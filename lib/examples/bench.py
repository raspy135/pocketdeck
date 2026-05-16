"""
PocketDeck VM Benchmark
Covers patterns common in PD apps: float math, array access,
attribute access, method calls, memoryview, list iteration.
Run as a PD app via main(vs, args), or standalone on the REPL.
"""
import time
import math
import array
import gc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_results = []
_out = None

def _pr(s):
  print(s, file=_out)

def _run(name, fn, iters):
  gc.collect()
  t0 = time.ticks_us()
  fn(iters)
  elapsed = time.ticks_diff(time.ticks_us(), t0)
  per_k = elapsed * 1000 // iters  # ns per iter
  _results.append((name, elapsed, iters, per_k))
  _pr(f"  {name:<22} {elapsed:>8} us  ({per_k} ns/iter)")

def _score():
  # Sum of (iters / elapsed_us) * 1e6 across all tests = total iters/sec
  return int(sum(it * 1_000_000 // max(el, 1) for _, el, it, _ in _results))

# ---------------------------------------------------------------------------
# 1. Integer arithmetic
#    Source: fps calc, index math throughout all demos
# ---------------------------------------------------------------------------
def _int_arith(n):
  x = 0
  for i in range(n):
    x = (x + 12345) * 7 % 1_000_003
  return x

# ---------------------------------------------------------------------------
# 2. Float arithmetic + trig
#    Source: rot() in texture_example, angle updates in cube/sphere/dither
# ---------------------------------------------------------------------------
def _float_trig(n):
  angle = 0.0
  x = y = 0.0
  for i in range(n):
    angle += 0.02
    s = math.sin(angle)
    c = math.cos(angle)
    x = x * c - y * s
    y = x * s + y * c
  return x

# ---------------------------------------------------------------------------
# 3. Object attribute access
#    Source: box.x, box.y, box.w, box.h, box.r, self.v in dither_test
# ---------------------------------------------------------------------------
class _Box:
  def __init__(self):
    self.x = -45
    self.y = -45
    self.w = 30
    self.h = 30
    self.r = 0.0
    self.dither = 8
    self.off_x = 100
    self.off_y = 100

def _attr_access(n):
  b = _Box()
  total = 0
  for i in range(n):
    total += b.x + b.y + b.w + b.h + b.off_x + b.off_y
    b.r += 0.01
    b.dither = (b.dither + 1) % 16
  return total

# ---------------------------------------------------------------------------
# 4. Method calls
#    Source: obj.update(), v.draw_polygon(), seq.update() per frame
# ---------------------------------------------------------------------------
class _Obj:
  def __init__(self):
    self.val = 0
  def update(self):
    self.val = (self.val + 1) % 65536
  def get(self):
    return self.val

def _method_calls(n):
  o = _Obj()
  for i in range(n):
    o.update()
  return o.get()

# ---------------------------------------------------------------------------
# 5. array.array 'h' (int16) read/write
#    Source: box.points[0..7] fill pattern in dither_test, cube, sphere
# ---------------------------------------------------------------------------
def _array_int16(n):
  pts = array.array('h', [0] * 8)
  for i in range(n):
    j = i & 0x7FFF
    pts[0] = j
    pts[1] = j + 10
    pts[2] = j + 20
    pts[3] = j + 30
    pts[4] = j + 1
    pts[5] = j + 11
    pts[6] = j + 21
    pts[7] = j + 31
    _ = pts[0] + pts[4]
  return pts[0]

# ---------------------------------------------------------------------------
# 6. array.array 'f' (float32) read/write
#    Source: matrix, v_rot, v_pos, temp_verts in cube/sphere
# ---------------------------------------------------------------------------
def _array_float(n):
  mat = array.array('f', [0.0] * 16)
  for i in range(n):
    f = float(i & 0xFF) * 0.01
    mat[0] = f
    mat[3] = mat[0] * 2.0 + 1.0
    mat[5] = mat[3] - f
    mat[15] = mat[5] * mat[0]
    _ = mat[0] + mat[15]
  return mat[0]

# ---------------------------------------------------------------------------
# 7. memoryview slice read
#    Source: mv_poly[i*6 : i*6+6] in cube/sphere draw loop
# ---------------------------------------------------------------------------
def _memoryview_slice(n):
  buf = array.array('h', list(range(200)))
  mv = memoryview(buf)
  total = 0
  for i in range(n):
    sl = mv[(i % 32) * 6 : (i % 32) * 6 + 6]
    total += sl[0] + sl[2] + sl[4]
  return total

# ---------------------------------------------------------------------------
# 8. Object list iteration
#    Source: for box in self.boxes (20 boxes) in dither_test
# ---------------------------------------------------------------------------
def _list_iter(n):
  boxes = [_Box() for _ in range(20)]
  total = 0
  for _ in range(n):
    for b in boxes:
      b.r += 0.005
      b.dither = (b.dither + 1) % 16
      total += b.x + b.off_x
  return total

# ---------------------------------------------------------------------------
# 9. String formatting
#    Source: str(fps) + " FPS", f"{fps} FPS" patterns
# ---------------------------------------------------------------------------
def _string_fmt(n):
  fps = 0
  s = ""
  for i in range(n):
    fps = (fps + 1) % 1000
    s = f"{fps} FPS, min {fps - 1}"
  return len(s)

# ---------------------------------------------------------------------------
# 10. Simulated frame loop  (closest to real app behaviour)
#     20 boxes, each gets: array fill (8 shorts), float rotation, attr read
# ---------------------------------------------------------------------------
def _frame_loop(n):
  boxes = [_Box() for _ in range(20)]
  pts = array.array('h', [0] * 8)
  angle = 0.0
  for _ in range(n):
    angle += 0.02
    s = math.sin(angle)
    c = math.cos(angle)
    for b in boxes:
      x, y, w, h = b.x, b.y, b.w, b.h
      pts[0] = x;     pts[1] = x + w; pts[2] = x + w; pts[3] = x
      pts[4] = y;     pts[5] = y;     pts[6] = y + h;  pts[7] = y + h
      b.r += 0.01
      for i in range(4):
        rx = pts[i] * c - pts[i + 4] * s
        ry = pts[i] * s + pts[i + 4] * c
        pts[i]     = int(rx) + b.off_x
        pts[i + 4] = int(ry) + b.off_y
  return pts[0]

# ---------------------------------------------------------------------------
# pem.py benchmarks
# ---------------------------------------------------------------------------

# P1. erow.update() pattern
#     enumerate(bytearray) + array.append() per byte — the hottest loop in pem.py.
#     Each iteration: tuple unpack, bitwise check, conditional appends.
def _pem_erow_update(n):
  line = bytearray(b'Hello world \t test \xc3\xa9 end of line here yes' * 2)
  for _ in range(n):
    cbmap = array.array('h')
    bcmap = array.array('h')
    bdmap = array.array('h')
    dbmap = array.array('h')
    numchar = 0
    numdchar = 0
    for i, ch in enumerate(line):
      if ch & 0xc0 == 0xc0:
        csize = 1
        dsize = 2
      elif ch & 0xc0 == 0x80:
        bcmap.append(numchar)
        bdmap.append(numdchar)
        continue
      elif ch == 0x9:
        csize = 1
        dsize = 4
      else:
        csize = 1
        dsize = 1
      cbmap.append(i)
      bcmap.append(numchar)
      dbmap.append(i)
      bdmap.append(numdchar)
      numchar += csize
      numdchar += dsize
  return numchar

# P2. _hl_py() pattern
#     Character-by-character string building with result += c.
#     O(n^2) allocations — dominant cost for syntax highlighting.
def _pem_str_build(n):
  src = "def hello(x, y):  # comment\n    return x + y\n"
  for _ in range(n):
    result = ""
    i = 0
    while i < len(src):
      c = src[i]
      if c == '#':
        result += src[i:]
        break
      result += c
      i += 1
  return len(result)

# P3. Double array index pattern
#     bdmap[cbmap[at]] called per character per visible line in render loop.
def _pem_double_index(n):
  cbmap = array.array('h', range(100))
  bdmap = array.array('h', range(100))
  total = 0
  for _ in range(n):
    for at in range(90):
      total += bdmap[cbmap[at]]
  return total

# P4. Guard check + indexed lookup
#     if not self.updated: self.update() pattern in every erow method,
#     followed by array index chain.
class _ErowMock:
  def __init__(self):
    self.updated = True
    self.cbmap = array.array('h', range(80))
    self.bdmap = array.array('h', range(80))
    self.len = 80
  def update(self):
    pass
  def cpos_to_dpos(self, at):
    if not self.updated:
      self.update()
    if self.len == 0:
      return 0
    if at >= len(self.cbmap):
      return self.bdmap[-1]
    return self.bdmap[self.cbmap[at]]

def _pem_method_guard(n):
  rows = [_ErowMock() for _ in range(20)]
  total = 0
  for _ in range(n):
    for row in rows:
      for at in range(0, 80, 4):
        total += row.cpos_to_dpos(at)
  return total

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_benchmark(out=None):
  global _out
  _out = out
  _results.clear()

  _pr("=" * 52)
  _pr("PocketDeck VM Benchmark")
  _pr("=" * 52)

  _run("int_arith",        _int_arith,        10_000)
  _run("float_trig",       _float_trig,        2_000)
  _run("attr_access",      _attr_access,      10_000)
  _run("method_calls",     _method_calls,     10_000)
  _run("array_int16",      _array_int16,      10_000)
  _run("array_float",      _array_float,      10_000)
  _run("memoryview_slice", _memoryview_slice,  5_000)
  _run("list_iter",        _list_iter,           200)
  _run("string_fmt",       _string_fmt,        2_000)
  _run("frame_loop",       _frame_loop,          100)
  _pr("")
  _pr("-- pem.py patterns --")
  _run("pem_erow_update",  _pem_erow_update,    200)
  _run("pem_str_build",    _pem_str_build,    2_000)
  _run("pem_double_index", _pem_double_index,   500)
  _run("pem_method_guard", _pem_method_guard,   100)

  score = _score()
  _pr("=" * 52)
  _pr(f"SCORE: {score}  (higher = faster)")
  _pr("=" * 52)
  return score

import io

class _Tee(io.IOBase):
  def __init__(self, a, b):
    self.a = a
    self.b = b
  def write(self, s):
    self.a.write(s)
    self.b.write(s)
    return len(s)
  def flush(self):
    self.a.flush()
    self.b.flush()

def main(vs, args):
  if args and len(args) > 1 and args[1]:
    with open(args[1], 'w') as f:
      run_benchmark(out=_Tee(vs, f))
  else:
    run_benchmark(out=vs)

if __name__ == "__main__":
  run_benchmark()
