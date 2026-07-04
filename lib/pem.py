#
# Pem -- A editor for pocket deck
# Copyright Nunomo LLC

import sys

# When launched as `python -m pem` (or `pem.py`) this file runs as __main__, so
# erow's `from pem import _hl_line` would re-import it under the name `pem` and
# hit a circular import. Alias `pem` to the running __main__ module so that
# import resolves to us. PC-only: on the device pem is imported as `pem`.
if __name__ == '__main__':
  sys.modules.setdefault('pem', sys.modules['__main__'])

# const() is a bare builtin on the device's MicroPython, but not on CPython.
# Define a no-op mock for PC only (leaving the device path untouched) so that
# module-level uses like `IM_EN = const(1)` work even when pdeck imports
# successfully on PC -- e.g. running against the emulator stubs -- and the
# CPython fallback block below is skipped.
if sys.implementation.name != 'micropython':
  def const(x):
    return x

# The same source runs on the Pocket Deck (MicroPython) and on desktop CPython
# (for development and testing). The device exposes a native `pdeck` module; if
# it can't be imported we're on CPython, so set up a pure-Python fallback layer
# up front -- before importing any device helper modules -- so the rest of the
# file (and those helpers) is left unchanged.
try:
  import pdeck
  pdeck_enabled = True
except ImportError:
  pdeck_enabled = False
  import time, types, unicodedata

  # MicroPython exposes these as builtins; provide CPython equivalents.
  if not hasattr(time, 'sleep_ms'):
    time.sleep_ms = lambda ms: time.sleep(ms / 1000)
  if not hasattr(time, 'ticks_us'):
    time.ticks_us = lambda: int(time.perf_counter() * 1000000)

  class _pdeck_shim:
    # Stand-in for the device's native `pdeck` module. Only the calls reachable
    # on the CPython path are implemented; the rest are no-ops so device helper
    # modules that `import pdeck` still load.
    def get_utf8_width(self, ch):
      # ch may be an int code point, a 1-char str, or a bytes/bytearray slice.
      if isinstance(ch, int):
        ch = chr(ch)
      elif isinstance(ch, (bytes, bytearray)):
        try:
          ch = ch.decode('utf-8')
        except Exception:
          return 1
        if not ch:
          return 1
        ch = ch[0]
      return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1

    def clipboard_copy(self, data):
      pass

    def clipboard_paste(self):
      return b''

    def shared_filelist(self, filename):
      pass

    def delay_tick(self, n):
      time.sleep_ms(n)

    def led(self, *a):
      pass

    def wifi_connected(self):
      return True

  pdeck = _pdeck_shim()
  sys.modules['pdeck'] = pdeck

  # The local MicroPython `argparse` port (and other helpers) import
  # `pdeck_utils`; provide just the stdout-backed stream it needs.
  _pdeck_utils = types.ModuleType('pdeck_utils')
  class _vscreen_stream:
    def write(self, s):
      sys.stdout.write(s)
    def flush(self):
      sys.stdout.flush()
  _pdeck_utils.vscreen_stream = _vscreen_stream
  sys.modules['pdeck_utils'] = _pdeck_utils

  # jp_input imports MicroPython's `network` and gates kana conversion on a
  # connected WLAN. On the desktop we're effectively always online, so a shim
  # whose isconnected() is True lets the (local) romaji->hiragana path run; the
  # online henkan step keeps its own try/except for when there's no network.
  _network = types.ModuleType('network')
  _network.STA_IF = 0
  class _WLAN:
    def __init__(self, *a):
      pass
    def isconnected(self):
      return True
  _network.WLAN = _WLAN
  sys.modules['network'] = _network

import pem_keymap_default as km

open_pending_list= []

# Remote AI edit queue, drained the same way as open_pending_list: the editor's
# read loop notices a pending request and synthesizes REMOTE_EDIT_KEY, which
# process_key services on the editor's own thread (the only place it is safe to
# mutate rows and re-render). Each item is [line_from, line_to, content, result],
# where result is a dict the requesting thread polls for completion.
edit_pending_list = []
# Remote AI buffer-switch queue, drained the same way (on the editor's thread via
# REMOTE_EDIT_KEY). Each item is [filename, result]; result is a dict the
# requesting thread polls for completion.
switch_pending_list = []
# Internal sentinel returned by read(); a multi-byte value no real key produces.
REMOTE_EDIT_KEY = b'\x00\x11pem_edit'

try:
  import pem_keymap as custom_keymap
  custom_keymap.init_custom(km)
  import pem_extra
  pem_extra.init_custom(km)
except Exception as e:
  print(e)
  pass

loaded = True

import re
if not pdeck_enabled:
  import termios
  import select

import os
import time
import esclib as elib
import argparse
import array

# Where the "resume last file" state is stored. The device keeps it under
# /config; on CPython that path doesn't exist, so use the home directory.
if pdeck_enabled:
  PEM_FILELIST = '/config/pem_filelist.txt'
else:
  PEM_FILELIST = os.path.join(os.path.expanduser('~'), '.pem_filelist.txt')

# Device-only helper modules. They pull in MicroPython-only modules (network,
# pdeck_utils, ...), so on CPython we import what we can and degrade gracefully:
# Japanese input and filename TAB-completion are simply unavailable.
try:
  import jp_input
except Exception:
  jp_input = None
try:
  import ls
except Exception:
  ls = None
try:
  import auto_connect
except Exception:
  auto_connect = None

el = elib.esclib()

IM_EN = const(1)
IM_JP = const(2)

import benchmark
bm = benchmark.benchmark(False)

def _basename(p):
    if p.endswith("/") and p != "/":
        p = p[:-1]
    i = p.rfind("/")
    return p if i < 0 else p[i + 1 :]

def _dirname(p):
    if p.endswith("/") and p != "/":
        p = p[:-1]
    i = p.rfind("/")
    if i < 0:
        return "."
    return p[:i] or "/"

def _trim_path(path, maxlen):
  # Shorten a long path for the status bar while keeping the informative tail
  # (the filename and as many trailing folders as fit). A leading '*' marks
  # that some parent folders were dropped, e.g.
  #   /long/path/to/the/file/structure.md -> *the/file/structure.md
  if maxlen <= 0 or len(path) <= maxlen:
    return path
  parts = path.split('/')
  # Always keep the last component (the filename), tail-truncated if it alone
  # is still too long to fit alongside the '*' marker.
  result = parts[-1]
  if len(result) + 1 > maxlen:
    return '*' + result[-(maxlen - 1):]
  # Grow leftward one whole component at a time while it still fits.
  for i in range(len(parts) - 2, -1, -1):
    candidate = parts[i] + '/' + result
    if len(candidate) + 1 > maxlen:
      break
    result = candidate
  return '*' + result

def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

def _expand_user(path):
  # '~' / '~/...' home-directory shortcut is a desktop convenience; the device
  # has no home directory, so only expand it on CPython.
  if not pdeck_enabled and path and path[0] == '~':
    return os.path.expanduser(path)
  return path

def _is_dir(path):
  # 0x4000 is S_IFDIR on both CPython and MicroPython stat results.
  try:
    return (os.stat(path)[0] & 0x4000) != 0
  except OSError:
    return False

# ---- Syntax highlighting ----
_PY_KEYWORDS = frozenset([
  'if','elif','else','for','while','def','class','return',
  'import','from','and','or','not','in','is','True','False','None',
  'try','except','finally','with','as','pass','break','continue',
  'raise','yield','lambda','del','global','nonlocal',
])
_PY_KEYWORDS_B = frozenset([
  b'if',b'elif',b'else',b'for',b'while',b'def',b'class',b'return',
  b'import',b'from',b'and',b'or',b'not',b'in',b'is',b'True',b'False',b'None',
  b'try',b'except',b'finally',b'with',b'as',b'pass',b'break',b'continue',
  b'raise',b'yield',b'lambda',b'del',b'global',b'nonlocal',
])
_C_KEYWORDS_B = frozenset([
  b'auto',b'break',b'case',b'char',b'const',b'continue',b'default',b'do',
  b'double',b'else',b'enum',b'extern',b'float',b'for',b'goto',b'if',b'inline',
  b'int',b'long',b'register',b'restrict',b'return',b'short',b'signed',b'sizeof',
  b'static',b'struct',b'switch',b'typedef',b'union',b'unsigned',b'void',
  b'volatile',b'while',b'bool',b'true',b'false',b'NULL',
  # common C++ extras so .h/.cpp also look reasonable
  b'class',b'namespace',b'template',b'public',b'private',b'protected',
  b'new',b'delete',b'this',b'using',b'virtual',b'nullptr',
])
_B_HL_OFF = b'\x1b[0m'
if pdeck_enabled:
  # The device's mono terminal only understands attribute SGRs (bold), so every
  # category maps to bold; comments/strings stay plain, matching the old look.
  _HL_KEYWORD = b'\x1b[1m'
  _HL_COMMENT = None
  _HL_STRING  = None
  _HL_HEADING = b'\x1b[1m'
  _HL_EMPH    = b'\x1b[1m'
  _HL_LINK    = b'\x1b[1m'
else:
  # Desktop terminals support ANSI color, so give each token type its own hue.
  _HL_KEYWORD = b'\x1b[38;5;204m'    # pink   keywords
  _HL_COMMENT = b'\x1b[38;5;245m'    # gray   comments
  _HL_STRING  = b'\x1b[38;5;114m'    # green  strings
  _HL_HEADING = b'\x1b[1;38;5;39m'   # bold blue   md headings
  _HL_EMPH    = b'\x1b[1;38;5;214m'  # bold orange md **emphasis**
  _HL_LINK    = b'\x1b[4;38;5;81m'   # underlined cyan md links
_B_HL_ON = _HL_KEYWORD  # backward-compatible alias

def _is_id_cont(c):
  return c.isalpha() or c.isdigit() or c == '_'

def _is_id_cont_b(c):
  return (65 <= c <= 90) or (97 <= c <= 122) or (48 <= c <= 57) or c == 95

def _hl_md(b):
  if type(b) is not bytes:
    b = bytes(b)
  if not b:
    return None
  if b[0] == 35:  # '#' heading — wrap whole line
    idx = 0
    while len(b) > idx and b[idx] == 35:
      idx += 1
    # if # is not followed by space, it's a tag.
    if len(b) > idx and b[idx] == 0x20:
      return b''.join([_HL_HEADING, b, _B_HL_OFF])

  if b'**' not in b and b'[' not in b and b'#' not in b:
    return None
  parts = []
  append = parts.append
  i = 0
  n = len(b)
  modified = False
  while i < n:
    c = b[i]
    if c == 42 and i + 1 < n and b[i + 1] == 42:  # '**'
      j = b.find(b'**', i + 2)
      if j != -1:
        append(_HL_EMPH); append(b[i:j + 2]); append(_B_HL_OFF)
        modified = True
        i = j + 2
        continue
    elif c == 91:  # '['
      if i > 0 and b[i-1] == 0x1b:
        append(b[i:i+1])
        i += 1
        continue
      if i + 1 < n and b[i + 1] == 91:  # '[['
        j = b.find(b']]', i + 2)
        if j != -1:
          append(_HL_LINK); append(b[i:j + 2]); append(_B_HL_OFF)
          modified = True
          i = j + 2
          continue
      else:
        j = b.find(b']', i + 1)
        if j != -1:
          append(_HL_LINK); append(b[i:j + 1]); append(_B_HL_OFF)
          modified = True
          i = j + 1
          continue
    elif c == 35:  # '#'
      j = b.find(b' ', i + 1)
      if j == -1:
        j=len(b)-1
      append(_HL_HEADING); append(b[i:j + 1]); append(_B_HL_OFF)
      modified = True
      i = j + 1
      continue

    append(b[i:i + 1])
    i += 1
  if not modified:
    return None
  return b''.join(parts)

def _hl_py(b):
  if type(b) is not bytes:
    b = bytes(b)
  parts = []
  append = parts.append
  i = 0
  n = len(b)
  modified = False
  while i < n:
    c = b[i]
    if c == 35:  # '#' comment runs to end of line
      if _HL_COMMENT is None:
        append(b[i:])
      else:
        append(_HL_COMMENT); append(b[i:]); append(_B_HL_OFF)
        modified = True
      break
    if _HL_STRING is not None and (c == 34 or c == 39):  # " or ' string literal
      j = i + 1
      while j < n:
        if b[j] == 92:  # backslash escapes the next byte
          j += 2
          continue
        if b[j] == c:
          j += 1
          break
        j += 1
      append(_HL_STRING); append(b[i:j]); append(_B_HL_OFF)
      modified = True
      i = j
      continue
    if (65 <= c <= 90) or (97 <= c <= 122) or c == 95:  # isalpha or '_'
      j = i + 1
      while j < n and _is_id_cont_b(b[j]):
        j += 1
      word = b[i:j]
      if word in _PY_KEYWORDS_B:
        append(_HL_KEYWORD)
        append(word)
        append(_B_HL_OFF)
        modified = True
      else:
        append(word)
      i = j
    else:
      append(b[i:i + 1])
      i += 1
  if not modified:
    return None
  return b''.join(parts)

def _hl_c(b):
  # Like _hl_py but with C tokens: // and /* */ comments, "..."/'...' literals,
  # C keywords. Note '#' is a preprocessor directive in C, not a comment.
  if type(b) is not bytes:
    b = bytes(b)
  parts = []
  append = parts.append
  i = 0
  n = len(b)
  modified = False
  while i < n:
    c = b[i]
    if c == 47 and i + 1 < n and b[i + 1] == 47:  # '//' line comment
      if _HL_COMMENT is None:
        append(b[i:])
      else:
        append(_HL_COMMENT); append(b[i:]); append(_B_HL_OFF)
        modified = True
      break
    if c == 47 and i + 1 < n and b[i + 1] == 42:  # '/*' block comment
      j = b.find(b'*/', i + 2)
      end = (j + 2) if j != -1 else n   # unterminated -> to end of line
      if _HL_COMMENT is None:
        append(b[i:end])
      else:
        append(_HL_COMMENT); append(b[i:end]); append(_B_HL_OFF)
        modified = True
      i = end
      continue
    if _HL_STRING is not None and (c == 34 or c == 39):  # " string or ' char
      j = i + 1
      while j < n:
        if b[j] == 92:  # backslash escapes the next byte
          j += 2
          continue
        if b[j] == c:
          j += 1
          break
        j += 1
      append(_HL_STRING); append(b[i:j]); append(_B_HL_OFF)
      modified = True
      i = j
      continue
    if (65 <= c <= 90) or (97 <= c <= 122) or c == 95:  # isalpha or '_'
      j = i + 1
      while j < n and _is_id_cont_b(b[j]):
        j += 1
      word = b[i:j]
      if word in _C_KEYWORDS_B:
        append(_HL_KEYWORD)
        append(word)
        append(_B_HL_OFF)
        modified = True
      else:
        append(word)
      i = j
    else:
      append(b[i:i + 1])
      i += 1
  if not modified:
    return None
  return b''.join(parts)

def _hl_line(line_bytes, mode):
  if not line_bytes:
    return line_bytes
  if mode == 'py':
    out = _hl_py(line_bytes)
  elif mode == 'md':
    out = _hl_md(line_bytes)
  elif mode == 'c':
    out = _hl_c(line_bytes)
  else:
    return line_bytes
  return line_bytes if out is None else out

class editor:
  def __init__(self,v, japanese):
    # enum
    self.MODE_NORMAL = 0
    self.MODE_SEARCH = 1
    self.MODE_SELECT_DIALOG = 2
    self.MODE_INPUT_LINE_DIALOG = 3
    self.MODE_REPLACE = 4
    self.IM_EN = 1
    self.IM_JP = 2
    self.h_diff = 1
    self.v = v
    self.vs = None  # set in main(); used to record file-open events (None on PC)
    self.in_ext_mode = False
    self.pending_keys = None
    self._chord_items = []
    self._chord_saved_scroll = None
    self.should_quit = False

    # Load Japanese font
    if japanese:
      self.load_jpfont()

    self.mode = self.MODE_NORMAL
    self.text_width, self.text_height = v.get_terminal_size()
    self.yankbuf = yank_buffer()
    self.text_height -= 1
    self.adding_yank = False
    self.search_info = search_info()
    self.status_message =""
    self.status_message_life = 0
    self.file_list = []
    self.input_answer_list = None
    self.dmod = True
    # For select dialog
    self.sd_info = None

    # For input line dialog
    self.sl_info = None
    
    # file_row and col indicates cursor
    #  positon in file (not screen)
    self.file_row = 0
    self.file_col = 0

    # scroll_row and col indicates scroll
    # position. row is file row #, col is screen col shift
    self.scroll_row = 0
    self.scroll_col = 0

    # cursor position on display
    self.d_row = 0
    self.d_col = 0
    self.wished_d_col = 0 # screen col wanted (but it was not possible because it's more than the line length)

    # line number informaton on display [linenum, start_col]
    self.line_num_list = []
    self.tab_size = 2
    self.jpfont_loaded = False

  def record_event(self, content):
    # self.vs is None on PC (only set in main() on the device), so skip there.
    if self.vs is not None:
      self.vs.record_event(content)

  def load_jpfont(self):
    # The device must load a CJK bitmap font into its terminal; a desktop
    # terminal already renders Japanese with its own font, so this is a no-op.
    if not pdeck_enabled:
      self.jpfont_loaded = True
      return
    import fontloader
    #fontname = 'font_unifont_japanese3'
    fontname = 'unifont_large'
    fontloader.load(fontname)

    font = fontloader.font_list[fontname]
    self.v.v.set_terminal_font(font,font,8,16)
    self.jpfont_loaded = True
    

  def exit(self):
    self.v.print(el.raw_mode(False))
    #self.v.print(el.wraparound_mode(False))
    
  def pub_open_file(self, filename, linenum=1, colnum=1):
    # Remote-control entry point (see the pem_open command). This runs on a
    # different task than the editor loop, so it must NOT touch screen/render
    # state directly. Instead it queues the request onto open_pending_list,
    # which the editor's own read loop drains as a synthesized C-x C-f
    # (open-file) key. linenum/colnum are 1-based, matching the open-file
    # handler and the desktop pem_client protocol.
    open_pending_list.append((filename, linenum, colnum))

  def pub_get_status(self):
    # Remote/AI read-only status. Safe to call from another task: it only reads
    # scalar editor state (no rows mutation, no rendering). Row/col are 1-based to
    # match the status line and pub_edit_block. Returns a dict.
    cur = self.file
    open_files = []
    for f in [cur] + self.file_list:
      open_files.append(f.filename if f.filename is not None else '** New file **')
    return {
      'filename': cur.filename,
      'row': self.file_row + 1,
      'col': self.file_col + 1,
      'num_lines': len(cur.rows),
      'modified': cur.modified,
      'open_files': open_files,
    }

  def pub_edit_block(self, line_from, line_to, content, timeout_ms=4000):
    # Remote/AI entry point: replace lines [line_from, line_to] (1-based,
    # inclusive) of the CURRENT file with `content`. Like pub_open_file this runs
    # on a different task than the editor loop, so it must NOT touch rows/render
    # here. Queue the request and block (bounded) until the editor's own loop
    # applies it via drain_remote_edits and fills in `result`. Returns
    # (ok: bool, message: str).
    result = {'done': False, 'ok': False, 'msg': ''}
    item = [line_from, line_to, content, result]
    edit_pending_list.append(item)
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while not result['done']:
      if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
        try:
          edit_pending_list.remove(item)
        except ValueError:
          pass  # the editor picked it up between our check and removal
        if not result['done']:
          return (False, 'timeout: editor did not apply the edit (is PEM running and at the main editing screen?)')
        break
      time.sleep_ms(20)
    return (result['ok'], result['msg'])

  def drain_remote_edits(self):
    # Runs on the editor's own thread (via the synthesized REMOTE_EDIT_KEY in
    # process_key), so it is safe to mutate rows and request a redraw here.
    applied = False
    while edit_pending_list:
      line_from, line_to, content, result = edit_pending_list.pop(0)
      try:
        ok, msg = self._apply_edit_block(line_from, line_to, content)
      except Exception as e:
        ok, msg = False, 'edit failed: %s' % str(e)
      result['ok'] = ok
      result['msg'] = msg
      result['done'] = True
      if ok:
        applied = True
    if applied:
      self.dmod = True  # main loop re-renders after process_key returns

  def _apply_edit_block(self, line_from, line_to, content):
    f = self.file
    nrows = len(f.rows)
    if not (isinstance(line_from, int) and isinstance(line_to, int)):
      return (False, 'line_from and line_to must be integers (1-based)')
    if line_from < 1 or line_to < line_from:
      return (False, 'invalid range: need 1 <= line_from <= line_to')
    if line_from > nrows + 1:
      return (False, 'line_from %d is past end of file (%d lines)' % (line_from, nrows))
    if line_to > nrows:
      line_to = nrows
    # Build the replacement rows from `content` (newline-separated). An empty
    # string deletes the range outright (no blank line left behind); the
    # at-least-one-row safeguard below keeps an emptied file valid.
    new_rows = []
    if content != "":
      for ln in content.split('\n'):
        row = erow(ln.encode('utf-8'), f.tab_size, f.w)
        row.hl_mode = f.mode
        new_rows.append(row)
    # Snapshot for undo BEFORE mutating so the user can C-z the AI's edit.
    f.undo.record(self, 'other')
    f.rows[line_from - 1:line_to] = new_rows
    # A file must always have at least one row for the renderer/cursor logic.
    if len(f.rows) == 0:
      row = erow(b"", f.tab_size, f.w)
      row.hl_mode = f.mode
      f.rows.append(row)
    f.modified = True
    f.num_updated = 0  # force syntax re-highlight from the top
    # Clamp the cursor into the (possibly shorter) buffer.
    if self.file_row >= len(f.rows):
      self.file_row = len(f.rows) - 1
      self.file_col = 0
    rlen = f.rows[self.file_row].get_len()
    if self.file_col > rlen:
      self.file_col = rlen
    if len(new_rows) == 0:
      return (True, 'deleted lines %d-%d; file now has %d line(s)'
                    % (line_from, line_to, len(f.rows)))
    return (True, 'replaced lines %d-%d with %d line(s); file now has %d line(s)'
                  % (line_from, line_to, len(new_rows), len(f.rows)))

  def pub_read_content(self, line_from=1, line_to=None):
    # Remote/AI read-only access to the CURRENT file's text. Safe to call from
    # another task: it only reads rows (like pub_get_status). line_from/line_to
    # are 1-based and INCLUSIVE; line_to=None (or beyond EOF) reads to the end.
    # Returns (ok: bool, text-or-error: str). The text is newline-joined.
    f = self.file
    nrows = len(f.rows)
    try:
      line_from = int(line_from)
    except (TypeError, ValueError):
      return (False, 'line_from must be an integer (1-based)')
    if line_to is None:
      line_to = nrows
    else:
      try:
        line_to = int(line_to)
      except (TypeError, ValueError):
        return (False, 'line_to must be an integer (1-based) or null')
    if line_from < 1:
      line_from = 1
    if line_to > nrows:
      line_to = nrows
    if line_from > nrows:
      return (True, '')  # range starts past EOF -> empty
    if line_to < line_from:
      return (False, 'invalid range: need line_from <= line_to')
    lines = []
    for i in range(line_from - 1, line_to):
      lines.append(f.rows[i].decode())
    return (True, '\n'.join(lines))

  def pub_switch_buffer(self, filename, timeout_ms=4000):
    # Remote/AI entry point: make `filename` (one of the already-open buffers) the
    # current editing file. Mutates editor state + renders, so (like pub_edit_block)
    # it queues the request and blocks (bounded) until the editor's own loop applies
    # it via drain_remote_edits. Returns (ok: bool, message: str).
    result = {'done': False, 'ok': False, 'msg': ''}
    item = [filename, result]
    switch_pending_list.append(item)
    deadline = time.ticks_add(time.ticks_ms(), timeout_ms)
    while not result['done']:
      if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
        try:
          switch_pending_list.remove(item)
        except ValueError:
          pass  # the editor picked it up between our check and removal
        if not result['done']:
          return (False, 'timeout: editor did not switch buffer (is PEM running and at the main editing screen?)')
        break
      time.sleep_ms(20)
    return (result['ok'], result['msg'])

  def drain_remote_switches(self):
    # Runs on the editor's own thread (see drain_remote_edits). Safe to switch the
    # current buffer and re-render here.
    applied = False
    while switch_pending_list:
      filename, result = switch_pending_list.pop(0)
      try:
        ok, msg = self._apply_switch_buffer(filename)
      except Exception as e:
        ok, msg = False, 'switch failed: %s' % str(e)
      result['ok'] = ok
      result['msg'] = msg
      result['done'] = True
      if ok:
        applied = True
    if applied:
      self.dmod = True

  def _apply_switch_buffer(self, filename):
    if not isinstance(filename, str) or filename == '':
      return (False, 'filename must be a non-empty string')
    cur = self.file.filename
    if cur == filename or cur == filename + '.md':
      return (True, '%s is already the current buffer' % filename)
    # switch_buf_if_exists matches against self.file_list and switches via
    # process_file_select (the same path the file-select menu uses).
    if self.switch_buf_if_exists(filename):
      return (True, 'switched to %s' % (self.file.filename or '** New file **'))
    open_names = []
    for f in [self.file] + self.file_list:
      open_names.append(f.filename if f.filename is not None else '** New file **')
    return (False, '%s is not open; open buffers: %s' % (filename, ', '.join(open_names)))

  def open(self, filename, linenum=0, colnum=0):
    self.file = editor_file(self.v, filename, self.text_height, self.text_width - 1, self.tab_size)
    self.file_row, self.file_col = self.file.open(linenum, colnum)
    self.v.background_update=self.file.background_update
    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)

  def setup_screen(self):
    self.v.set_raw_mode(True)
    #self.v.print(el.wraparound_mode(False))
    self.v.print(el.erase_screen())    

  
  def render_main_text(self, dry_run = False):
    # When dry_run is True, it won't print chars
    # It's useful to update list_num_list and d_row,d_col
    self.line_num_list = self.file.file_refresh_screen(self.scroll_row, self.scroll_col, self.file_row, self.file_col, dry_run)

  def update_d_cursor(self):
    #figure out cursor position
    file_row = self.file_row
    file_col = self.file_col
    if self.file.im_session:
      file_col += self.file.im_session.col
    #print(f'row,col={file_row},{file_col}')
    llen = len(self.line_num_list)
    for num in self.line_num_list:
      
      if num[1] == file_row:
        d_cur_row = num[0]
        row = self.file.rows[num[1]]
        # Not the end of the screen
        if num[0]+1 < llen:
          # Next line is different row
          cond = self.line_num_list[num[0]+1][1] != file_row
        else:
          cond = True
        if row.expanded_to_pos(num[2],self.file.w) == file_col and cond:
          self.d_row = d_cur_row
          self.d_col = row.cpos_to_dpos(file_col, True) - row.cpos_to_dpos(num[2]) #row.expand(num[2], file_col)
          #print("cursor2 {},{}".format(self.d_row+1, self.d_col+1))
          break
        
        maybe_d_col = row.cpos_to_dpos(file_col, True) - row.cpos_to_dpos(num[2])
        
        if num[0]+1 < llen:
          if self.line_num_list[num[0]+1][1] == num[1] and file_col == self.line_num_list[num[0] + 1][2]:
            self.d_row = d_cur_row + 1
            self.d_col = 0
            break

        if self.file.w > maybe_d_col:
          self.d_row = d_cur_row
          self.d_col = maybe_d_col #row.expand(num[2], file_col)
          #print("cursor {},{}".format(self.d_row+1, self.d_col+1))
          break

  def print_input_line_dialog(self):
    self.v.print(el.set_font_color(7)) #invert
    title = f"  ** {self.sl_info.subject} ** "
    # Clamp to the screen width so a long subject can't wrap and corrupt the
    # layout (mirrors print_select_dialog). Padding is "" when already over.
    self.v.print(title[:self.text_width] + " "*(self.text_width - len(title)))
    self.v.print("\r\n")
    self.v.print(el.set_font_color(0))
    
    self.v.print(f"{self.sl_info.header}: {self.sl_info.line.decode()}")
    self.v.print(el.erase_to_end_of_current_line())

  def new_erow(self, chars, tab_size, w=200):
    return erow(chars, tab_size, w)

  def print_select_dialog(self):
    self.v.print(el.set_font_color(7)) #invert
    # Show the incremental-search query (if any) in the title bar.
    if self.sd_info.query:
      title = f"  ** {self.sd_info.subject} ** {self.sd_info.query}"
    else:
      title = f"  ** {self.sd_info.subject} ** "
    self.v.print(title[:self.text_width] + " "*(self.text_width - len(title)))
    self.v.print("\r\n")

    # Display the filtered view (indices into slist that match the query).
    b_list = [self.sd_info.dlist[idx] for idx in self.sd_info.filtered[self.sd_info.scroll:]]

    self.v.print(el.move_cursor(self.text_height +2,1))
    #print(f"bufs {b_list}")
    for i in range(0,self.sd_info.height):
      if i >= len(b_list):
        self.v.print("~")
        self.v.print(el.erase_to_end_of_current_line())
      else:
        buf=b_list[i]
        if(i == self.sd_info.cur):
          self.v.print(el.set_font_color(7)) #invert
        else:
          self.v.print(el.set_font_color(0))
        self.v.print(f"{i+self.sd_info.scroll+1} :")
        self.v.print(el.set_font_color(0))
        self.v.print(" {}".format(buf[:self.text_width].replace('\n',' ')))
        self.v.print(el.erase_to_end_of_current_line())
      if i != self.sd_info.height - 1:
        self.v.print("\r\n")


  def refresh_screen(self):
    bm.start_bench()

    # Batch the whole frame into a single write+flush (desktop only; no-op on
    # device) so the cursor hide/redraw/show doesn't flicker on PC terminals.
    self.v.begin_frame()

    # Hide the cursor for the whole frame up front. On a PC terminal the real
    # hardware caret sits at the last write position, so any redraw that doesn't
    # end by repositioning+showing it (select dialog) or that skips the main
    # render (dmod False / dialogs opened with a dry-run render) would leave the
    # caret stranded at a "random" spot. Hiding here unconditionally and letting
    # each mode below re-show it after a move makes cursor visibility
    # deterministic. No-op visually on device (cursor is composited).
    self.v.print(el.cursor_mode(False))

    # While a region mark is active, re-render every refresh so the highlight
    # tracks the moving cursor (plain cursor moves otherwise skip rendering).
    if self.dmod or self.file.mark_row is not None:
      self.render_main_text()
      self.dmod = False
    #else:
    #  print("no update")
    bm.add_bench('render')
    self.update_d_cursor()
    bm.add_bench('update_d')

    #status bar
    self.v.print(el.move_cursor(self.text_height + 1, 1))

    if self.status_message_life > 0:
      self.v.print(" [ ")
      self.v.print(self.status_message)
      self.v.print(" ] ")
      self.status_message_life -= 1
    else:
      if self.mode == self.MODE_NORMAL:
        stbout = []
        stbout.append((el.set_font_color(7))) #invert
        filename = self.file.filename
        if filename == None:
          filename = '** New file **'
        filestat = f"{'*' if self.file.modified else '-'} L:{self.file_row+1}/{len(self.file.rows)} C:{self.file_col+1}"

        max_filename_length = self.file.w - (len(filestat) + 5 + 2 + 2 + 1 + 2)
        if len(filename) > max_filename_length:
          # Trim parent folders (not the filename) and mark with a leading '*'.
          filename = _trim_path(filename, max_filename_length)
        filestat = filename + " " + filestat
        
        filestat_left = f"Mode:{'EN' if self.file.input_method == self.IM_EN else 'JP'},{self.file.mode}"
        statline = filestat + " " * (self.text_width - len(filestat) - len(filestat_left)) + filestat_left
        #self.v.print(statline)
        stbout.append(statline)
        self.v.print(''.join(stbout))
      if self.mode == self.MODE_SEARCH:
        searchstat = f"Search: {self.search_info.query_str}"
        if self.search_info.matched_query == None:
          searchstat += " : Not found"
        statline = searchstat + " " * (self.text_width - len(searchstat))
        self.v.print(statline)

      if self.sd_info: #mode == self.MODE_SELECT_DIALOG:
        self.print_select_dialog()
      if self.sl_info: #mode == self.MODE_INPUT_LINE_DIALOG:
        self.print_input_line_dialog()

    if self.mode == self.MODE_SELECT_DIALOG:
      pass  # keep cursor hidden while dialog is open
    elif self.mode == self.MODE_INPUT_LINE_DIALOG:
      # Position cursor at the end of input or current cursor position in input
      prompt_len = len(self.sl_info.header) + 2
      self.v.print(el.move_cursor(self.text_height + 2, prompt_len + self.sl_info.cur + 1))
      self.v.print(el.cursor_mode(True))
    else:
      self.v.print(el.reset_font_color() + el.move_cursor(self.d_row +1, self.d_col + 1))

      #if (self.mode == self.MODE_REPLACE or self.mode == self.MODE_SEARCH) and
      if self.search_info.matched_query != None:
        out = el.set_font_color(4) #underline
        offset = len(self.search_info.matched_query) + self.d_col - self.file.w
        #print(f"offset {offset}")
        if  offset > 0:
          out += self.search_info.matched_query[:-offset]
          out += "\r\n"
          out += self.search_info.matched_query[-offset:]
        else:
          out += self.search_info.matched_query
        out += el.move_cursor(self.d_row +1, self.d_col + 1)
        #out += el.cur_left(len(self.search_info.matched_query))
        #out += _B_HL_OFF
        #el.reset_font_color()
        self.v.print(out)
      self.v.print(_B_HL_OFF)
      self.v.print(el.cursor_mode(True))
    
    bm.add_bench('status bar')
    self.v.end_frame()
    bm.print_bench()

  def cursor_move(self, a_row, a_col):
    row = a_row
    col = a_col
    while row != 0 or col != 0:
      #print(f"{row}, {col}")
      row, col = self.cursor_move_loop(row,col)

  def cursor_move_loop(self, a_row, a_col):
    row = a_row
    col = a_col
    #print(f"row1 {row}")
    if row < 0:
      request_col = self.wished_d_col if self.wished_d_col != -1 else self.d_col
      filepos = self.file.scr_to_filepos(self.file.h, self.file.w, self.d_row - 1, request_col)
      #print(f"filepos {filepos}")
      
      if filepos:
        self.file_row = filepos[0]        
        self.file_col = filepos[1]
        rlen = self.file.rows[self.file_row].len
        if self.file_col >= rlen:
          self.file_col = rlen
          if self.wished_d_col == -1:
            self.wished_d_col = self.d_col
      row += 1
    #print(f"row {row}")
    if row > 0:
      request_col = self.wished_d_col if self.wished_d_col != -1 else self.d_col
      # print(f' Req: {request_col}')
      filepos = self.file.scr_to_filepos(self.file.h, self.file.w, self.d_row + 1, request_col)
      if filepos:
        self.file_row = filepos[0]        
        self.file_col = filepos[1]
        rlen = self.file.rows[self.file_row].len
        if self.file_col >= rlen:
          self.file_col = rlen
          if self.wished_d_col == -1:
            self.wished_d_col = self.d_col
            #print(f'wished_d_col {self.wished_d_col}')
      row -= 1
    #print(f"row {row}")
    if col < 0:
      self.wished_d_col = -1
      nextcol = self.file_col - 1
      if nextcol == -1:
        if self.file_row > 0:
          self.file_row -= 1
          self.file_col = self.file.rows[self.file_row].len
      else:
        self.file_col = nextcol
      col += 1
    if col > 0:
      self.wished_d_col = -1
      nextcol = self.file_col + 1
      if nextcol == self.file.rows[self.file_row].len + 1:
        if self.file_row < len(self.file.rows) - 1:
          self.file_row += 1
          self.file_col = 0
      else:
        self.file_col = nextcol
      col -= 1

    self.update_scroll_for_curmove()
    return row,col

  def update_scroll_for_curmove(self, offset = 0):
    while self.update_scroll_for_curmove_one(offset):
      self.line_num_list = self.file.line_num_list = self.file.gen_line_num_list(self.scroll_row, self.scroll_col ,0, self.file.h - 1)
        
  def update_scroll_for_curmove_one(self, offset = 0):
    file_col = self.file_col + offset
    range = self.file.in_screen(self.file_row,file_col)
    if range == -1:
      self.dmod = True
      #self.scroll_row -= 1
      lnl = self.file.gen_line_num_list(self.line_num_list[0][1],self.line_num_list[0][2], -1,0)
      self.scroll_row = lnl[0][1]
      self.scroll_col = lnl[0][2]
      return True
      
    if range == 1:
      self.dmod = True
      #self.scroll_row += 1
      lnl = self.line_num_list
      self.scroll_row = lnl[1][1]
      self.scroll_col = lnl[1][2]
      #print(lnl)
      return True
    
    return False
      
  def match_parenthesis(self, r_in, c_in):
    p_close = bytes(self.file.rows[r_in].at(c_in))
    pairs = { b"}": b"{" ,b"]": b"[" ,b")": b"("   }
    if p_close not in pairs:
      return
    p_open = pairs[p_close]

    level = 0
    c_start = -1
    matched_position = None

    for r in range(r_in,-1, -1):
      row = self.file.rows[r]
      if row.get_len() == 0:
        continue
      c_start = c_in  if c_start == -1 else row.get_len() - 1
      for c in range(c_start,-1, -1):
        #print(f" r {r}, c {c}")
        ch = row.at(c)
        if ch == p_close:
          #print("Level+1")
          level += 1
        if ch == p_open:
          #print("Level-1")
          level -= 1
          if level == 0:
            matched_position = (r,c)
            #print(f"matched {r},{c}")
            break
      if level == 0:
        break
    return matched_position


  def search_exec(self, direction = 0):
    if direction == 0:
      direction = self.search_info.last_direction
    else:
      self.search_info.last_direction = direction

    row = self.file_row
    col = self.file_col

    query = self.search_info.query_str
    self.search_info.matched_query = None
    #print(f"Query: {row},{col},{direction} q={query}")
    num_found = 0
    if direction == 1:
      r_goal = len(self.file.rows)
    if direction == -1:
      r_goal = -1
    
    self.search_info.aborted = False
    for idx in range(row, r_goal, direction):
      if self.v.poll():
        #keyboard interrupt
        print(f"Aborting {query}")
        self.search_info.aborted = True
        return  
      row = self.file.rows[idx]
      #print(f" searching.. row {idx} col {col} dir {direction}")
      result, self.search_info.matched_query = row.search(col, query, direction)

      # Reset col for the second line and the rest
      if direction == 1:
        col = 0 
      else:
        col = -1

      if result != None:
        num_found += 1
        #print(f"{query} found at {idx},{result}")
        self.jump_to_position(idx, result, direction)
        break

  def jump_to_position(self, r, c, direction = 1, stay_if_possible = True):
    if len(self.file.rows) < 2:
      return
    if r >= len(self.file.rows):
      r = len(self.file.rows)-1
      c = 0
    range_ret = self.file.in_screen(r,c)
    if stay_if_possible and range_ret == 0:
      # in_screen
      self.file_row = r
      self.file_col = c
    else:
      if direction == 1:
        pad = 4 if self.file.h > 10 else 1
        if not stay_if_possible:
          pad = (self.file.h >> 1 ) - 1
      else:
        pad = 6 if self.file.h > 10 else self.file.h - 1
      lnl = self.file.gen_line_num_list(r,c, -pad,0)
      self.scroll_row = lnl[0][1]
      self.scroll_col = lnl[0][2]
      self.file_row = r
      self.file_col = c

    return
    
  def close_file(self):
    if len(self.file_list) == 0:
      self.set_message("The last file cannot be closed.")
      return
    self.process_file_select(0,"")
    del self.file_list[0]

  def process_replace1(self, replace_from):
    
    self.search_info.query_str = replace_from.chars.decode('utf-8')
    self.open_input_line_dialog("Replace",f"{replace_from.decode()} ->",self.process_replace2)
    
  def process_replace2(self, replace_to):
    self.search_info.replace_str = replace_to.chars.decode('utf-8')
    #self.mode = self.MODE_REPLACE
    #print(f"Replace {self.search_info.query_str} {self.search_info.replace_str}")
    self.search_exec(1)
    if self.search_info.matched_query:
      self.open_input_line_dialog("Replace","Replace? y/n (q for quit)", self.process_replace_yn, ["y","n","q"])
    
  def process_revert_yn(self, answer):
    if answer.chars == b"n":
      return
    self.process_open_file(self.file.filename.encode('utf-8'), linenum = self.file_row, colnum = self.file_col, force = True)
    # We don't need the old file
    del self.file_list[0]

  def process_quit_yn(self, answer):
    if answer.chars == b"n":
      return
    self.should_quit = True

  def process_close_yn(self, answer):
    if answer.chars == b"n":
      return
    self.close_file()

  def _open_default_dir(self):
    # Default directory for the open dialog: the current buffer's file
    # directory (emacs-style), falling back to the working directory for a
    # buffer with no filename. Always ends with '/'.
    fn = self.file.filename
    d = _dirname(fn) if fn else "."
    if d == "." or d == "":
      d = os.getcwd()
    if not d.endswith("/"):
      d += "/"
    return d


  def process_replace_yn(self, answer):
    #print(f"Answer: {answer.decode()}")
    if answer.chars == b"q":
      self.recall_pos(self.search_info.saved_pos)
      self.search_info.close()
      return
    if answer.chars == b"y":
      self.file.undo.record(self, 'other')
      row = self.file.rows[self.file_row]
      row.delete_str(self.file_col, len(self.search_info.query_str))
      row.insert_str(self.file_col, self.search_info.replace_str)
      
    for i in range(0, len(self.search_info.replace_str)):
       self.cursor_move(0,1)
    self.search_exec(1)
    if self.search_info.matched_query:
      self.open_input_line_dialog("Replace","Replace? y/n (q for quit)", self.process_replace_yn, ["y","n","q"])
    return

  def process_goto_line(self, num):
    if not num.decode().isdigit():
      self.set_message("Not a number")
      return
    intnum = int(num.decode())-1
    if intnum < 0 or intnum >= len(self.file.rows):
      self.set_message("Out of range")
      return
    pos = self.save_pos()
    self.file.push_pos_history(pos)
    self.jump_to_position(intnum,0, 1)

  def _dir_marked_list(self, base, names):
    # Build (full_paths, display_names) for a file-list dialog. Directories get
    # a trailing '/' marker. The full path is the callback value; the display is
    # just the basename so deep paths don't overflow the dialog width.
    full = []
    disp = []
    for n in names:
      p = base + '/' + n
      if _is_dir(p):
        full.append(p + '/')
        disp.append(n + '/')
      else:
        full.append(p)
        disp.append(n)
    return full, disp

  def process_open_file_select(self, idx, item):
    #print(f' {idx}:{item}')
    # A directory is marked with a trailing '/'. Selecting it opens another
    # file-selection dialog showing its contents instead of "opening" it.
    path = item[:-1] if (len(item) > 1 and item[-1] == '/') else item
    if _is_dir(path) and ls is not None:
      flist = ls.list_file(path)
      if flist and len(flist[1]) > 0:
        full, disp = self._dir_marked_list(flist[0], flist[1])
        self.open_select_dialog(full, min(len(full), 5), flist[0], self.process_open_file_select, dlist=disp)
      else:
        self.set_message("Empty directory: " + path)
      return
    self.process_open_file(item.encode('utf-8'))
    
  def process_open_file(self, name, linenum = None, colnum = None, force = False):
    #print(f"Opening.. file={name.decode()}")
    name = _expand_user(name.decode()).encode('utf-8')

    # A directory isn't a file: browse it in a selection dialog instead.
    if ls is not None and _is_dir(name.decode()):
      self.process_open_file_select(0, name.decode())
      return

    _open_path = name.decode()
    if _open_path:
      self.record_event('open file ' + _open_path)

    if not force and (name.decode() == self.file.filename or self.switch_buf_if_exists(name.decode())):
      # File is already open (the current buffer, or another one just switched
      # to by switch_buf_if_exists). When a jump target was given (symbol jump,
      # md link, remote open) honor it instead of staying at the current/saved
      # position -- otherwise jumping to a symbol that lives in the file you're
      # already editing silently does nothing. linenum None means "no target,
      # keep the existing position" (plain open / buffer switch).
      if linenum is not None:
        self.file_row = linenum
        self.file_col = colnum or 0
      if self.file_row >= len(self.file.rows):
        self.file_row = len(self.file.rows)-1
        self.file_col = 0
      self.render_main_text(True)
      self.jump_to_position(self.file_row, self.file_col, 1, False)
      return

    filename = name.decode()
    filename = None if filename == '' else filename
    
    self.file.saved_pos = self.save_pos()
    self.file_list.insert(0,self.file)
    self.file_row = 0
    self.file_col = 0
    self.scroll_row = 0
    self.scroll_col = 0
    self.file = editor_file(self.v, filename, self.text_height, self.text_width - 1, self.tab_size)

    self.file_row, self.file_col = self.file.open(linenum or 0, colnum or 0)

    if filename is None or not file_exists(filename):
      self.set_message("New file  F1:Help")

    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)
    return


  def process_save_file(self, name):
    fname = name.decode()
    self.filename = fname
    self.file.filename = fname
    self.record_event(f"Saving.. file={name.decode()}")
    total = self.file.save()
    self.file.save_last_filename(self.file_row, self.file_col)
      
    if total == 0:
      self.set_message('File write error')
      # Rollback the new filename to None
      self.filename = None
      self.file.filename = None
    else:
      self.set_message(f"{total} bytes written")
    return
    
  def process_yank_select(self, idx, item):
    #print("process_yank_select")
    self.yankbuf.curbuf = item
    if pdeck_enabled:
      pdeck.clipboard_copy(self.yankbuf.curbuf.encode('utf-8'))
    return

  def set_mark(self):
    self.file.mark_row = self.file_row
    self.file.mark_col = self.file_col
    self.set_message("Mark set")

  def _region_bounds(self):
    # Return ((r1,c1),(r2,c2)) ordered, clamped to the buffer, or None.
    if self.file.mark_row is None:
      return None
    mr = self.file.mark_row
    if mr >= len(self.file.rows):
      mr = len(self.file.rows) - 1
    mc = self.file.mark_col
    mlen = self.file.rows[mr].get_len()
    if mc > mlen:
      mc = mlen
    m = (mr, mc)
    p = (self.file_row, self.file_col)
    return (m, p) if m <= p else (p, m)

  def _region_to_yank(self, text):
    self.yankbuf.reset_buf()
    self.yankbuf.add_str(text)
    self.adding_yank = False

  def copy_region(self):
    b = self._region_bounds()
    if b is None:
      self.set_message("No mark set")
      return
    (r1, c1), (r2, c2) = b
    self._region_to_yank(self.file.extract_region(r1, c1, r2, c2))
    self.file.mark_row = None   # deactivate region after copying
    self.dmod = True
    self.set_message("Region copied")

  def kill_region(self):
    b = self._region_bounds()
    if b is None:
      self.set_message("No mark set")
      return
    (r1, c1), (r2, c2) = b
    self.file.undo.record(self, 'other')
    self._region_to_yank(self.file.extract_region(r1, c1, r2, c2))
    self.file.delete_region(r1, c1, r2, c2)
    self.file.mark_row = None
    self.file_row, self.file_col = r1, c1
    self.jump_to_position(self.file_row, self.file_col, -1)

  def process_file_select(self, idx, item):
    #print("process_file_select")
    self.file_list.insert(0,self.file)
    self.file = self.file_list[idx+1]
    self.v.background_update=self.file.background_update
    self.file.w = self.text_width - 1
    self.file.h = self.text_height
    del self.file_list[idx+1]
    self.recall_pos(self.file.saved_pos)
    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)
    self.file.save_last_filename(self.file_row, self.file_col)
    
    return

  def process_input_line_dialog(self, keys):
    #Ctrl-g to quit
    if keys == b'\x07':
      self.mode = self.MODE_NORMAL
      self.h_diff -= 1
      self.text_height += 1
      self.file.h += 1
      self.sl_info = None
      self.search_info.close()
      return
      
    if self.input_answer_list:
      key = keys.decode('ascii')
      for ch in self.input_answer_list:
        if ch == key:
          #print("Answered {ch}")
          self.h_diff -= 1
          self.file.h += 1
          self.text_height += 1
          self.mode = self.MODE_NORMAL
          line = erow(keys, self.tab_size)
          s_callback = self.sl_info.callback
          self.sl_info = None
          s_callback(line)
      return     
    # Backspace (0x08 from the device keyboard, 0x7f/DEL from PC terminals)
    elif keys in (b'\x08', b'\x7f'):
      if self.sl_info.line.get_len() !=0 and self.sl_info.cur != 0:
        self.sl_info.line.delete_str(self.sl_info.cur -1,1)
        self.sl_info.cur -= 1
    # Left (C-b / arrow): move the caret one char toward the start
    elif keys in km.map['left']:
      if self.sl_info.cur > 0:
        self.sl_info.cur -= 1
    # Right (C-f / arrow): move the caret one char toward the end
    elif keys in km.map['right']:
      if self.sl_info.cur < self.sl_info.line.get_len():
        self.sl_info.cur += 1
    # Home (C-a): jump the caret to the start of the line
    elif keys in km.map['top_line']:
      self.sl_info.cur = 0
    # End (C-e): jump the caret to the end of the line
    elif keys in km.map['bottom_line']:
      self.sl_info.cur = self.sl_info.line.get_len()
    # Forward delete (C-d / Del): remove the char under the caret
    elif keys in km.map['delete']:
      if self.sl_info.cur < self.sl_info.line.get_len():
        self.sl_info.line.delete_str(self.sl_info.cur, 1)
    # Kill to end of line (C-k): cut from the caret onward into the yank buffer
    elif keys in km.map['kill']:
      if self.sl_info.cur < self.sl_info.line.get_len():
        killed = self.sl_info.line.substr(self.sl_info.cur, -1).decode()
        self.yankbuf.reset_buf()
        self.yankbuf.add_str(killed)
        self.sl_info.line.erase_to_the_end(self.sl_info.cur)
    # Yank (C-y): insert the current yank-buffer text at the caret
    elif keys in km.map['yank']:
      if self.yankbuf.curbuf:
        # The dialog is a single line, so stop at the first newline.
        text = self.yankbuf.curbuf
        pos = text.find("\n")
        if pos != -1:
          text = text[:pos]
        if text:
          self.sl_info.line.insert_str(self.sl_info.cur, text)
          self.sl_info.cur += len(text)
    # Enter
    elif keys in (b'\x0d', b'\x0a'): 
      #print("Calling callback")
      self.h_diff -= 1
      self.file.h += 1
      self.text_height += 1
      self.mode = self.MODE_NORMAL
      line = self.sl_info.line
      s_callback = self.sl_info.callback
      self.sl_info = None
      s_callback(line)
    elif keys in (b'\x09') and self.sl_info.callback == self.process_open_file:
      #TAB
      if ls is None:
        return
      try:
        flist = ls.list_file(_expand_user(self.sl_info.line.decode()) + '*')
        if len(flist[1]) > 0:
          if len(flist[1]) > 1:
            full, disp = self._dir_marked_list(flist[0], flist[1])

            self.h_diff -= 1
            self.file.h += 1
            self.text_height += 1
            self.sl_info = None
            self.open_select_dialog(full, 5, flist[0], self.process_open_file_select, dlist=disp)

          else:
            new_line = (flist[0] + '/' + flist[1][0])
            if _is_dir(new_line):
              new_line += '/'
            self.sl_info.line.update_str(bytearray(new_line.encode('utf-8')))
            self.sl_info.cur = len(new_line)
      except Exception as e:
         print(e)
    else:
      if keys[0] >= 0x20:
        self.sl_info.line.insert_str(self.sl_info.cur, keys)
        self.sl_info.cur += 1

    
  def process_select_dialog(self, keys):
    # In a chord menu, typing is reserved for direct second-key dispatch, so
    # incremental search is disabled there; everywhere else, printable keys
    # filter the list (emacs-style).
    is_chord = bool(self._chord_items)

    # Direct chord shortcut: pressing the second key while the chord menu is open
    if is_chord:
      for i, seq in enumerate(self._chord_items):
        if keys == seq[1:2]:
          self.h_diff -= self.sd_info.height
          self.text_height += self.sd_info.height
          self.file.h += self.sd_info.height
          self.mode = self.MODE_NORMAL
          self.sd_info = None
          self.pending_keys = self._chord_items[i]
          self._chord_items = []
          if self._chord_saved_scroll is not None:
            self.scroll_row, self.scroll_col = self._chord_saved_scroll
            self._chord_saved_scroll = None
          return
    #Ctrl-g to quit (also 'q' in chord menus, where 'q' isn't a search char)
    if keys == b'\x07' or (is_chord and keys == b'q'):
      self.mode = self.MODE_NORMAL
      self.h_diff -= self.sd_info.height
      self.text_height += self.sd_info.height
      self.file.h += self.sd_info.height
      self.sd_info = None
      if self._chord_items:
        self._chord_items = []
        if self._chord_saved_scroll is not None:
          self.scroll_row, self.scroll_col = self._chord_saved_scroll
          self._chord_saved_scroll = None
      return
    #Up
    elif keys in (b'\x1b[A', b'\x10'):
      if self.sd_info.scroll + self.sd_info.cur != 0:
        self.sd_info.cur -= 1
      if self.sd_info.cur < 0:
        self.sd_info.cur = 0
        self.sd_info.scroll -= 1
    #Down
    elif keys in  (b'\x1b[B', b'\x0e'):
      if self.sd_info.scroll + self.sd_info.cur < len(self.sd_info.filtered) - 1:
        self.sd_info.cur += 1
      if self.sd_info.cur == self.sd_info.height:
        self.sd_info.cur -= 1
        self.sd_info.scroll += 1
    #Enter
    elif keys in ( b'\x0d', b'\x0a'):
      if not self.sd_info.filtered:
        return  # nothing matches the search; ignore
      orig = self.sd_info.filtered[self.sd_info.cur + self.sd_info.scroll]
      self.h_diff -= self.sd_info.height
      self.text_height += self.sd_info.height
      self.file.h += self.sd_info.height
      prev = self.sd_info
      prev.callback(orig, prev.slist[orig])
      # The callback may open a fresh dialog (e.g. drilling into a directory);
      # only fall back to normal mode if it didn't.
      if self.sd_info is prev:
        self.mode = self.MODE_NORMAL
        self.sd_info = None
      return
    # Incremental search (non-chord dialogs): backspace edits, printables filter.
    elif not is_chord and keys in (b'\x08', b'\x7f'):
      self.sd_info.query = self.sd_info.query[:-1]
      self.sd_info.apply_filter()
    elif not is_chord and keys[0] >= 0x20 and keys[0] != 0x7f:
      try:
        self.sd_info.query += keys.decode('utf-8')
      except Exception:
        pass
      self.sd_info.apply_filter()

  def process_comp_select(self, idx, comp):
    self.file.undo.record(self, 'other')
    pos, sym = self.file.get_symbol(self.file_row, self.file_col)
    row = self.file.rows[self.file_row]
    row.delete_str(pos,len(sym))
    row.insert_str(pos,comp)
    #print(f"Replaced to {comp}")
    #self.cursor_move(0,pos - self.file_col + len(comp))
    self.file_col += pos - self.file_col + len(comp)
    #print(" cursor move to {}".format(pos - self.file_col + len(comp)))
    


  def process_search(self, keys, direction = 1):
    #Ctrl-g to quit
    if keys == b'\x07':
      self.scroll_row, self.scroll_col, self.file_row, self.file_col = self.search_info.saved_pos
      if self.search_info.matched_query != None:
        self.search_info.last_query_str = self.search_info.query_str
      self.mode = self.MODE_NORMAL
      self.search_info.close()
      return

    #Arrow keys (or any escape sequences, some control keys) to quit
    #print(f"hi {keys}")
    if keys[0] == 0x1b \
        or keys in (b'\x01', b'\x02', b'\x05', b'\x06', b'\x0a',b'\x0b', b'\x0e', b'\x10'):
      #print("hi2")
      pos = self.save_pos()
      self.file.push_pos_history(pos)  
      if self.search_info.matched_query != None:
        self.search_info.last_query_str = self.search_info.query_str
        #print(f"Record last query = {self.search_info.last_query_str}")
      self.mode = self.MODE_NORMAL
      self.search_info.close()
      return

    #Ctrl-s (Next)
    if keys == b'\x13':
      if self.search_info.matched_query:
        self.cursor_move(0,1)
      else:
        if len(self.search_info.query_str) == 0 and self.search_info.last_query_str:
          #print("last query: {self.search_info.last_query_str}")
          self.search_info.query_str = self.search_info.last_query_str
        else:
          self.file_row = 0
          self.file_col = 0

      self.search_exec(1)

    #Ctrl-r (Reverse)
    if keys == b'\x12':
      if self.search_info.matched_query:
        self.cursor_move(0,-1)
      else:
        if len(self.search_info.query_str) == 0 and self.search_info.last_query_str:
          #print("last query: {self.search_info.last_query_str}")
          self.search_info.query_str = self.search_info.last_query_str

      self.search_exec(-1)
      
    elif keys in (b'\x08', b'\x7f'):
      self.search_info.query_str = self.search_info.query_str[:-1]
      if (self.search_info.query_str) == 0:
        self.scroll_row, self.scroll_col, self.file_row, self.file_col = self.search_info.saved_pos
        self.mode = self.MODE_NORMAL
        return
      self.file_row = self.search_info.saved_pos[2]
      self.file_col = self.search_info.saved_pos[3]
      self.search_exec()
    elif keys == b'\x19':
      # Yank
      if self.yankbuf.curbuf:
        line_str = self.yankbuf.curbuf
        pos = line_str.find("\n")
        if pos != -1:
          self.search_info.query_str += self.yankbuf.curbuf[:pos]
        else:
          self.search_info.query_str += self.yankbuf.curbuf
        #print(f"curbuf:{self.yankbuf.curbuf}")
        #print(f"sbuf:{self.search_info.query_str}")
        self.search_exec()

    elif keys[0] >= 0x20:

      self.search_info.query_str += keys.decode("utf-8")
      if self.search_info.aborted or self.search_info.matched_query or len(self.search_info.query_str) == 1:
        self.search_exec()

  def set_message(self, message):
    self.status_message=message
    self.status_message_life = 1
    self.dmod = True

  def _fmt_chord_key(self, k):
    if k < 0x20:
      return 'C-' + chr(k + 0x40).lower()
    if k == 0x20:
      return 'SPC'
    return chr(k)

  def _open_chord_dialog(self, prefix):
    self._chord_items = []
    labels = []
    for name, seqs in km.map.items():
      for seq in seqs:
        if len(seq) == 2 and seq[0:1] == prefix:
          key_label = self._fmt_chord_key(seq[1])
          pad = ' ' * max(1, 6 - len(key_label))
          labels.append(key_label + pad + name)
          self._chord_items.append(seq)
          break
    if hasattr(km, 'custom_map'):
      for name, seqs in km.custom_map.items():
        for seq in seqs:
          if len(seq) == 2 and seq[0:1] == prefix:
            key_label = self._fmt_chord_key(seq[1])
            pad = ' ' * max(1, 6 - len(key_label))
            labels.append(key_label + pad + name)
            self._chord_items.append(seq)
            break
    if not labels:
      return
    if not getattr(km, 'chord_dialog', True):
      self.in_ext_mode = True
      return
    prefix_label = 'C-' + chr(prefix[0] + 0x40).lower()
    height = min(len(labels), 6)
    self._chord_saved_scroll = (self.scroll_row, self.scroll_col)
    self.open_select_dialog(labels, height, prefix_label, self.process_chord_select)

  def process_chord_select(self, idx, item):
    if self._chord_saved_scroll is not None:
      self.scroll_row, self.scroll_col = self._chord_saved_scroll
      self._chord_saved_scroll = None
    self.pending_keys = self._chord_items[idx]

  def open_select_dialog(self,slist,height,subject, callback, dlist=None):
    self.mode = self.MODE_SELECT_DIALOG
    self.sd_info = select_dialog_info(slist, height, subject, callback, dlist)
    self.h_diff += height
    self.text_height -= height
    self.file.h -= height
    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)


  def open_input_line_dialog(self,subject,header,callback, answer_list = None, default_str=b''):
    self.mode = self.MODE_INPUT_LINE_DIALOG
    self.sl_info = input_line_info(subject, header, callback, default_str)
    self.h_diff += 1
    self.text_height -= 1
    self.file.h -= 1
    self.render_main_text(True)
    self.input_answer_list = answer_list
    self.jump_to_position(self.file_row, self.file_col, 1, False)

  def switch_buf_if_exists(self,link_filename):
    # Check if the file is already opened
    for i,file in enumerate(self.file_list):
      #print(f'{file.filename} vs {link_filename}')
      if file.filename == link_filename or file.filename == link_filename + '.md':
        self.process_file_select(i,None)
        return True
    return False
  
  def process_key(self):
    if self.pending_keys is not None:
      keys = self.pending_keys
      self.pending_keys = None
    else:
      keys = self.v.read(1)

    # Remote AI edits are serviced here (read() synthesizes REMOTE_EDIT_KEY when
    # edit_pending_list is non-empty), so the buffer is only mutated on this,
    # the editor's own, thread. Mirrors the open_pending_list / C-x C-f path.
    if keys == REMOTE_EDIT_KEY:
      self.drain_remote_edits()
      self.drain_remote_switches()
      return 0

    # Catching window size change
    tw, th = self.v.get_terminal_size()
    if tw != self.text_width or th-self.h_diff != self.text_height:
      print(f'ow,oh,nw,nh = {self.text_width},{self.text_height},{tw},{th}')
      h_diff = self.text_height - self.file.h
      self.text_width = tw
      self.text_height = th-1
      self.file.w = tw
      self.file.h = self.text_height - h_diff
      #self.jump_to_position(self.file_row, self.file_col, 1, False)
      self.update_scroll_for_curmove()
      #print("size changed")


    # When chord_dialog=False, in_ext_mode is set after the prefix key.
    # The next key is matched directly against _chord_items.
    if self.in_ext_mode:
      self.in_ext_mode = False
      for seq in self._chord_items:
        if keys == seq[1:2]:
          self.pending_keys = seq
          self._chord_items = []
          return 0
      self._chord_items = []
      return 0

    # ext keys (C-x, C-c): open command chooser dialog
    # Skip when a dialog is already open so the second key (e.g. C-c in C-x C-c)
    # is handled by the dialog's direct-shortcut logic instead.
    if keys in km.ext_keys and self.mode == self.MODE_NORMAL:
      self._open_chord_dialog(keys)
      return 0

   


    # C-x C-c to exit
    if keys in km.map['quit']:
      msg = "Modified buffer. Quit? y(or Enter)/n" if self.file.modified else "Quit? y(or Enter)/n"
      self.open_input_line_dialog("Quit", msg, self.process_quit_yn, ["y","n","\r"])
      return 0

    if keys == b'\x1b':
      seq = [ keys ]
      seq.append( self.v.read(1) )
      if seq[-1] == b'[' or seq[-1] == b'O':
        # In Rawmode, arrow keys as send as \x1bOA (or BCD) instead of \x1b[A (or BCD). Replace it back to '['
        seq[-1] = b'['
        seq.append( self.v.read(1) )
        if seq[-1] >= b'0' and seq[-1] <= b'9':
          seq.append( self.v.read(1) )
        keys = b''.join(seq)
        #print(keys)
      else:
        keys = b''.join(seq)


    #print(f"--- {keys} ---")
    #self.v.read(1)
    self.dmod = True
    
    # F1 / help: open readme (must be after escape sequence is assembled)
    if keys in km.map.get('help', []):
      self.process_open_file(b'/sd/Documents/pd/pem_readme.md', 0,0)
      return 0
      
    # A remote open (pem_client) is serviced by synthesizing the open key into
    # this handler. If we're in incremental search, MODE_SEARCH would swallow
    # that key as search input and the queue would never drain. Cancel search
    # first (mirrors the escape-key abort path) and fall through to the open.
    if self.mode == self.MODE_SEARCH and open_pending_list and keys in km.map['open']:
      if self.search_info.matched_query != None:
        self.search_info.last_query_str = self.search_info.query_str
      self.mode = self.MODE_NORMAL
      self.search_info.close()

    if self.mode == self.MODE_SEARCH:
      return self.process_search(keys)
      
    if self.mode == self.MODE_SELECT_DIALOG:
      return self.process_select_dialog(keys)

      

    if self.mode == self.MODE_INPUT_LINE_DIALOG:
      self.process_input_line_dialog(keys)
      if self.should_quit:
        return 1
      return 0




    if self.file.input_method == self.IM_JP:
      if keys in km.map['ime_jp_toggle']:
        pass
      elif self.file.im_session and len(self.file.im_session.buffer) == 0 and (keys[0] <= 0x20 or keys[0] == 0x7f):
        # Pass through control chars (incl. 0x7f/DEL from PC terminals) when
        # there's no active pre-edit, so they act as normal editor commands.
        pass
      else:
        last_len = len(self.file.im_session.buffer)
        if last_len == 0:
          self.file.org_row = self.file.rows[self.file_row]
          
        result = self.file.im_session.feed_key(keys)
        if len(result) != 0:
          self.file.rows[self.file_row] = self.file.org_row
          self.file.undo.record(self, 'other')
          self.file.insert_str(self.file_row, self.file_col, result)
          self.file_col += len(result)
          # Don't use jump_to_position here: it snaps the column to 0 on the
          # last row of the file, which left the caret at line start after
          # committing IME text at the end of the document. Just follow the
          # caret with the scroll, like the English insert path does.
          self.update_scroll_for_curmove()

        if last_len > 0 and len(self.file.im_session.buffer) == 0:
          #print('clear')
          self.file.rows[self.file_row] = self.file.org_row
          self.file.org_row = None #self.file.rows[self.file_row]

        if self.file.im_session and len(self.file.im_session.buffer) > 0:
          row = self.file.org_row
          curcol = self.file_col
          temp_row = erow( row.substr(0,curcol) +  el.set_font_color(4).encode('utf-8') +  self.file.im_session.d_buffer.encode('utf-8') + el.set_font_color(0).encode('utf-8') + row.substr(curcol, -1), self.file.tab_size, self.file.w)
          self.file.rows[self.file_row] = temp_row
          self.update_scroll_for_curmove(self.file.im_session.col)
          
        return 0
      
    # C-x C-s to save file
    if keys in km.map['save']:
      if self.file.filename == None:
        self.open_input_line_dialog("Save file","Filename",self.process_save_file)
      else:
        while True:
          total = self.file.save()
          self.record_event(f"Saving.. file={self.file.filename}")
          self.file.save_last_filename(self.file_row, self.file_col)
          if total != 0:
            break
          print("File write error. Retrying..")
          time.sleep_ms(200)
        
        if total == 0:
          self.set_message('File write error')
        else:
          self.set_message(f"{total} bytes written")
    # C-x C-v to revert change
    if keys in km.map['revert']:
      self.open_input_line_dialog("Revert","Revert current file? y/n", self.process_revert_yn, ["y","n"])
    # C-x C-f to open file
    if keys in km.map['open']:
      if len(open_pending_list) > 0:
        filename, linenum, colnum = open_pending_list.pop()
        self.process_open_file(filename.encode('utf-8'), linenum-1, colnum-1)

      else:
        d = self._open_default_dir()
        # Keep the editable input on the full path (default_str) but trim the
        # title's directory tail so the "  ** Open file in <dir> ** " line fits.
        title_dir = _trim_path(d, self.text_width - 22)
        self.open_input_line_dialog("Open file in "+title_dir, "Filename",
                                    self.process_open_file,
                                    default_str=d.encode('utf-8'))

    # C-x k to close file
    if keys in km.map['close']:
      if len(self.file_list) == 0:
        self.set_message("The last buffer cannot be closed.")
      else:
        self.open_input_line_dialog("Kill buffer","Kill buffer? y(or Enter)/n", self.process_close_yn, ["y","\r", "n"])

    # C-x b to switch buffer
    if keys in km.map['switch']:
      filenames = []
      for file in self.file_list:
        if file.filename == None:
          filenames.append("** New file **")
        else:
          filenames.append(file.filename)
      if len(filenames) == 0:
        self.set_message("No files to switch")
      else:
        self.file.saved_pos = self.save_pos()
        self.open_select_dialog(filenames, 5, "File list", self.process_file_select)


    # Reset yankbuf if the operation is not kill
    if keys not in km.map['kill'] and keys not in km.map['delete']:
      self.adding_yank = False

    #Ctrl-s (Search)
    if keys in km.map['search']:
      pos = self.save_pos()
      self.file.push_pos_history(pos)
      self.mode = self.MODE_SEARCH
      self.search_info.start_search( (self.scroll_row, self.scroll_col, self.file_row, self.file_col),1)

    #Ctrl-r (Reverse Search)
    elif keys in km.map['rev_search']:
      pos = self.save_pos()
      self.file.push_pos_history(pos)
      self.mode = self.MODE_SEARCH
      self.search_info.start_search( (self.scroll_row, self.scroll_col, self.file_row, self.file_col),-1 )

    # Escape + % (Replace)
    elif keys in km.map['replace']:
      pos = self.save_pos()
      self.search_info.start_search(pos,1,True)
      self.open_input_line_dialog("Replace","Replace from",self.process_replace1)

    # Escape + " " (Manual marking)
    elif keys in km.map['mark']:
      pos = self.save_pos()
      self.file.push_pos_history(pos)
      self.set_message("Position marked.")
    # C-g : cancel / clear an active region mark
    elif keys == b'\x07':
      if self.file.mark_row is not None:
        self.file.mark_row = None
        self.dmod = True
        self.set_message("Mark cleared")
    # C-Space : set region mark
    elif keys in km.map['set_mark']:
      self.set_mark()
    # C-w : cut region to kill ring
    elif keys in km.map['kill_region']:
      self.kill_region()
    # M-w : copy region to kill ring
    elif keys in km.map['copy_region']:
      self.copy_region()
    # Escape + ' (Position hisoty walk forward)
    elif keys in km.map['walk_forward']:
      pos = self.file.walk_pos_history(1)
      if pos:
        self.recall_pos(pos)
      else:
        self.set_message("No more history")
   
    # Escape + ; (Position hisoty walk backward)
    elif keys in km.map['walk_back']:
      pos = self.file.walk_pos_history(-1)
      if pos:
        self.recall_pos(pos)
      else:
        self.set_message("No more history")

    # Escape + g : Go to input line #
    elif keys in km.map['goto_line']:
      self.open_input_line_dialog("Go to line #","Line #",self.process_goto_line)

    # Escape + . : Go to function definition in Python mode, try to go link in md mode
    elif keys in km.map['ref_def'] or keys in km.map['ref_sym']:
      pos, sym = self.file.get_symbol(self.file_row, self.file_col)
      #print(f'sym {sym}')
      if sym and self.file.mode == 'md':
        print(f'sym in md mode {sym}')
        if sym.startswith('/'):
          dirname = ''
        else:
          dirname = _dirname(self.file.filename) + "/"
        try:
          link_filename = dirname + sym
          #print(link_filename)
          st = os.stat(link_filename)
          if st[0]&0x4000:
            raise Exception('directory')
    
          res = self.switch_buf_if_exists(link_filename)
          if not res:
            self.process_open_file(link_filename.encode('utf-8'))
        except Exception as e:
          try:
            link_filename += ".md"
            #print(link_filename)
            st = os.stat(link_filename)
            res = self.switch_buf_if_exists(link_filename)
            if not res:
              self.process_open_file(link_filename.encode('utf-8'))
          except Exception as e:
            self.process_open_file(link_filename.encode('utf-8'))
            #self.set_message('Link not found')
            print(e)
        
      elif sym and self.file.mode in ('py', 'c'):
        pos = self.save_pos()
        self.file.push_pos_history(pos)
        self.mode = self.MODE_SEARCH
        self.search_info.start_search( (self.scroll_row, self.scroll_col, self.file_row, self.file_col),1)
        self.search_info.query_str = sym
        if keys in km.map['ref_def']:
          # "def " prefix is Python-only; for C just jump to the symbol from top.
          if self.file.mode == 'py':
            self.search_info.query_str = "def " + sym
          self.file_row = 0
          self.file_col = 0

        self.search_exec(1)



    # Escape + < : Go to the top
    elif keys in km.map['top']:
      self.jump_to_position(0,0,1)

    # Escape + > : Go to the end
    elif keys in km.map['bottom']:
      r = len(self.file.rows) -1
      c = self.file.rows[-1].get_len()
      self.jump_to_position(r,c,-1)

    # Escape + y : Select kill ring
    elif keys in km.map['recover_yank']:
      self.yankbuf.reset_buf()
      if len(self.yankbuf.bufs) == 0:
        self.set_message("No yank list")
      else:
        self.open_select_dialog(self.yankbuf.bufs,5, "Yank list", self.process_yank_select)

    #Ctrl-a (Move to the start of the line)
    elif keys in km.map['top_line']:
      # Stop at indent first
      if self.file.mode in ("py", "c"):
        pos = self.file.get_indent(self.file_row)
        if pos != -1 and pos < self.file_col:
          self.file_col = pos
        else:
          self.file_col = 0

      else:
        self.dmod = False
        self.file_col = 0

      self.update_scroll_for_curmove()

    #Ctrl-e (Move to the end of the line)
    elif keys in km.map['bottom_line']:
      self.dmod = False
      self.file_col = self.file.rows[self.file_row].get_len()
      self.update_scroll_for_curmove()
    
    #Ctrl-k (Erase to the end of the line)
    elif keys in km.map['kill']:
      if not self.adding_yank:
        self.yankbuf.reset_buf()
      self.file.undo.record(self, 'other')
      self.file.erase_to_the_end(self.file_row, self.file_col, self.yankbuf)
      self.adding_yank = True

    #Ctrl-y (Yank)
    elif keys in km.map['yank']:
      self.file.undo.record(self, 'other')
      self.file_row, self.file_col = self.file.yank(self.file_row, self.file_col, self.yankbuf)
      self.jump_to_position(self.file_row, self.file_col, -1)

    # Undo / Redo
    elif keys in km.map['undo']:
      if not self.file.undo.undo_one(self):
        self.set_message("Nothing to undo")
    elif keys in km.map['redo']:
      if not self.file.undo.redo_one(self):
        self.set_message("Nothing to redo")

    elif keys in km.map['redraw']:
      #print("center")
      self.jump_to_position(self.file_row, self.file_col, 1, False)
      self.dmod = True

    #Up
    elif keys in km.map['up']:
      self.dmod = False
      self.cursor_move(-1,0)
    #Down
    elif keys in km.map['down']:
      self.dmod = False
      self.cursor_move(1,0)
    #Left
    elif keys in km.map['left']:
      self.dmod = False
      self.cursor_move(0,-1)
    #Right 
    elif keys in km.map['right']:
      self.dmod = False
      self.cursor_move(0,1)

    # Input method toggle
    elif keys in km.map['ime_jp_toggle']:
      if jp_input is None:
        self.set_message("Japanese input unavailable")
      elif self.file.input_method == self.IM_EN:
        if auto_connect is not None:
          auto_connect.check(self.v, silent = True)
        self.file.input_method = self.IM_JP
        if not self.jpfont_loaded:
          self.load_jpfont()
        self.file.im_session = jp_input.input_session()
        #self.file.org_row = self.file.rows[self.file_row]
        self.file.org_row = None
      else:
        self.file.input_method = self.IM_EN
        self.file.im_session = None
        if self.file.org_row:
          self.file.rows[self.file_row] = self.file.org_row
        self.file.org_row = None

    # Delete
    elif keys in km.map['delete']:
      if not self.adding_yank:
        self.yankbuf.reset_buf()
      self.adding_yank = True
      self.file.undo.record(self, 'delete')
      self.file_row, self.file_col = self.file.delete_one_char_del(self.file_row, self.file_col, self.yankbuf)
      self.update_scroll_for_curmove()

    # Backspace
    elif keys in km.map['bs']:
      self.file.undo.record(self, 'delete')
      self.file_row, self.file_col = self.file.delete_one_char_bs(self.file_row, self.file_col)
      self.update_scroll_for_curmove()

    # Enter
    elif keys in km.map['enter']:
      self.file.undo.record(self, 'insert', 'nl')
      self.file_row, self.file_col = self.file.insert_return(self.file_row, self.file_col)
      self.update_scroll_for_curmove()
    #PageDown
    elif keys in km.map['pagedown']:
      lnl = self.file.gen_line_num_list(self.file_row, self.line_num_list[self.d_row][2],0, self.file.h)
      if self.wished_d_col != -1:
        d_col = self.wished_d_col
      else:
        d_col = self.d_col
      next_file_row = lnl[-1][1]
      next_file_col = lnl[-1][2] + d_col
      if next_file_col > self.file.rows[lnl[-1][1]].get_len():
        next_file_col = self.file.rows[lnl[-1][1]].get_len()
        self.wished_d_col = self.d_col
      self.jump_to_position(next_file_row, next_file_col)
      
      #for i in range(self.file.h):
      #  self.cursor_move(1,0)
      #  self.render_main_text(True) #dry_run
      #  self.update_d_cursor()
    #PageUp
    elif keys in km.map['pageup']:
      lnl = self.file.gen_line_num_list(self.file_row, self.line_num_list[self.d_row][2],-self.file.h,0)
      if self.wished_d_col != -1:
        d_col = self.wished_d_col
      else:
        d_col = self.d_col
      next_file_row = lnl[0][1]
      next_file_col = lnl[0][2] + d_col
      if next_file_col > self.file.rows[lnl[0][1]].get_len():
        next_file_col = self.file.rows[lnl[0][1]].get_len()
        self.wished_d_col = self.d_col
      self.jump_to_position(next_file_row, next_file_col)
      #for i in range(self.file.h):
      #  self.cursor_move(-1,0)
      #  self.render_main_text(True) #dry_run
      #  self.update_d_cursor()
    #tab
    elif keys == b'\x09':
      tab_process = True
      if self.file.mode in ("py", "c"):
        indent = self.file.get_indent(self.file_row)
        if indent >= 2 and self.file_col > indent:
          tab_process = False
          pos, sym = self.file.get_symbol(self.file_row, self.file_col)
          if sym:
            complist = self.file.get_comp_list(sym)
            if not complist:
              return
            if len(complist) == 0:
              return
            if len(complist) == 1:
              self.process_comp_select(0,complist[0])
              return
              
            list_size = 5 if len(complist) >=5 else len(complist)
            self.open_select_dialog(complist,list_size, "Compeletion", self.process_comp_select)
            #print(complist)
            
          else:
            self.set_message("List not found")
      
      if tab_process:
        num_space = self.tab_size - self.file.rows[self.file_row].expand(0,self.file_col) % self.tab_size
        if num_space == 0:
          num_space = self.tab_size
        self.file.undo.record(self, 'other')
        self.file.insert_str(self.file_row, self.file_col, " "*num_space)
        self.cursor_move(0,num_space)
    
    # Letters, etc..  
    else:
      
      # Custom command
      for command in km.custom_map:
        if keys in km.custom_map[command]:
          try:
            eval(f"km.{command}(e)",{ "km" : km, "e" : self })
          except Exception as e:
            print(e)
          return 0

      if int(keys[0]) >= 0x20:
        self.file.undo.record(self, 'insert', _edit_class(keys))
        self.file.insert_str(self.file_row, self.file_col, keys)
        mresult = self.match_parenthesis(self.file_row,self.file_col)
        if mresult:
          org_pos = self.save_pos()
          self.jump_to_position(mresult[0], mresult[1])
          self.refresh_screen()
          for i in range(16):
            if self.v.poll():
              break
            time.sleep_ms(50)
          self.recall_pos(org_pos)

        self.cursor_move(0,1)
        self.update_scroll_for_curmove()

    #print(f"file_row {self.file_row}")
    #if keys == b"\x1b"
    return 0

  def save_pos(self):
    return (self.scroll_row, self.scroll_col, self.file_row, self.file_col)
  def recall_pos(self, pos):
    # A buffer that was never switched away from (e.g. the buffer revealed by
    # closing another with C-x k) has saved_pos == None. Fall back to the top
    # of the file instead of crashing while unpacking None.
    if pos is None:
      pos = (0, 0, 0, 0)
    self.scroll_row, self.scroll_col, self.file_row, self.file_col = pos

def _edit_class(keys):
  # Classify a typed key for word/line undo granularity.
  c = keys[0]
  if c == 0x0d or c == 0x0a:
    return 'nl'
  if (48 <= c <= 57) or (65 <= c <= 90) or (97 <= c <= 122) or c == 95 or c >= 0x80:
    return 'word'
  return 'sep'

class undo_history:
  # Snapshot-based undo/redo with word/line coalescing. erow.chars is
  # copy-on-write (every edit reassigns it, never mutates in place), so a
  # snapshot can store line references cheaply and unchanged lines are shared
  # across snapshots.
  def __init__(self, limit=40):
    self.limit = limit
    self.undo = []
    self.redo = []
    self.last_kind = None
    self.last_class = None
    self.exp_row = -1
    self.exp_col = -1

  def _snap(self, ed):
    return ([r.chars for r in ed.file.rows],
            ed.file_row, ed.file_col, ed.scroll_row, ed.scroll_col)

  def _restore(self, ed, snap):
    rows, fr, fc, sr, sc = snap
    newrows = []
    for cb in rows:
      row = erow(bytearray(cb), ed.file.tab_size, ed.file.w)
      row.hl_mode = ed.file.mode
      newrows.append(row)
    ed.file.rows = newrows
    ed.file.num_updated = 0
    ed.file_row, ed.file_col = fr, fc
    ed.scroll_row, ed.scroll_col = sr, sc
    ed.dmod = True

  def record(self, ed, kind, cclass=None):
    # Call BEFORE a mutation. Start a new undo group (push a snapshot of the
    # pre-edit state) or coalesce with the current one for word/line granularity.
    brk = (not self.undo) or kind != self.last_kind or kind == 'other'
    if not brk:
      if kind == 'insert':
        if cclass == 'nl' or self.last_class == 'nl':
          brk = True
        elif self.last_class == 'sep' and cclass == 'word':
          brk = True   # start of a new word
        elif ed.file_row != self.exp_row or ed.file_col != self.exp_col:
          brk = True   # caret jumped -> discontinuous edit
      elif kind == 'delete':
        if ed.file_row != self.exp_row:
          brk = True
    if brk:
      self.undo.append(self._snap(ed))
      if len(self.undo) > self.limit:
        self.undo.pop(0)
      self.redo = []
    self.last_kind = kind
    self.last_class = cclass
    # Predict the caret after this edit so the next one can test contiguity.
    if kind == 'insert' and cclass != 'nl':
      self.exp_row, self.exp_col = ed.file_row, ed.file_col + 1
    elif kind == 'delete':
      self.exp_row, self.exp_col = ed.file_row, ed.file_col
    else:
      self.exp_row, self.exp_col = -1, -1

  def _reset_group(self):
    self.last_kind = None
    self.last_class = None
    self.exp_row = -1
    self.exp_col = -1

  def undo_one(self, ed):
    if not self.undo:
      return False
    self.redo.append(self._snap(ed))
    self._restore(ed, self.undo.pop())
    self._reset_group()
    return True

  def redo_one(self, ed):
    if not self.redo:
      return False
    self.undo.append(self._snap(ed))
    self._restore(ed, self.redo.pop())
    self._reset_group()
    return True

class select_dialog_info:
  def __init__(self, slist, height, subject, callback, dlist=None):
    self.slist = slist
    # What to show for each entry. Defaults to slist; pass dlist to show a short
    # label (e.g. basename) while the callback still receives the full slist[i].
    self.dlist = dlist if dlist is not None else slist
    self.subject = subject
    self.height = height
    self.callback = callback
    self.cur = 0
    self.scroll = 0
    # Incremental search (emacs-style): typing filters the list. `query` is the
    # typed text; `filtered` holds the indices into slist that currently match.
    self.query = ''
    self.filtered = list(range(len(slist)))

  def apply_filter(self):
    q = self.query.lower()
    if not q:
      self.filtered = list(range(len(self.slist)))
    else:
      out = []
      for i, item in enumerate(self.slist):
        # Match the basename only -- ignore any directory part of the path.
        # _basename() also handles directory entries' trailing '/' marker.
        if q in _basename(item).lower():
          out.append(i)
      self.filtered = out
    self.cur = 0
    self.scroll = 0

class input_line_info:
  def __init__(self, subject, header, callback, default_str=b''):
    self.subject = subject
    self.callback = callback
    self.header = header
    self.line = erow(default_str, 2) # dummy tab_size
    self.cur = self.line.get_len()   # start the caret after any prefilled text

class search_info:
  def __init__(self):
    self.saved_pos = []
    self.last_query_str = None
    self.query_str = None
    self.replace_str = None
    self.p_query_str = None
    self.p_replace_str = None
    self.matched_query = None
    self.index = 0
    self.last_direction = 1
    self.isreplace = False
    self.aborted = False

  def start_search(self,pos, direction, replace = False):
    self.saved_pos = pos
    self.query_str = ""
    self.replace_str = None
    self.matched_query = None
    self.index = 0
    self.last_direction = direction
    self.isreplace = replace
  def close(self):
    self.start_search(None, 1)
    
class editor_file:
  def __init__(self, v, filename,h,w, tab_size):
    self.v = v
    self.input_method = IM_EN
    self.im_session = None
    self.tab_size = tab_size
    self.rows = []
    self.pos_history = []
    self.phistory_cur = 0
    self.saved_pos = None
    self.undo = undo_history(40)   # per-buffer undo/redo
    self.mark_row = None           # region mark (set by C-Space), per-buffer
    self.mark_col = 0
    self.h = h
    self.w = w
    self.modified = False
    self.filename = filename
    self.v.background_update=self.background_update

  def open(self, linenum = 0, colnum = 0):
    
    filename = self.filename
    
    self.mode = "txt"
    self.num_updated = 0
    self.period_regex = {}
    self.period_regex['py'] = re.compile("([A-Za-z0-9_]+)")
    self.period_regex['c'] = re.compile("([A-Za-z0-9_]+)")
    self.period_regex['md'] = re.compile("([A-Za-z0-9_\ \/\.']+)")
    fn = self.filename
    if fn != None:
      if fn.endswith(".md"):
        self.mode = "md"
      elif fn.endswith(".py"):
        self.mode = "py"
      elif fn.endswith(".c") or fn.endswith(".h") or fn.endswith(".cpp") \
           or fn.endswith(".cc") or fn.endswith(".hpp"):
        self.mode = "c"
    if file_exists(filename):
      if pdeck_enabled:
        pdeck.shared_filelist(filename)
      try:
        with open(filename, "r") as f:
          for line in f:
            if line[-1] in ('\n', '\r'):
              if len(line) > 1 and line[-2] in ('\r','\n'):
                line = line[:-2]
              else:
                line = line[:-1]
            row = erow(line.encode('utf-8'), self.tab_size, self.w)
            row.hl_mode = self.mode
            self.rows.append(row)
        #self.jump_to_position(linenum, colnum, 1, False)
        #self.save_last_filename(linenum, colnum)
      except:
        row = erow(b"", self.tab_size, self.w)
        row.hl_mode = self.mode
        self.rows.append(row)
    else:
      row = erow(b"", self.tab_size, self.w)
      row.hl_mode = self.mode
      self.rows.append(row)
    
    return linenum, colnum      

  def background_update(self):
    if self.num_updated < len(self.rows):
      for i in range(self.num_updated, self.num_updated+3):
        if i < len(self.rows):
          self.rows[i].w = self.w
          self.rows[i].update_hl_bytes()
      self.num_updated += 3
      #print('update')
      return True
    return False

  def push_pos_history(self, pos):
    # If current entry is same, do nothing
    if 0 <= self.phistory_cur < len(self.pos_history):
      if pos == self.pos_history[self.phistory_cur]:
        return

    # Discard forward history when creating a new branch
    if self.phistory_cur < len(self.pos_history) - 1:
      del self.pos_history[self.phistory_cur + 1:]

    self.pos_history.append(pos)
    self.phistory_cur = len(self.pos_history) - 1

    # Limit size
    if len(self.pos_history) > 30:
      overflow = len(self.pos_history) - 30
      del self.pos_history[:overflow]
      self.phistory_cur -= overflow
      if self.phistory_cur < 0:
        self.phistory_cur = 0


  def walk_pos_history(self,step):
    if self.phistory_cur+step < 0 or self.phistory_cur+step >= len(self.pos_history):
      return None
    self.phistory_cur += step
    return self.pos_history[self.phistory_cur]


  def save_last_filename(self, row, col):
    resume_last_file = True
    if hasattr(km,'resume_last_file'):
      resume_last_file=km.resume_last_file
    if resume_last_file:
      if self.filename == None:
        return
      try:
        with open(PEM_FILELIST, "wb") as f:
          payload = "{},{},{}\n".format(self.filename, row, col)
          f.write(payload.encode('utf-8'))
      except Exception as e:
        print(e)

  def save(self):
    if self.filename == None:
      return
    total_bytes = 0
    try:
      with open(self.filename, "wb") as f:
        for row in self.rows:
          f.write(row.chars)
          f.write(b"\n")
          total_bytes += len(row.chars) + 1
      self.modified = False
      if hasattr(os, 'sync'):  # POSIX/MicroPython only; absent on Windows
        os.sync()
    except:
      return 0
    return total_bytes

  def get_indent(self, r):
    row = self.rows[r]
    rlen = self.rows[r].get_len()
    if rlen == 0:
      return 0
    first_nonspace = -1
    if row.at(0) == b' ':
      for c in range(0, rlen):
        if row.at(c) != b' ':
          first_nonspace = c
          break
    return first_nonspace


  def gen_line_num_list(self,filerow, filecol, rel_start,rel_end):
    lnl = [ [0, filerow, filecol] ]
    for _ in range(rel_end):    
      newln = self.get_next_line_num_list(lnl)
      if newln:
        lnl.append(newln)
    if rel_start < 0:
      for _ in range(rel_start,0):
        newln = self.get_prev_line_num_list(lnl)
        if newln:
          lnl.insert(0, newln)
    #print(lnl)
    return lnl

  def _wrap_prev_start(self, row, col):
    # Char position where the wrapped segment ending at `col` begins. Boundaries
    # are walked forward (same as get_next_line_num_list) because forward
    # wrapping is the source of truth: a 2-column wide char that would straddle
    # the right edge is pushed to the next line, making a segment only w-1 wide.
    # Stepping backward by a fixed w mis-handles that case.
    cur = 0
    nxt = row.expanded_to_pos(cur, self.w)
    while nxt < col and nxt > cur:
      cur = nxt
      nxt = row.expanded_to_pos(cur, self.w)
    return cur

  def _wrap_last_start(self, row):
    # Char position where the final wrapped segment of `row` begins.
    rlen = row.get_len()
    cur = 0
    nxt = row.expanded_to_pos(cur, self.w)
    while nxt < rlen and nxt > cur:
      cur = nxt
      nxt = row.expanded_to_pos(cur, self.w)
    return cur

  def get_prev_line_num_list(self, lnl):
    top_ln = lnl[0]
    toprow = self.rows[top_ln[1]]
    if top_ln[2] > 0:
      next_stop = self._wrap_prev_start(toprow, top_ln[2])
      return ( top_ln[0] - 1, top_ln[1], next_stop)
    else:
      if top_ln[1] == 0:
        return None
      file_row = top_ln[1] - 1
      nextrow = self.rows[file_row]
      file_col = self._wrap_last_start(nextrow)
      return (top_ln[0] - 1, file_row, file_col)

  def get_next_line_num_list(self, lnl):
    last_ln = lnl[-1]
    lastrow = self.rows[last_ln[1]]
    #if lastrow.expand(last_ln[2],lastrow.get_len()) > self.w:
    maybe_next_stop = lastrow.expanded_to_pos(last_ln[2], self.w)
    if maybe_next_stop < lastrow.get_len():
      next_stop = maybe_next_stop
      return (last_ln[0] + 1, last_ln[1], next_stop)
    else:
      file_row = last_ln[1] + 1
      if file_row >= len(self.rows):
        return None
      return (last_ln[0] + 1, file_row, 0)

  def utf8_trim(self, str, col):
    ct = 0
    i = 0
    for ch in str:
      ct += pdeck.get_utf8_width(ch)
      #if ord(ch) >= 0x100:
      #  ct += 2
      #else:
      #  ct += 1
      
      i += 1
      if ct >= col:
        return str[:i]
    return str


  def _selection_region(self, currow, curcol):
    # Ordered, clamped region (mark .. point), or None if no mark is set.
    if self.mark_row is None:
      return None
    mr = self.mark_row
    if mr >= len(self.rows):
      mr = len(self.rows) - 1
    mc = self.mark_col
    mlen = self.rows[mr].get_len()
    if mc > mlen:
      mc = mlen
    m = (mr, mc)
    p = (currow, curcol)
    return (m, p) if m <= p else (p, m)

  def _seg_sel(self, frow, seg_start, seg_end, region):
    # Selected char range [a,b) within a wrapped segment, or None.
    if region is None:
      return None
    (r1, c1), (r2, c2) = region
    if frow < r1 or frow > r2:
      return None
    ls = c1 if frow == r1 else 0
    le = c2 if frow == r2 else seg_end   # interior lines select to segment end
    a = ls if ls > seg_start else seg_start
    b = le if le < seg_end else seg_end
    if a >= b:
      return None
    return (a, b)

  def _render_sel_segment(self, row, seg_start, seg_end, sel):
    # Build the segment bytes with the selected range in reverse video.
    a, b = sel
    inv = el.set_font_color(7).encode('utf-8')   # reverse video
    rst = el.set_font_color(0).encode('utf-8')
    if not row.tab_detected:
      out = bytearray(row.substr(seg_start, a))
      out += inv
      out += row.substr(a, b)
      out += rst
      out += row.substr(b, seg_end)
      return out
    # tab line: slice the tab-expanded chars by display position
    d0 = row.bdmap[row.cbmap[seg_start]]
    de = d0 + self.w
    da = row.cpos_to_dpos(a)
    db = row.cpos_to_dpos(b)
    da = d0 if da < d0 else (de if da > de else da)
    db = da if db < da else (de if db > de else db)
    ex = row.ex_chars
    out = bytearray(ex[d0:da])
    out += inv
    out += ex[da:db]
    out += rst
    out += ex[db:de]
    return out

  def file_refresh_screen(self,filerow, filecol, currow, curcol, dry_run = False):

    bm.add_bench('refresh_start')

    out_buf = bytearray()
    line_count = 0

    lnl = self.gen_line_num_list(filerow, filecol,0, self.h - 1)
    region = self._selection_region(currow, curcol)
    bm.add_bench('num_list')

    #print(lnl)
    #print(len(lnl))

    for ln in lnl:
      if not dry_run:
        row = self.rows[ln[1]]
        if row.w != self.w:
          row.w = self.w
          row.update_hl_bytes()
          self.num_updated = 0
        #print(f"exchars: {row.get_ex_chars()}")

        # Trim the row to one display line.
        # ln[2] is the starting column
        # expos will be the end of the column
        expos, d_pos = row.expanded_to_pos_with_d(ln[2], self.w)

        sel = self._seg_sel(ln[1], ln[2], expos, region)
        if sel is not None:
          # Region is active over this segment: reverse-video the selection
          # (syntax highlighting is skipped on selected segments).
          out_line = self._render_sel_segment(row, ln[2], expos, sel)
        else:
          if row.tab_detected:
            # Use cached expanded characters and slice them
            # We need to map ln[2] (file col) and expos (file col end) to expanded col positions
            # or simply use the fact that d_pos is display position.
            d_start = row.bdmap[row.cbmap[ln[2]]]
            out_line = row.ex_chars[d_start : d_start + self.w]
          else:
            out_line = row.substr(ln[2], expos)

          if self.mode in ('md', 'py', 'c'):
            #if not row.tab_detected and expos >= len(row.cbmap):
            if self.input_method != IM_JP and ln[1] != filerow:
              if not ln[2] in row.hl_bytes:
                # Highlight the visible (tab-expanded) segment that out_line
                # already holds -- not bytes(row.chars), which kept literal tabs
                # and highlighted the whole row instead of this wrapped segment.
                row.hl_bytes[ln[2]] = _hl_line(out_line, self.mode)
              out_line = row.hl_bytes[ln[2]]
            else:
              out_line = _hl_line(out_line, self.mode)
        out_buf.extend(out_line)
        out_buf.extend(el.erase_to_end_of_current_line().encode('utf-8'))
        #print(f"outbuf: {out_line}")
        #print(f"outbuf: {out_line.decode('utf-8')}")
        
        #out_buf.extend(el.erase_to_end_of_current_line().encode('utf-8'))
        if ln[0] != self.h-1:
          line_count += 1
          out_buf.extend(b"\r\n")
    #Add lines if it's not enough
    while line_count < self.h:
      line_count += 1
      out_buf.extend(el.erase_to_end_of_current_line().encode('utf-8') + b"\r\n")
      #out_buf.extend(b"\r\n")
      
    if not dry_run:
      self.v.print(el.cursor_mode(False)) #hide cursor
      self.v.print(el.home())
      #print(out_buf.decode('utf-8'))
      #self.v.print(out_buf.decode('utf-8'))
      self.v.print(out_buf)
    #print(f"line_count {line_count}")
    self.line_num_list = lnl
    bm.add_bench('print')
    return lnl

  def in_screen(self, row, col):
    lnl = self.line_num_list
    #print(f"in_screen {row},{col}")
    #print(lnl)
    if row < lnl[0][1]:
      return -1
    if row == lnl[0][1] and col < lnl[0][2]:
      return -1
    w = lnl[-1][2] + self.w
    if row == lnl[-1][1]:
      lnl_next = self.gen_line_num_list(lnl[-1][1], lnl[-1][2], 0,1)
      if len(lnl_next) == 2 and lnl_next[1][1] == row:
        w = lnl_next[1][2]

    if row > lnl[-1][1] or (row == lnl[-1][1] and col >= w):
      #if file is less  then one screen
      if lnl[-1][0] < self.h - 1:
        pad = self.h - lnl[-1][0]
        if row < lnl[-1][1]+pad:
          return 0
      return 1
    return 0

  def scr_to_filepos(self, h, w, scr_y, scr_x):
    # Convert screen position to file position
    # This might return filecol more than the its length

    file_row = -1
    file_col = -1
    lnl = self.line_num_list

    # Take care if scr_y is out of screen
    # (Only one more line)
    if scr_y == -1:
      lnl_extra = self.gen_line_num_list(lnl[0][1], lnl[0][2], -1,0)
      for ln in lnl_extra:
        if ln[0] == -1:
          #print(f"lnl_extra {ln}")
          return (ln[1], self.rows[ln[1]].expanded_to_pos(ln[2], scr_x))
      return None # if there is no item for the line_num, return None

    if scr_y == h:
      lnl_extra = self.gen_line_num_list(lnl[h-1][1], lnl[h-1][2], 0,1)
      for ln in lnl_extra:
        if ln[0] == 1:
          return (ln[1], self.rows[ln[1]].expanded_to_pos(ln[2], scr_x))
      return None # if there is no item for the line_num, return None


    # scr_y is within the display
    for lineinfo in lnl:
      if lineinfo[0] == scr_y:
        file_row = lineinfo[1]
        file_col = self.rows[file_row].expanded_to_pos(lineinfo[2], scr_x)
        break

    if file_row == -1:
      return None    
    return (file_row, file_col)

  def insert_str(self, r, c, str):
    self.modified = True
    self.rows[r].insert_str(c,str)

  def insert_return(self, r, c, auto_indent = True):
    self.modified = True
    newrow = erow(self.rows[r].substr(c,-1), self.tab_size, self.w)
    newrow.hl_mode = self.mode

    # Auto indent for Python
    ind = 0
    if auto_indent and self.mode in ("py", "c") and c != 0:
      ind = self.get_indent(r)
      ind = 0 if ind == -1 else ind
      if self.rows[r].at(c-1) == b":":
        ind += 2
      #print(f"Auto indent ind = {ind}")
      if ind != -1:
        newrow.insert_str(0," "*ind)

    self.rows[r].update_str(self.rows[r].substr(0,c))
    self.rows.insert(r+1, newrow)
    return (r+1, ind)

  def get_comp_list(self, sym):
    row = 0
    col = 0
    query = sym
    comp_list = []
    #print(f"CompQuery: {row},{col} q={query}")
    r_goal = len(self.rows)

    for idx in range(row, r_goal):
      if self.v.poll():
        #keyboard interrupt
        return None
      row = self.rows[idx]
      #print(f" searching.. row {idx} col {col} dir {direction}")

      col = 0 

      while True:
        result, matched_string = row.search(col, query, 1, True)


        if result != None:
          pos, sym = self.get_symbol(idx,result)
          if sym:
            #print(f"Comp:maybe {sym}")
            if len(sym) > len(query) and query == sym[:len(query)]:
              comp_list.append(sym)
            col = result + 1
            if len(comp_list) > 20:
              break
          else:
            # error to get symbol
            break
        else:
          break
    if len(comp_list) > 0:
      comp_list = list(set(comp_list))
    return comp_list

  def get_symbol(self, r,c, search_list = None):
    line = self.rows[r]
    if not search_list:
      if self.mode == 'py' or self.mode == 'c':
        search_list = ( b".",b"(",b" ",b"+",b"/",b"-",b"~",b"=",b">",b"<",b"?",b",",b".",b"{",b"}",b"[",b"]",b"|")
      elif self.mode == 'md':
        search_list = ( b"(",b"+",b"-",b"~",b"=",b">",b"<",b"?",b",",b"{",b"}",b"[",b"]",b"|")
      else:
        return None
      
    period = 0
    for ch in range(c-1,-1,-1):
      for search_ch in search_list:
        if line.at(ch) == search_ch:
          period = ch
          break
      if period:
        break

    if period:
      result = self.period_regex[self.mode].search(line.substr(period,-1).decode('utf-8'))
    else:
      return (None, None)
    if result:
      #print(result.group(1))
      # Return the top column of the symbol and the symbol itself
      return (period + 1, result.group(1))
    else:
      return (None, None)

  def extract_region(self, r1, c1, r2, c2):
    # Text of the region (r1,c1)..(r2,c2), assumed already ordered. Multi-line
    # joins with '\n', matching how yank() re-inserts.
    if r1 == r2:
      return self.rows[r1].substr(c1, c2).decode('utf-8')
    parts = [self.rows[r1].substr(c1, -1).decode('utf-8')]
    for r in range(r1 + 1, r2):
      parts.append(self.rows[r].decode())
    parts.append(self.rows[r2].substr(0, c2).decode('utf-8'))
    return "\n".join(parts)

  def delete_region(self, r1, c1, r2, c2):
    self.modified = True
    if r1 == r2:
      self.rows[r1].delete_str(c1, c2 - c1)
    else:
      newchars = self.rows[r1].substr(0, c1)
      newchars.extend(self.rows[r2].substr(c2, -1))
      self.rows[r1].update_str(newchars)
      del self.rows[r1 + 1 : r2 + 1]
    return (r1, c1)

  def yank(self, r, c, yankbuf):
    self.modified = True
    if yankbuf.curbuf != None:
      line_str = yankbuf.curbuf
      while True:
        pos = line_str.find("\n")
        if pos != -1:
          #print(f"return found at {pos}")
          self.rows[r].insert_str(c, line_str[:pos])
          self.insert_return(r, c+pos, False)
          line_str = line_str[pos+1:]
          r += 1
          c = 0
        else:        
          self.rows[r].insert_str(c, line_str)
          c += len(line_str)
          break
    return (r,c)
        
  def erase_to_the_end(self, r, c, yankbuf):
    self.modified = True
    if c == 0 and r < len(self.rows) - 1:
      yankbuf.add_str(self.rows[r].chars.decode('utf-8'))
      yankbuf.add_str("\n")
      del self.rows[r]
    elif c == self.rows[r].get_len() and len(self.rows)-1 > r:
      self.rows[r].insert_str(c,self.rows[r+1].chars)
      yankbuf.add_str("\n")
      del self.rows[r+1]
    else:
      yankbuf.add_str(self.rows[r].substr(c, -1).decode('utf-8'))
      self.rows[r].erase_to_the_end(c)

  def delete_one_char_bs(self, r, c):
    self.modified = True
    if c == 0:
      if r == 0:
        return (r,c)
      col = self.rows[r - 1].get_len()
      self.rows[r-1].insert_str(self.rows[r-1].get_len(), self.rows[r].chars)
      del self.rows[r]
      return (r-1, col)
    else:
      self.rows[r].delete_str(c - 1,1)
      return (r, c - 1)      

  def delete_one_char_del(self, r, c, yankbuf):
    self.modified = True
    if self.rows[r].get_len() == 0:
      if len(self.rows) > 1:
        del self.rows[r]
    elif c == self.rows[r].get_len() and len(self.rows)-1 > r:
      self.rows[r].insert_str(c,self.rows[r+1].chars)
      del self.rows[r+1]
    else:
      yankbuf.add_str(self.rows[r].at(c).decode('utf-8'))
      self.rows[r].delete_str(c,1)
    return (r, c)

class yank_buffer:
  def __init__(self):
    self.bufs = []
    self.curbuf = None
    self.numbuf = 40

  def add_str(self, str):
    if self.curbuf == None:
      self.curbuf = str
    else:
      self.curbuf += str
    #print(f"yank buf '{self.curbuf}'")
    if pdeck_enabled:
      pdeck.clipboard_copy(self.curbuf.encode('utf-8'))
      
    

  def reset_buf(self):
    if self.curbuf != None:
      self.bufs.insert(0, self.curbuf)
      if len(self.bufs) > self.numbuf:
        del self.bufs[self.numbuf]
      self.curbuf = None


from erow import erow

if pdeck_enabled:
  class screen_interface:
    def __init__(self, vs):
      self.v = vs.v
      self.background_update = None
      # Optional zero-arg callable invoked while read() waits for a key, so a
      # plugin can apply asynchronous work (e.g. a background AI result) without
      # the user having to press a key. Kept separate from background_update,
      # which pem reassigns for its own scroll/animation updates.
      self.idle_callback = None

    def poll(self):
      return self.v.poll()

    # Frame batching is a desktop-only flicker fix (see the CPython
    # screen_interface); the device terminal composites the cursor into the
    # framebuffer, so here these are no-ops.
    def begin_frame(self):
      pass

    def end_frame(self):
      pass

    def print(self, str):
      self.v.print(str)

    def read(self, n):
      ret = None
      while True:
        ret = self.v.read_nb_bytes(1)
        if len(open_pending_list) > 0:
          return km.map['open'][0]
        if (edit_pending_list or switch_pending_list) and getattr(self, 'allow_remote_open', True):
          return REMOTE_EDIT_KEY
        if ret:
          if ret[0] > 0:
            break
        if self.idle_callback:
          try:
            self.idle_callback()
          except Exception:
            pass
        if self.v.active:

          if self.background_update:
            if not self.background_update():
              pdeck.delay_tick(7)
          else:
            pdeck.delay_tick(7)
          #time.sleep_ms(10)
        else:
          pdeck.delay_tick(100)
          #time.sleep_ms(200)
      # read_nb_bytes already returns bytes, so no encode step is needed; this
      # also preserves multi-byte UTF-8 (paste / AI send_char) that .encode('ascii')
      # used to choke on. The byte read above can split a UTF-8 char across
      # successive read() calls; the editor reassembles the bytes downstream.
      keys = ret[1]
      return keys

    def get_terminal_size(self):
      return self.v.get_terminal_size()

    def set_raw_mode(self, mode):
      self.v.print(el.raw_mode(mode))
else:
  class screen_interface:
    def __init__(self, vs):
      self.fd = sys.stdin.fileno()
      self.org_term = termios.tcgetattr(self.fd)
      # Set True by the editor only while it's idle at top level (no dialog), so
      # a queued remote-open (from pem_client) can be serviced without clobbering
      # a dialog or a multi-byte escape sequence.
      self.allow_remote_open = True
      # See the device screen_interface: a plugin can register a zero-arg
      # callable here to run while read() waits, so background work is applied
      # without needing a keystroke.
      self.idle_callback = None
    def poll(self):
      return False

    # Frame batching: while a frame is open, print() accumulates into _frame
    # instead of writing+flushing each fragment. A real PC terminal has a
    # blinking hardware cursor and would redraw it on each flushed write, so the
    # per-keystroke hide/redraw/show cycle was visible as a flicker. Coalescing
    # a whole refresh into one write+flush makes the update atomic.
    def begin_frame(self):
      self._frame = bytearray()
      self._buffering = True

    def end_frame(self):
      self._buffering = False
      if self._frame:
        sys.stdout.buffer.write(self._frame)
        sys.stdout.buffer.flush()
      self._frame = bytearray()

    def print(self, str):
      # The editor mixes str (escape sequences) and bytes/bytearray (rendered
      # rows). Go through the binary buffer so both work and UTF-8 is preserved.
      if isinstance(str, (bytes, bytearray)):
        data = str
      else:
        data = str.encode('utf-8')
      if getattr(self, '_buffering', False):
        self._frame.extend(data)
        return
      sys.stdout.buffer.write(data)
      sys.stdout.buffer.flush()
    def read(self, n):
      # Wait for a keypress, but wake periodically so queued remote-open requests
      # (pushed onto open_pending_list by the pem_client server) get serviced.
      # Stdin always has priority, so this never interrupts an escape sequence.
      while True:
        r, _, _ = select.select([self.fd], [], [],
                                0 if ((open_pending_list or edit_pending_list or switch_pending_list) and self.allow_remote_open) else 0.2)
        if r:
          break
        if open_pending_list and self.allow_remote_open:
          return km.map['open'][0]   # synthesize C-x C-f to drain the queue
        if (edit_pending_list or switch_pending_list) and self.allow_remote_open:
          return REMOTE_EDIT_KEY     # synthesize the remote-edit drain key
        if self.idle_callback:       # select timed out: run idle work, then re-wait
          try:
            self.idle_callback()
          except Exception:
            pass
      b = os.read(self.fd, 1)
      # Assemble a full UTF-8 character (e.g. Japanese via the OS IME); the
      # continuation bytes are already available on the fd.
      if b and b[0] >= 0xc0:
        need = 3 if b[0] >= 0xf0 else 2 if b[0] >= 0xe0 else 1
        while need > 0:
          more = os.read(self.fd, need)
          if not more:
            break
          b += more
          need -= len(more)
      return b

    def get_terminal_size(self):
      import os
      size = os.get_terminal_size()

      return (size.columns, size.lines)

    def set_raw_mode(self, mode):
      if mode == True:
        new = termios.tcgetattr(self.fd)
        new[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
        new[1] &= ~(termios.OPOST);
        new[2] |= (termios.CS8);
        new[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG);

        termios.tcsetattr(self.fd,termios.TCSANOW, new)
      else:
        new = self.org_term
        termios.tcsetattr(self.fd,termios.TCSANOW, new)
      return

def _start_open_server():
  # PC only: listen on a local TCP port so `pem_client FILE` can open files in
  # this already-running instance (emacs-server style). The first pem to bind
  # the port becomes the server; later instances just skip it. Requests are
  # pushed onto open_pending_list, which the open-file handler already drains.
  import socket
  import threading

  port = int(os.environ.get('PEM_SERVER_PORT', '51737'))
  try:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', port))
    srv.listen(5)
  except OSError:
    return None  # port already taken -> another instance is the server

  def serve():
    while True:
      try:
        conn, _ = srv.accept()
        data = b''
        while b'\n' not in data and len(data) < 4096:
          chunk = conn.recv(512)
          if not chunk:
            break
          data += chunk
        conn.close()
      except OSError:
        continue
      line = data.split(b'\n', 1)[0].decode('utf-8', 'replace').strip()
      if not line:
        continue
      # Wire format: "PATH\tLINE\tCOL" (line/col 1-based, optional).
      parts = line.split('\t')
      ln = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
      col = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
      open_pending_list.append((parts[0], ln, col))

  t = threading.Thread(target=serve)
  t.daemon = True
  t.start()
  return srv

def main(vs, args_in):
  # Get a virtual screen (No argument = current)
  v = screen_interface(vs)
  if not pdeck_enabled:
    _start_open_server()
  parser = argparse.ArgumentParser( description = "pem")
  parser.add_argument('-j','--japanese', action='store_true',help='Set Japansese font at launching') 
  parser.add_argument('-n','--new-file', action='store_true',help='Do not open the last edited file') 
  
  if len(args_in) > 1 and args_in[-1][0] != '-':
    parser.add_argument("filename", default=None)
    
  args = parser.parse_args(args_in[1:])

  filename=None
  try:
    filename=args.filename
  except Exception as e:
    pass

  resume_last_file = not args.new_file

  linenum = 0
  colnum = 0
  if resume_last_file and hasattr(km,'resume_last_file'):
    resume_last_file=km.resume_last_file

  if resume_last_file and filename == None:
    if file_exists(PEM_FILELIST):
      with open(PEM_FILELIST, "r") as f:
        first_line = f.read().split('\n')[0]
        if ',' in first_line:
          filename, linenum, colnum = first_line.split(',')
          linenum = int(linenum)
          colnum = int(colnum)
      if not file_exists(filename):
        filename = None
        linenum = 0
        colnum = 0


  try: 
    e = editor(v, args.japanese)
    e.vs = vs  # enable file-open event logging (vs is None on desktop CPython)
    # Register the editor for remote control so the pem_open command can open
    # files in this already-running instance (app_list['obj']). vs is None on
    # desktop CPython, where the pem_client TCP server provides the same
    # capability instead.
    if vs is not None:
      vs.register_module(e)
    e.setup_screen()
    e.open(filename, linenum, colnum)
    e.refresh_screen()
    while True:
      # Only service remote-open requests while idle at top level, so they don't
      # disrupt an open dialog / search / IME pre-edit.
      v.allow_remote_open = (e.mode == e.MODE_NORMAL)
      ret = e.process_key()
      if ret == 1:
        break
      e.refresh_screen()
    e.exit()
  except OSError:
    v.print("File open error\n")
  finally:
    # If a frame was left open by an exception mid-refresh, close batching so
    # these cleanup writes flush instead of being buffered and lost.
    v.end_frame()
    v.print(el.reset_font_color())
    v.set_raw_mode(False)
    v.print(el.erase_screen())
    #print("exiting..")
    v.print('finished\n')

if not pdeck_enabled:
  if __name__ == "__main__":
    main(None, sys.argv)
