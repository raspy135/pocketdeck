# pc_compat.py - lets gpt.py / gpt_l.py run on a normal PC (CPython).
#
# On the Pocket Deck these modules run under MicroPython and import a stack of
# device-only modules (pdeck, urequests, audio, ...). On a PC none of those
# exist, so install() registers lightweight stub modules in sys.modules BEFORE
# the device code imports them. Only what plain (non-agent) chat needs is real;
# agent tools, screen capture and voice are no-ops/disabled on PC.
#
# Detection: sys.implementation.name is 'micropython' on the device and
# 'cpython' on a PC. On the device this whole file is never imported.

import sys
import types

IS_PC = sys.implementation.name != 'micropython'


# ----------------------------------------------------------------------------
# vs stream replacement
# ----------------------------------------------------------------------------

class PCStream:
  """Stands in for the device's vscreen stream. The device code writes output
  with print(..., file=vs) and reads keys with vs.read(1). We map those to
  stdout/stdin. Deliberately has no `.v` attribute so ThinkingAnimation and the
  raw line editor fall back to their simple paths."""

  def write(self, s):
    if isinstance(s, (bytes, bytearray)):
      s = s.decode('utf-8', 'replace')
    sys.stdout.write(s)
    sys.stdout.flush()

  def read(self, n=1):
    return sys.stdin.read(n)

  def poll(self):
    return False


# ----------------------------------------------------------------------------
# esclib - real ANSI escapes (works in any terminal). Mirrors the device API.
# ----------------------------------------------------------------------------

class _esclib:
  def erase_screen(self):
    return "\x1b[2J"
  def home(self):
    return "\x1b[H"
  def erase_to_end_of_current_line(self):
    return "\x1b[K"
  def cur_up(self, num=1):
    return "\x1b[%dA" % num if num != 1 else "\x1b[A"
  def cur_down(self, num=1):
    return "\x1b[%dB" % num if num != 1 else "\x1b[B"
  def cur_left(self, num=1):
    return "\x1b[%dD" % num if num != 1 else "\x1b[D"
  def cur_right(self, num=1):
    return "\x1b[%dC" % num if num != 1 else "\x1b[C"
  def raw_mode(self, mode):
    return "\x1b[?1h" if mode else "\x1b[?1l"
  def cursor_mode(self, mode):
    return "\x1b[?25h" if mode else "\x1b[?25l"
  def wraparound_mode(self, mode):
    return "\x1b[?7h" if mode else "\x1b[?7l"
  def move_cursor(self, x, y):
    return "\x1b[%d;%dH" % (x, y)
  def set_font_color(self, color):
    return "\x1b[%dm" % color
  def reset_font_color(self):
    return "\x1b[39;22;23m"
  def bold(self):
    return "\x1b[1m"
  def bold_off(self):
    return "\x1b[22m"


# ----------------------------------------------------------------------------
# urequests - tiny stdlib-urllib HTTP shim with a urequests-like response
# ----------------------------------------------------------------------------

class _Response:
  def __init__(self, status_code, body):
    self.status_code = status_code
    self.content = body
    self.raw = None
    self.s = None

  @property
  def text(self):
    return self.content.decode('utf-8', 'replace')

  def json(self):
    import json
    return json.loads(self.content)

  def close(self):
    pass


def _post(url, headers=None, data=None):
  import urllib.request
  import urllib.error
  if isinstance(data, str):
    data = data.encode('utf-8')
  req = urllib.request.Request(url, data=data, headers=headers or {}, method='POST')
  try:
    resp = urllib.request.urlopen(req)
    return _Response(resp.getcode(), resp.read())
  except urllib.error.HTTPError as e:
    # Return the error body so the caller can surface the API error message.
    return _Response(e.code, e.read())


# ----------------------------------------------------------------------------
# Generic stub module: every attribute access yields a no-op callable
# ----------------------------------------------------------------------------

def _noop(*args, **kwargs):
  return None


class _StubModule(types.ModuleType):
  def __getattr__(self, name):
    return _noop


def _local_tz_quarter_hours():
  """The device stores its UTC offset as a count of 15-minute units; gpt code
  does time.gmtime(time()+pu.timezone*60*15). Compute the same for local time."""
  import time
  off = -time.timezone
  if time.localtime().tm_isdst and time.daylight:
    off = -time.altzone
  return int(round(off / 900.0))


def _module(name, **attrs):
  m = _StubModule(name)
  for k, v in attrs.items():
    setattr(m, k, v)
  return m


def _ensure(name, **attrs):
  """Like reg(), but cooperate with an already-registered module (e.g. another
  compat layer such as pem's own PC shims got there first): backfill only the
  attributes it's missing instead of skipping it. This is what lets `gpt` run
  from inside pem on a PC: pem registers a partial pdeck/pdeck_utils and we top
  it up with the bits (timezone, screen helpers, ...) that gpt also needs.

  When the module is absent we build a full _StubModule WITH these attrs in its
  __dict__ (so real values like timezone resolve normally and only *unlisted*
  attributes fall through to the no-op __getattr__). When it already exists we
  use honest hasattr() — foreign shims have no catch-all, so missing attrs read
  as absent and get filled, while their real methods are left untouched."""
  mod = sys.modules.get(name)
  if mod is None:
    sys.modules[name] = _module(name, **attrs)
    return sys.modules[name]
  for k, v in attrs.items():
    if not hasattr(mod, k):
      setattr(mod, k, v)
  return mod


def install():
  """Register PC stand-ins in sys.modules for every MicroPython/device module
  the gpt code imports. Idempotent and only registers names not already present
  (so a real module a user installed, e.g. a native binascii, still wins)."""
  if not IS_PC:
    return

  import json
  import binascii

  def reg(name, mod):
    if name not in sys.modules:
      sys.modules[name] = mod

  # MicroPython builtins -> stdlib equivalents
  reg('ujson', _module('ujson', dumps=json.dumps, loads=json.loads,
                       load=json.load, dump=json.dump))
  reg('ubinascii', binascii)
  reg('urequests', _module('urequests', post=_post))
  import socket as _socket
  reg('usocket', _socket)
  try:
    import ssl as _ssl
    reg('ussl', _ssl)
  except ImportError:
    pass

  # Device hardware / radio modules: pure no-op stubs
  for name in ('network', 'wifi', 'codec_config', 'audio', 'wav_play',
               'recorder', 'setuni'):
    reg(name, _StubModule(name))

  # Network availability check always passes on a PC
  reg('auto_connect', _module('auto_connect', check=lambda vs, silent=True: True))

  # pdeck: LEDs, clipboard, screen control -> no-ops / inert returns.
  # _ensure (not reg) so we top up an existing pdeck (e.g. pem's shim).
  _ensure('pdeck',
          led=_noop,
          clipboard_copy=_noop,
          clipboard_paste=lambda: b'',
          shared_filelist=_noop,
          delay_tick=_noop,
          get_screen_num=lambda: None,
          change_screen=_noop,
          show_screen_num=_noop,
          cmd_exists=lambda i: False,
          command_shell=lambda n: False,
          vscreen=lambda: _StubModule('vscreen'))

  # pdeck_utils: timezone (quarter-hours), empty app list, no-op launch.
  # CaptureStream must be a real class (gpt_tools subclasses it at import),
  # matching the device interface: bounded write + getvalue.
  class _CaptureStream:
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

  _ensure('pdeck_utils',
          timezone=_local_tz_quarter_hours(),
          app_list={},
          launch=_noop,
          CaptureStream=_CaptureStream)

  reg('pngwriter', _module('pngwriter', encode_mono_xbm=_noop))
  reg('esclib', _module('esclib', esclib=_esclib))
