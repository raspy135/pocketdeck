#!/usr/bin/env python3
# Self-check for the pem editor's non-trivial logic. Run from the repo root:
#   python3 -B test_pem.py
# Desktop (CPython) only -- it drives a real editor against a fake screen.

import os
import sys
import tempfile

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
                for p in ('lib', 'lib/noa')]

import pem
import pem_keymap_default as km
from erow import erow


class FakeScreen:
  def __init__(self):
    self.out = []
    self.background_update = None
    self.idle_callback = None
    self.allow_remote_open = True

  def poll(self):
    return False

  def begin_frame(self):
    pass

  def end_frame(self):
    pass

  def print(self, s):
    self.out.append(s)

  def read(self, n):
    raise AssertionError('the tests never block on input')

  def get_terminal_size(self):
    return (40, 12)

  def set_raw_mode(self, mode):
    pass


def new_editor(tmp, text):
  path = os.path.join(tmp, 'sample.py')
  with open(path, 'w') as f:
    f.write(text)
  e = pem.editor(FakeScreen(), False)
  e.setup_screen()
  e.open(path)
  e.refresh_screen()
  return e, path


def test_highlight():
  # _hl_code drives both 'py' and 'c'; each mode must find its own comments,
  # strings and keywords, and leave an unhighlightable line untouched.
  py = pem._hl_line(b'def f(): x = "s"  # note', 'py')
  assert pem._HL_KEYWORD in py and pem._HL_STRING in py and pem._HL_COMMENT in py
  c = pem._hl_line(b'static int x = 1; /* blk */ // eol', 'c')
  assert pem._HL_KEYWORD in c and c.count(pem._HL_COMMENT) == 2, c
  assert pem._hl_line(b'int x;', 'py') == b'int x;'      # 'int' is not a py keyword
  assert pem._hl_line(b'plain words', 'txt') == b'plain words'
  assert pem._hl_line(b'', 'py') == b''
  assert pem._HL_HEADING in pem._hl_line(b'# Title', 'md')
  # an unterminated C block comment still colours to end of line
  assert pem._hl_line(b'x /* open', 'c').endswith(pem._B_HL_OFF)


def test_dialog_rows(e):
  # Opening a dialog takes rows from the text area; every close path returns
  # exactly the same rows, whichever key dismissed it.
  base = (e.file.h, e.text_height, e.h_diff)
  e.open_select_dialog(['x', 'y', 'z'], 3, 'T', lambda i, it: None)
  assert (e.file.h, e.text_height, e.h_diff) == (base[0] - 3, base[1] - 3, base[2] + 3)
  e.process_select_dialog(b'\x07')                       # C-g
  assert (e.file.h, e.text_height, e.h_diff) == base

  picked = []
  e.open_select_dialog(['alpha', 'beta', 'gamma'], 3, 'T', lambda i, it: picked.append(it))
  e.process_select_dialog(b'g')                          # incremental filter
  assert [e.sd_info.slist[i] for i in e.sd_info.filtered] == ['gamma']
  e.process_select_dialog(b'\x0d')                       # Enter
  assert picked == ['gamma'] and (e.file.h, e.text_height, e.h_diff) == base

  e.open_input_line_dialog('S', 'H', lambda line: None)
  assert (e.file.h, e.text_height, e.h_diff) == (base[0] - 1, base[1] - 1, base[2] + 1)
  e.process_input_line_dialog(b'\x07')
  assert (e.file.h, e.text_height, e.h_diff) == base


def test_remote_queue(e):
  # Requests are applied on the editor's own thread by drain_remote_requests.
  ok, msg = e._apply_edit_block(1, 1, 'def a(x):')
  assert ok and e.file.rows[0].decode() == 'def a(x):', msg

  res = {'done': False, 'ok': False, 'msg': ''}
  pem.remote_pending_list.append(['edit', (2, 2, '  return 99'), res])
  e.drain_remote_requests()
  assert res['done'] and res['ok'] and not pem.remote_pending_list
  assert e.file.rows[1].decode() == '  return 99'

  # a handler that raises must be reported, not escape the drain loop
  bad = {'done': False, 'ok': False, 'msg': ''}
  pem.remote_pending_list.append(['edit', ('x', 'y', 'z'), bad])
  e.drain_remote_requests()
  assert bad['done'] and not bad['ok'] and not pem.remote_pending_list

  assert not e._apply_edit_block(99, 1, 'x')[0]           # range past EOF
  assert not e._apply_switch_buffer('missing.py')[0]
  # with no editor loop running, a pub_* call must time out and clean up
  ok, msg = e.pub_switch_buffer('missing.py', timeout_ms=120)
  assert not ok and 'timeout' in msg and not pem.remote_pending_list

  ok, txt = e.pub_read_content(1, 2)
  assert ok and txt == 'def a(x):\n  return 99', repr(txt)
  assert e.pub_get_status()['modified'] is True


def test_undo(e):
  u = e.file.undo
  e.file_row, e.file_col = 0, 0
  before = e.file.rows[0].decode()
  depth = len(u.undo)
  for ch in b'abc':                       # one word coalesces to one group
    u.record(e, 'insert', pem._edit_class(bytes([ch])))
    e.file.insert_str(e.file_row, e.file_col, bytes([ch]))
    e.file_col += 1
  assert len(u.undo) == depth + 1, (depth, len(u.undo))
  assert u.undo_one(e) and e.file.rows[0].decode() == before
  assert u.redo_one(e) and e.file.rows[0].decode() != before
  u.undo_one(e)
  assert pem._edit_class(b'a') == 'word' and pem._edit_class(b' ') == 'sep'
  assert pem._edit_class(b'\r') == 'nl'


def test_region(e):
  e.file_row, e.file_col = 0, 0
  e.set_mark()
  e.file_row, e.file_col = 0, 3
  assert e._region_bounds() == ((0, 0), (0, 3))
  e.copy_region()
  assert e.yankbuf.curbuf == e.file.rows[0].decode()[:3]
  assert e._region_bounds() is None       # copying deactivates the region


def test_wrapping(e):
  # _wrap_seg_start finds the start of a wrapped segment; a wide (2-column)
  # char that would straddle the edge is pushed to the next line.
  f = e.file
  saved, f.w = f.w, 10
  plain = erow(bytearray(b'x' * 25), 2, 10)
  assert f._wrap_seg_start(plain, 25) == 20
  assert f._wrap_seg_start(plain, 15) == 10
  wide = erow(bytearray('あ'.encode() * 8), 2, 10)
  assert f._wrap_seg_start(wide, wide.get_len()) == 5
  f.w = saved


def test_erow():
  r = erow(bytearray('aあ\tz'.encode()), 2, 12)
  assert r.get_len() == 4          # get_len() forces the lazy update()
  assert r.tab_detected
  # expanded_to_pos is the first half of expanded_to_pos_with_d, always
  for at in range(-2, 10):
    assert r.expanded_to_pos(0, at) == r.expanded_to_pos_with_d(0, at)[0]
  assert r.search(0, 'z')[0] is not None
  assert r.search(0, 'nope') == (None, None)
  # reverse search reports an absolute offset
  rr = erow(bytearray(b'abcabc'), 2, 12)
  assert rr.search(-1, 'abc', -1)[0] == 3, rr.search(-1, 'abc', -1)


def test_paging_and_save(e, tmp):
  big = os.path.join(tmp, 'big.txt')
  with open(big, 'w') as f:
    f.write('\n'.join('line %d' % i for i in range(60)))
  e.process_open_file(big.encode())
  e.render_main_text(True)
  top = e.file_row
  e.pending_keys = km.map['pagedown'][0]
  e.process_key()
  down = e.file_row
  assert down > top
  e.pending_keys = km.map['pageup'][0]
  e.process_key()
  assert e.file_row < down

  e.file.rows[0].insert_str(0, b'#')
  assert e.file.save() > 0
  with open(big) as f:
    assert f.read().startswith('#line 0')


def test_paths():
  assert pem._basename('/a/b/c.txt') == 'c.txt'
  assert pem._dirname('/a/b/c.txt') == '/a/b'
  assert pem._basename('/a/b/') == 'b'
  assert pem._dirname('c.txt') == '.'
  assert pem._trim_path('/very/long/path/to/file.md', 14) == '*to/file.md'
  assert pem._trim_path('short.md', 20) == 'short.md'


def test_completion():
  # TAB completion must keep the directory text the user typed: a completion
  # that rewrites 'pd' as './pd' (or '/' as '//') no longer names the file.
  tmp = tempfile.mkdtemp()
  os.mkdir(os.path.join(tmp, 'pd'))
  for n in ('README.md', 'RESULT.txt', 'notes.md'):
    open(os.path.join(tmp, 'pd', n), 'w').write('x')
  e, _ = new_editor(tmp, 'hello\n')
  cwd = os.getcwd()
  os.chdir(tmp)
  try:
    def complete(typed):
      e.open_input_line_dialog('Open', 'Filename', e.process_open_file,
                               default_str=typed.encode())
      e.process_input_line_dialog(b'\x09')
      out = (e.sl_info.line.decode() if e.sl_info else None,
             e.sd_info.slist if e.sd_info else None)
      e.sl_info = None
      e.sd_info = None
      e.mode = e.MODE_NORMAL
      return out

    assert complete('pd/n') == ('pd/notes.md', None)
    assert complete('pd')[0] == 'pd/'                  # not './pd/'
    assert complete('pd/R')[1] == ['pd/README.md', 'pd/RESULT.txt']
    assert complete(tmp + '/pd/n')[0] == tmp + '/pd/notes.md'
    assert complete('/')[1][0].startswith('/') and not complete('/')[1][0].startswith('//')
    assert complete('pd/zzz') == ('pd/zzz', None)      # no match: line untouched
  finally:
    os.chdir(cwd)


def main():
  tmp = tempfile.mkdtemp()
  e, _ = new_editor(tmp, 'def alpha():\n  return 1\n\ndef beta():\n  return 2\n')
  test_highlight()
  test_paths()
  test_completion()
  test_erow()
  test_dialog_rows(e)
  test_remote_queue(e)
  test_undo(e)
  test_region(e)
  test_wrapping(e)
  test_paging_and_save(e, tmp)
  print('pem self-check: all tests passed')


if __name__ == '__main__':
  main()
