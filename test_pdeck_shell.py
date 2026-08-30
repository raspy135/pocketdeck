#!/usr/bin/env python3
# Self-check for the shell command line handling in the firmware's
# pdeck_utils.py (';' sequencing, '|' pipes, '>' redirects, quoting).
# Run from the repo root:
#   python3 -B test_pdeck_shell.py
# Desktop (CPython) only -- the firmware module is exec'd with fake pdeck/
# esclib/pstdin modules, so nothing here touches a device.

import os
import sys
import types

SRC = ('/home/ryan/esp/esp-idf-2025/myprojects/work/micropython/ports/esp32/'
       'modules/pdeck_utils.py')


def _fake(name, **attrs):
  m = types.ModuleType(name)
  for k, v in attrs.items():
    setattr(m, k, v)
  sys.modules[name] = m
  return m


def load_pdeck_utils():
  """exec the firmware pdeck_utils with just enough of MicroPython faked."""
  import asyncio  # noqa: F401  (import it before _thread is faked out)
  _fake('pdeck', init=lambda: None, get_screen_num=lambda: 1,
        get_default_terminal_font_size=lambda: 12, cmd_exists=lambda n: False)
  _fake('_thread', stack_size=lambda n: None,
        allocate_lock=lambda: _Lock(), start_new_thread=lambda *a: None)
  _fake('esclib', esclib=lambda: types.SimpleNamespace(
      raw_mode=lambda b: '', cursor_mode=lambda b: '',
      wraparound_mode=lambda b: ''))
  sys.print_exception = lambda e, f=None: print(repr(e), file=f or sys.stdout)
  ns = {'__name__': 'pdeck_utils', 'const': lambda x: x}
  exec(compile(open(SRC).read(), SRC, 'exec'), ns)
  mod = types.ModuleType('pdeck_utils')
  mod.__dict__.update(ns)
  sys.modules['pdeck_utils'] = mod
  return mod


class _Lock:
  def __enter__(self):
    return self

  def __exit__(self, *a):
    return False

  def acquire(self):
    pass

  def release(self):
    pass


class FakeStdin:
  """Stand-in for the pstdin bridge: one buffered string, taken once."""
  def __init__(self):
    self.buf = None

  def feed(self, data):
    self.buf = data

  def take(self):
    b, self.buf = self.buf, None
    return b


def register_fake_commands(stdin):
  # 'one' has no trailing newline on purpose: sequenced outputs must still be
  # separated when they are concatenated.
  _fake('f1', main=lambda vs, args: vs.write('one'))
  _fake('f2', main=lambda vs, args: vs.write('two\n'))
  _fake('up', main=lambda vs, args: vs.write((stdin.take() or '').upper()))
  _fake('boom', main=lambda vs, args: 1 / 0)


def main():
  if not os.path.exists(SRC):
    print('SKIP: firmware pdeck_utils.py not found at %s' % SRC)
    return
  pu = load_pdeck_utils()
  stdin = FakeStdin()
  sys.modules['pstdin'] = stdin
  register_fake_commands(stdin)

  # --- splitting, with quoting -------------------------------------------
  assert pu.split_commands('f1 ; f2') == ['f1', 'f2']
  assert pu.split_commands('grep "a;b" x ; ls') == ['grep "a;b" x', 'ls']
  assert pu.split_commands("grep 'a;b' x") == ["grep 'a;b' x"]
  assert pu.split_commands(' ; f1 ;; f2 ; ') == ['f1', 'f2']
  assert pu.split_commands('') == []
  # ';' does not swallow pipes, and '|' does not swallow ';'
  assert pu.split_commands('f1 | up ; f2') == ['f1 | up', 'f2']
  assert pu.split_pipeline('f1 | up') == ['f1', 'up']
  assert pu.split_pipeline('grep "a|b" x') == ['grep "a|b" x']
  # argv form (the C shell has already stripped quotes)
  assert pu.split_commands_args(['ls', '-l', ';', 'cat', 'f']) == \
      [['ls', '-l'], ['cat', 'f']]
  assert pu.split_commands_args([';', 'ls', ';']) == [['ls']]
  assert pu.split_commands_args([]) == []

  # --- sequential execution ----------------------------------------------
  cap, out = pu.run_pipeline('f1 ; f2')
  assert cap is not None and out == 'one\ntwo\n', repr(out)
  cap, out = pu.run_pipeline('f1 | up ; f2')
  assert out == 'ONE\ntwo\n', repr(out)
  # a quoted ';' is an argument, not a separator
  seen = []
  _fake('argecho', main=lambda vs, args: seen.append(args))
  cap, out = pu.run_pipeline('argecho "a ; b"')
  assert seen == [['argecho', 'a ; b']], repr(seen)
  # a crashing command does not stop the next one
  cap, out = pu.run_pipeline('boom ; f2')
  assert out.endswith('two\n') and 'ZeroDivisionError' in out, repr(out)

  # --- '&&' / '||' are rejected, not silently swallowed -------------------
  assert pu.find_unsupported('f1 && f2') == '&&'
  assert pu.find_unsupported('f1 || f2') == '||'
  assert pu.find_unsupported('grep "a||b" x ; f1') is None
  assert pu.find_unsupported('f1 | up ; f2') is None
  cap, out = pu.run_pipeline('f1 && f2')
  assert cap is None and out.startswith("'&&' is not supported"), repr(out)
  cap, out = pu.run_pipeline('f1 || f2')
  assert cap is None and out.startswith("'||' is not supported"), repr(out)

  # --- redirect binds to its own segment ---------------------------------
  path = os.path.join(os.environ.get('TMPDIR', '/tmp'), 'test_pdeck_shell.txt')
  cap, out = pu.run_pipeline('f1 > %s ; f2' % path)
  assert out == 'two\n', repr(out)
  assert open(path).read() == 'one'
  cap, out = pu.run_pipeline('f2 >> %s ; f1' % path)
  assert out == 'one\n', repr(out)
  assert open(path).read() == 'onetwo\n'
  os.remove(path)

  # every '/dev/null' form discards the output instead of writing a file:
  # stdout and stderr are one stream here, so '2>' hides everything too.
  for form in ('f1 > /dev/null', 'f1 >/dev/null', 'f1 >> /dev/null',
               'f1 1>/dev/null', 'f1 2>/dev/null', 'f1 2> /dev/null',
               'f1 &>/dev/null', 'f1 > /dev/null 2>&1', 'f1 | up > /dev/null'):
    cap, out = pu.run_pipeline(form)
    assert cap is not None and out == '', (form, repr(out))
  cap, out = pu.run_pipeline('f1 2>/dev/null ; f2')
  assert cap is not None and out == 'two\n', repr(out)
  # discarded without touching the filesystem (the device has no /dev/null),
  # while a redirect that really fails reports it instead of raising
  assert pu.write_redirect('x', 'w', pu.DEVNULL) is None
  assert pu.write_redirect('x', 'w', '/no/such/dir/f').startswith('cannot write')

  print('OK')


if __name__ == '__main__':
  main()
