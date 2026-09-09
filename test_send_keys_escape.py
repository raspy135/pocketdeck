"""send_keys escape handling for lib/noa/gpt_tools.py (run: python3 -B test_send_keys_escape.py)."""
import base64, json, sys, types

sys.path[:0] = ["lib", "lib/noa"]
for n, real in (("ujson", json), ("ubinascii", base64)):
  sys.modules.setdefault(n, real)
for n in ("pdeck", "pdeck_utils"):
  m = types.ModuleType(n)
  m.CaptureStream = object
  sys.modules.setdefault(n, m)

from gpt_tools import _unescape_keys as u

def test_arrows():
  assert u("\\x1b[A") == "\x1b[A"
  assert u("\\e[D") == "\x1b[D"
  assert u("\\u001b[B") == "\x1b[B"

def test_control_chars():
  assert u("\\x18") == "\x18"        # Ctrl-X
  assert u("ls\\r") == "ls\r"
  assert u("a\\tb\\nc") == "a\tb\nc"

def test_plain_text_untouched():
  assert u("ls -la") == "ls -la"
  assert u("grep '\\d+' f.py") == "grep '\\d+' f.py"   # unknown escape kept
  assert u("C:\\\\tmp") == "C:\\tmp"
  assert u("trailing\\") == "trailing\\"
  assert u("\\xZZ") == "\\xZZ"       # bad hex kept verbatim

for n, f in sorted(globals().items()):
  if n.startswith("test_"):
    f(); print("ok", n)
print("all passed")
