# Self-check for lib/chop.py: slicing, wavetable frames, grid -> Pie patterns,
# the polymeter scheduler, and a render of the UI.
# Run: python -B test_chop.py [out.png]
import sys, types, math, struct, time, array, wave, os

for name in ('audio', 'pdeck', 'esclib'):
  sys.modules[name] = types.ModuleType(name)
mp = types.ModuleType('micropython')
mp.native = mp.viper = lambda f: f
sys.modules['micropython'] = mp
sys.path[:0] = ['lib', 'lib/noa']       # lib/noa has the real Pie sequencer
import audio
audio.ECHO_PINGPONG = 1
audio.sample_rate = lambda *a: 24000
audio.get_current_tick = lambda: 0
time.ticks_ms = lambda: int(time.time() * 1000)
time.ticks_diff = lambda a, b: a - b
time.ticks_add = lambda a, b: a + b
import chop

RATE = chop.RATE

def take(hits, secs=3):
  # silence with a decaying burst at each hit time (seconds)
  n = RATE * secs
  out = [0] * n
  for t in hits:
    for i in range(3000):
      out[int(t * RATE) + i] = int(20000 * math.exp(-i / 600) * math.sin(i * 0.05))
  return memoryview(bytearray(struct.pack('<%dh' % n, *out)))

# ---- slicing: three hits -> three slices starting just before each hit ----
hits = [0.5, 1.2, 2.0]
mv = take(hits)
sl = chop.find_slices(chop.envelope(mv))
assert len(sl) == 3, sl
for (s, e), t in zip(sl, hits):
  start = s / 2 / RATE
  assert t - 0.03 <= start <= t + 0.005, (start, t)
  assert e > s and s % 2 == 0 and e % 2 == 0
assert sl[2][1] < len(mv)   # tail silence trimmed
assert len(chop.find_slices(chop.envelope(take([0.2 * k for k in range(1, 13)])))) == 8
eq = chop.find_slices(chop.envelope(memoryview(bytearray(RATE * 2))))
assert len(eq) == 8 and eq[0][0] == 0
# one hit ringing to the end must be capped (sampler 16.16 position limit)
long = memoryview(bytearray(struct.pack('<%dh' % (RATE * 3), *[12000 if i % 50 < 25 else -12000 for i in range(RATE * 3)])))
assert all(e - s <= chop.MAX_SLICE for s, e in chop.find_slices(chop.envelope(long)))

# ---- wavetable frames: right shape, loop-safe ends, normalized ----
fr = chop.make_frames(mv, sl[0][0], sl[-1][1])
assert len(fr) == chop.NF and all(len(f) == chop.FS for f in fr)
assert all(abs(f[0]) <= 1 for f in fr)
assert max(max(f) for f in fr) > 20000
assert chop.make_frames(mv, 0, 100) == []

# ---- stereo: same slices (x2 offsets) and same frames from the left channel ----
st = array.array('h')
for (x,) in struct.iter_unpack('<h', mv):
  st.append(x)
  st.append(x // 3)
sv = chop.byteview(st)
assert len(sv) == len(mv) * 2 and sv[1] == mv[1]
assert chop.find_slices(chop.envelope(sv, 2)) == sl
assert chop.make_frames(sv, sl[0][0] * 2, sl[-1][1] * 2, 2) == fr

# ---- bundled demo take: all seven sounds found ----
demo = None
if os.path.exists('lib/data/chop_demo.wav'):
  wf = wave.open('lib/data/chop_demo.wav')
  demo = memoryview(wf.readframes(wf.getnframes()))
  starts = [s / 2 / RATE for s, e in chop.find_slices(chop.envelope(demo, 2))]
  for t in (0.05, 0.35, 0.62, 0.85, 1.12, 1.40, 1.75):   # see utils/gen_chop_demo.py
    assert any(abs(t - x) < 0.04 for x in starts), (t, starts)

# ---- grid row -> Pie mini-notation ----
assert chop.loop_bars(16) == 1 and chop.loop_bars(6) == 3 and chop.loop_bars(7) == 7
assert chop.row_pattern([1, 0, 0, 0] * 4, 16, False, 2, 0, 5) == '2 ~ ~ ~ 2 ~ ~ ~ 2 ~ ~ ~ 2 ~ ~ ~'
p6 = chop.row_pattern([1, 0, 0, 0, 0, 0] + [0] * 10, 6, False, 0, 0, 5)
assert p6.startswith('<[0 ~ ~ ~ ~ ~ 0 ~') and p6.count('[') == 3
assert chop.row_pattern([3] + [0] * 15, 16, True, 0, -2, 5).startswith('-8 ~')

# ---- scheduler: a 6-step row against a 16-step row, through Pie, exactly once ----
class Rec:
  def __init__(self): self.calls = []
  def __getattr__(self, name):
    return lambda *a: self.calls.append((name, a))

now = [5000]
audio.get_current_tick = lambda: now[0]
tp = types.SimpleNamespace(get_tp_keys=lambda: b'\xff\xff\xff\0\xff\0\0')
s, w = Rec(), Rec()
app = chop.Chop(types.SimpleNamespace(v=tp), s, w, Rec(), Rec(), Rec(), Rec())
app.load(mv)
assert len(app.rows) == 3 and not any(r.tone for r in app.rows)
for r in app.rows:
  r.cells = [0] * 16
app.rows[0].cells[0] = 1                    # row 1: step 0 of a 16-step loop
app.rows[1].n = 6
app.rows[1].cells[0] = app.rows[1].cells[4] = 1   # row 2: steps 0 and 4 of a 6-step loop
for i in range(3):
  app.rebuild(i)
s.calls.clear()
app.toggle()
t0, bar = app.t0, app.bar()
while now[0] < t0 + 3 * bar:
  app.tick()
  now[0] += 517
plays = sorted([a for n, a in s.calls if n == 'play' and a[2] < t0 + 3 * bar], key=lambda p: (p[2], p[0]))
want = [(0, False, t0 + c * bar) for c in range(3)]
want += [(1, False, t0 + int(g / 16 * bar)) for g in range(48) if g % 6 in (0, 4)]
want.sort(key=lambda p: (p[2], p[0]))
assert [p[0] for p in plays] == [p[0] for p in want], (plays, want)
assert all(abs(a[2] - b[2]) <= 1 for a, b in zip(plays, want)), (plays, want)
app.set_bpm(150)                      # mid-flight: still no duplicate ticks per slot
for _ in range(200):
  app.tick()
  now[0] += 517
plays = [a for n, a in s.calls if n == 'play']
assert len(set(plays)) == len(plays)

# ---- TONE row: notes come out of Pie in the scale, one voice per unison osc ----
app.playing = False
app.key('\x1b[B'); app.key('\x1b[B')         # cursor to row 3
app.key('t')
assert app.rows[2].tone and app.rows[2].built, app.msg
app.rows[2].cells = [0] * 16
app.rows[2].n = 16
app.key('5')                                 # scale note 5 on step 0
assert app.rows[2].text.startswith('-6 ~'), app.rows[2].text     # 5th note, 2 octaves down
hz = app.rows[2].ev[0][0][2]
assert abs(hz - 440.0 * 2 ** ((69 - 24 + 10 - 69) / 12)) < 0.01, hz   # G above A2
w.calls.clear()
app.toggle()
for _ in range(20):
  app.tick()
  now[0] += 517
pitches = [a for n, a in w.calls if n == 'pitch']
assert len(pitches) == chop.UNI and abs(pitches[0][1] - hz / 440) < 1e-6, pitches
assert len([1 for n, a in w.calls if n == 'note_on']) == chop.UNI

# ---- mixer: row volume reaches sampler + synth, comp params reach the compressor ----
app.playing = False
app.key('m')
app.my = 2
s.calls.clear(); w.calls.clear()
app.key('\x1b[D')
assert abs(app.rows[2].vol - 0.75) < 1e-9
assert ('volume', (2, 0.75)) in s.calls and len([1 for n, a in w.calls if n == 'volume']) == chop.UNI
app.key(' ')
assert app.rows[2].vol == 0.0
app.my = len(app.rows) + 1
app.key('\x1b[C')
assert abs(app.cgain - 1.3) < 1e-9 and ('set_params', (1.3, 0.5)) in app.comp.calls
app.key('m')
assert not app.mix

# ---- UI: render one frame with Pillow (skipped if not installed) ----
try:
  from PIL import Image, ImageDraw, ImageChops
except ImportError:
  Image = None
if Image and demo:
  class V:
    def __init__(self):
      self.im = Image.new('1', (400, 240), 0)
      self.d = ImageDraw.Draw(self.im)
      self.c = 1
      self.fw = 7
    def col(self): return 1 if self.c else 0
    def set_draw_color(self, c): self.c = c
    def set_font(self, f): self.fw = {'11': 6, '15': 7, '22': 12, '29': 16}[f[17:19]]
    def get_str_width(self, t): return len(t) * self.fw
    def draw_str(self, x, y, t):
      assert x + len(t) * self.fw <= 400, ('text overflows screen', t)
      self.d.text((x, y - 10), t, fill=1)
    def draw_box(self, x, y, w, h):
      if self.c == 2:
        self.im.paste(ImageChops.logical_xor(self.im.crop((x, y, x + w, y + h)), Image.new('1', (w, h), 1)), (x, y))
      elif w > 0 and h > 0:
        self.d.rectangle((x, y, x + w - 1, y + h - 1), fill=self.col())
    def draw_frame(self, x, y, w, h): self.d.rectangle((x, y, x + w - 1, y + h - 1), outline=1)
    def draw_v_line(self, x, y, h): self.d.line((x, y, x, y + h - 1), fill=1)
    def finished(self): pass
    def get_tp_keys(self): return b'\xff\x20\x46\0\xff\0\0'
  pv = V()
  app2 = chop.Chop(types.SimpleNamespace(v=pv), Rec(), Rec(), Rec(), Rec(), Rec(), Rec())
  app2.load(demo, 2)
  assert len(app2.rows) == 7 and [r.tone for r in app2.rows] == [False] * 6 + [True]
  assert tuple(app2.rows[6].cells) == chop.BASS and app2.rows[6].text.startswith('-10 ~ ~ -10 ~ ~ -8')
  app2.modulate()
  app2.toggle()
  now[0] = app2.t0 + chop.LAT + app2.bar() * 19 // 16
  app2.update(True)
  assert pv.im.getbbox() is not None
  if len(sys.argv) > 1:
    pv.im.resize((800, 480)).save(sys.argv[1])
  app2.key('m')
  app2.my = 8
  pv.d.rectangle((0, 0, 399, 239), fill=0)     # the device clears the frame itself
  app2.update(True)                          # mixer page
  if len(sys.argv) > 1:
    pv.im.resize((800, 480)).save(sys.argv[1].replace('.png', '_mix.png'))
  app2.key('m')
  app2.key('?')
  app2.update(True)                          # help page must fit the screen too

print('ok')
