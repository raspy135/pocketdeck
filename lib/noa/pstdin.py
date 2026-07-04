# Piped stdin bridge for the command shell.
#
# Pocket Deck commands are modules exposing main(vs, args): they take input from
# file-path arguments and write output to `vs`. There is no real stdin. To make
# simple pipes ('a | b') work without changing that signature, the pipe driver
# stashes the previous stage's captured output here, and filter commands (head,
# tail, grep, cat) read it when they are given no file argument.
#
# Semantics are read-once: take() consumes the buffer so stale stdin can't leak
# into an unrelated later command.

_buf = None


def feed(text):
  """Store text for the next command to consume as stdin."""
  global _buf
  _buf = text


def has():
  """True if piped stdin is waiting to be read."""
  return _buf is not None


def peek():
  """Return the pending stdin without consuming it (None if empty)."""
  return _buf


def take():
  """Return the pending stdin and clear it (None if empty)."""
  global _buf
  b = _buf
  _buf = None
  return b
