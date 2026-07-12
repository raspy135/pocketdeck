# capture_stream.py - bounded in-memory output stream for Pocket Deck.
#
# A capture_stream is a drop-in replacement for the `vs` (vscreen_stream) that
# an app's main(vs, args) writes to: instead of drawing to a screen, everything
# written with print(..., file=vs) or vs.write(...) is captured in memory. Pass
# one as `vs` when you call another command's main() and want to collect its
# output (to return it, pipe it into another stage, or post-process it) rather
# than show it on screen.
#
# Capture is bounded to _MAX bytes so a runaway command can't exhaust RAM; once
# the cap is reached further writes are silently dropped. Read back the captured
# text with getvalue().
#
# Example:
#   import capture_stream
#   import mycmd
#   cap = capture_stream.capture_stream()
#   mycmd.main(cap, ['mycmd', 'arg'])
#   text = cap.getvalue()
#
# This is the same bounded-capture class the shell pipeline and the gpt agent
# tools use (it lives in pdeck_utils as CaptureStream); this module exposes it
# under the standard Pocket Deck lower-case module/class name.

import io


class capture_stream(io.IOBase):
  """Captures a command's stdout (it is passed as the `vs` to main()) so the
  output can be piped to the next stage or returned. Bounded so a runaway
  command can't exhaust RAM."""
  _MAX = 50000

  def __init__(self):
    self._parts = []
    self._total = 0

  def write(self, data):
    if isinstance(data, (bytes, bytearray)):
      data = data.decode('utf-8', 'replace')
    remaining = self._MAX - self._total
    if remaining <= 0:
      return
    if len(data) > remaining:
      data = data[:remaining]
    self._parts.append(data)
    self._total += len(data)

  def read(self, n=1):
    return ''

  def getvalue(self):
    return ''.join(self._parts)
