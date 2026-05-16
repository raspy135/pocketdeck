"""
String building micro-benchmark: += vs list+join vs bytearray
Run as PD app, or: import bench_str; bench_str.main(None, [])
"""
import time
import gc

SRC = "def hello(x, y):  # comment\n    return x + y\n"

_PY_KEYWORDS = frozenset([
  'False','None','True','and','as','assert','async','await',
  'break','class','continue','def','del','elif','else','except',
  'finally','for','from','global','if','import','in','is',
  'lambda','nonlocal','not','or','pass','raise','return',
  'try','while','with','yield',
])

def _is_id_cont(c):
  return c.isalpha() or c.isdigit() or c == '_'

# --- 1. concat: result += c ---
def _hl_py_concat(s):
  result = ""
  i = 0
  n = len(s)
  while i < n:
    c = s[i]
    if c == '#':
      result += s[i:]
      break
    if c.isalpha() or c == '_':
      j = i + 1
      while j < n and _is_id_cont(s[j]):
        j += 1
      word = s[i:j]
      if word in _PY_KEYWORDS:
        result += '\x1b[1m' + word + '\x1b[0m'
      else:
        result += word
      i = j
    else:
      result += c
      i += 1
  return result

# --- 2. list + join ---
def _hl_py_join(s):
  parts = []
  append = parts.append
  i = 0
  n = len(s)
  modified = False
  while i < n:
    c = s[i]
    if c == '#':
      append(s[i:])
      break
    if c.isalpha() or c == '_':
      j = i + 1
      while j < n and _is_id_cont(s[j]):
        j += 1
      word = s[i:j]
      if word in _PY_KEYWORDS:
        append('\x1b[1m')
        append(word)
        append('\x1b[0m')
        modified = True
      else:
        append(word)
      i = j
    else:
      append(c)
      i += 1
  if not modified:
    return s
  return ''.join(parts)

_B_ESC_ON  = b'\x1b[1m'
_B_ESC_OFF = b'\x1b[0m'

# --- 3. bytearray accumulator ---
def _hl_py_bytearray(s):
  buf = bytearray()
  i = 0
  n = len(s)
  modified = False
  while i < n:
    c = s[i]
    if c == '#':
      buf.extend(s[i:].encode())
      break
    if c.isalpha() or c == '_':
      j = i + 1
      while j < n and _is_id_cont(s[j]):
        j += 1
      word = s[i:j]
      if word in _PY_KEYWORDS:
        buf.extend(_B_ESC_ON)
        buf.extend(word.encode())
        buf.extend(_B_ESC_OFF)
        modified = True
      else:
        buf.extend(word.encode())
      i = j
    else:
      buf.extend(c.encode())
      i += 1
  if not modified:
    return s
  return buf.decode()

def _bench(fn, n, vs):
  gc.collect()
  t0 = time.ticks_us()
  for _ in range(n):
    fn(SRC)
  elapsed = time.ticks_diff(time.ticks_us(), t0)
  ns = elapsed * 1000 // n
  print(f"  {fn.__name__:<20} {elapsed:>8} us  ({ns} ns/iter)", file=vs)
  return elapsed

def main(vs, args):
  N = 5000
  print("String build benchmark", file=vs)
  print(f"  input: {repr(SRC[:30])}...", file=vs)
  print(f"  iters: {N}", file=vs)
  # warmup
  for fn in (_hl_py_concat, _hl_py_join, _hl_py_bytearray):
    _bench(fn, 100, vs)
  print("---", file=vs)
  t1 = _bench(_hl_py_concat,    N, vs)
  t2 = _bench(_hl_py_join,      N, vs)
  t3 = _bench(_hl_py_bytearray, N, vs)
  best = min(t1, t2, t3)
  print(f"  winner: {best} us (1.00x)", file=vs)
  for label, t in [("concat", t1), ("join", t2), ("bytearray", t3)]:
    print(f"    {label}: {t/best:.2f}x", file=vs)
