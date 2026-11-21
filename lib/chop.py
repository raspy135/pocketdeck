# chop.py — every row is a moment of your recording.
#
# Record 3 seconds of anything (beatbox, table taps, a word) or load a WAV.
# Chop finds the separate sounds in it; each becomes one row of a 16-step grid.
# A row is either
#   HIT   plays that moment as recorded (a drum pad), or
#   TONE  freezes that moment into a pitched synth voice: a wavetable cut
#         from just that slice, scanned through as the note sounds. Pitch
#         comes from the grid, time from the scan, so the two are independent
#         — your "ah" becomes a bass line, your snare a metallic lead.
# Every row has its own loop length, so rows drift against each other and
# realign later (polymeter). Rows are real Pie patterns: the grid writes Pie
# mini-notation (shown at the bottom) and Pie's pattern engine and scales
# turn it into notes, so TONE rows always land in key. Nothing is random.
#
#   chop            start with the bundled demo take; press r to record your own
#   chop file.wav   chop an existing WAV instead (mono or stereo, any rate)
#
# Keys:
#   arrows       move the cursor            Enter   run / stop
#   space        toggle the step            0       clear the step
#   1-8          TONE row: play that scale note and put it on the step
#   t            flip the row between HIT and TONE
#   [ ]          shorter / longer row loop (1-16 steps)
#   , .          HIT: pitch -/+ semitone.  TONE: octave down / up
#   p            preview the row's sound    c       clear the row
#   r  record 3 s     - =  tempo     l  filter LFO (off,1,2,3,4,8 per bar)
#   v  echo + reverb on/off          ?  key help     q  quit
#   m  mixer page: per-row volume and the master compressor
#      (up/down select, left/right adjust, space mutes a row / toggles comp)
# Touchpad: X = filter cutoff (TONE rows), Y = scan speed.  Slider = resonance.
#
# WAV files keep their stereo image in HIT rows. The mic is mono and TONE
# rows read the left channel.

import audio
import pdeck
import time
import gc
import math
import struct
from array import array
import esclib as elib
from pie import Pattern, parse_scale

RATE = 24000
REC_SEC = 3
BLOCK = 256       # samples per envelope block (~10.7 ms)
ROWS = 8          # max rows = max slices
STEPS = 16
UNI = 3           # unison oscillators per TONE row. Lower if audio drops out.
DETUNE = (0, 9, -9, 17, -17)   # cents per unison oscillator
NF = 16           # wavetable frames per TONE row
FS = 256          # samples per frame (engine resamples to 256 anyway)
LAT = 1500        # frames the render tick runs ahead of what you hear; tune by eye/ear
LFOS = (0, 1, 2, 3, 4, 8)
SCALE = 'apent_m' # any Pie scale: 'cmaj', 'dm', 'epent_maj', ...
ZERO = bytes(4)
MAX_SLICE = 65535 * 2   # sampler position is 16.16 fixed point: longer never ends
W = 400
GX = 34           # grid origin and cell pitch
GY = 28
CW = 20
RH = 20
DEMO = '/sd/lib/data/chop_demo.wav'   # made by utils/gen_chop_demo.py
MAX_SEC = 8       # only the first seconds of a long WAV are chopped
BASS = (1, 0, 0, 1, 0, 0, 3, 0, 1, 0, 0, 1, 0, 5, 4, 0)   # starter line for the TONE row
HELP = (
  "arrows  move cursor        Enter  run / stop",
  "space   toggle step        0      clear step",
  "1-8     note (TONE row)    p      preview row",
  "t       HIT <-> TONE       c      clear row",
  "[ ]     row loop length    , .    pitch / octave",
  "r       record 3 sec       - =    tempo",
  "l       filter LFO         v      echo+reverb",
  "touchpad X cutoff, Y scan speed; slider resonance",
  "m       mixer: volumes, compressor",
  "?       close help         q      quit",
)


def byteview(a):
  # Zero-copy byte view of an array('h'). MicroPython memoryviews can't cast.
  if isinstance(a, (bytes, bytearray, memoryview)):
    return memoryview(a)
  try:
    return memoryview(a).cast('B')
  except AttributeError:
    import uctypes
    return memoryview(uctypes.bytearray_at(uctypes.addressof(a), len(a) * 2))


def envelope(mv, ch=1):
  # Peak per BLOCK frames (0..128). Reads only the high byte of every 8th
  # frame: plenty for onset detection, fast in plain MicroPython. In stereo
  # the odd step lands on L and R alternately, so hard-panned hits count.
  env = []
  fb = BLOCK * 2 * ch
  for b in range(0, len(mv) - fb + 1, fb):
    p = 0
    for j in range(b + 1, b + fb, 16 * ch + 2 * (ch - 1)):
      h = mv[j]
      if h > 127:
        h = 256 - h
      if h > p:
        p = h
    env.append(p)
  return env


def find_slices(env, maxn=ROWS):
  # Returns [(start, end)] in mono byte offsets (x channels for real offsets)
  # — one per detected hit, in time order.
  # Falls back to equal slices when there are no clear hits (silence, pads,
  # a continuous loop).
  n = len(env)
  top = max(env) if env else 0
  thr = max(3, top // 6)
  on = []
  last = -100
  # 3-block peak hold: a bass hit's block peaks dip at its zero crossings,
  # which would otherwise look like new hits.
  hold = [max(env[max(0, i - 2):i + 1]) for i in range(n)]
  for i in range(n):
    prev = sum(hold[max(0, i - 3):i]) // 3
    if hold[i] >= thr and hold[i] > 2 * prev + 1 and i - last >= 6:
      on.append(i)
      last = i
  if not on:
    return [(n * k // maxn * BLOCK * 2, n * (k + 1) // maxn * BLOCK * 2)
            for k in range(maxn)] if n >= maxn else []
  if len(on) > maxn:
    # too many hits: keep the loudest ones
    on = sorted(sorted(on, key=lambda i: -max(env[i:i + 4]))[:maxn])
  end = n
  while end > on[-1] + 1 and env[end - 1] < thr // 2:
    end -= 1
  end = min(n, end + 2)
  out = []
  for k, i in enumerate(on):
    s = max(0, i - 1) * BLOCK * 2   # back up one block to keep the attack
    e = (max(0, on[k + 1] - 1) if k + 1 < len(on) else end) * BLOCK * 2
    out.append((s, min(e, s + MAX_SLICE)))
  return out


def make_frames(mv, start, end, ch=1, nf=NF):
  # nf single-cycle frames spread across mv[start:end] (left channel). Each
  # starts at a rising zero crossing and has its endpoint drift removed so it
  # loops without a click; the engine does the band-limiting.
  span = end - start - FS * 4 * ch
  if span < 0:
    return []
  out = []
  for f in range(nf):
    off = (start + span * f // max(1, nf - 1)) // (2 * ch) * (2 * ch)
    x = struct.unpack_from('<%dh' % (FS * 2 * ch), mv, off)
    z = 0
    for i in range(FS):
      if x[i * ch] <= 0 < x[(i + 1) * ch]:
        z = i
        break
    a = x[z * ch]
    d = x[(z + FS) * ch] - a
    fr = [x[(z + i) * ch] - a - d * i // FS for i in range(FS)]
    pk = max(max(fr), -min(fr), 256)   # floor: don't blow room noise up to full scale
    out.append(array('h', [s * 24000 // pk for s in fr]))
  return out


def loop_bars(n):
  # Bars until a row of n steps realigns with the 16-step bar.
  a, b = n, STEPS
  while b:
    a, b = b, a % b
  return n // a


def row_pattern(cells, n, tone, slot, octv, ns):
  # The row as Pie mini-notation: 16 steps per cycle, the n-step loop
  # unrolled into as many bars as it takes to realign, alternated with <>.
  # HIT steps are the sampler slot; TONE steps are scale degrees.
  bars = []
  for c in range(loop_bars(n)):
    toks = []
    for i in range(STEPS):
      v = cells[(c * STEPS + i) % n]
      toks.append('~' if not v else str(v - 1 + ns * octv) if tone else str(slot))
    bars.append(' '.join(toks))
  if len(bars) == 1:
    return bars[0]
  return '<' + ' '.join('[%s]' % b for b in bars) + '>'


class Row:
  def __init__(self):
    self.tone = False
    self.n = STEPS
    self.cells = [0] * STEPS   # 0 = rest; HIT: 1; TONE: scale note 1-8
    self.pitch = 0             # HIT: semitones.  TONE: octaves
    self.vol = 0.8             # mixer level, 0..1
    self.note = 1              # last note entered on this row
    self.built = False         # wavetable loaded for this row
    self.text = ''             # Pie pattern string
    self.ev = [[]]             # Pie events per bar of the loop


class Chop:
  def __init__(self, vs, s, w, flt, echo, rev, comp):
    self.vs = vs
    self.v = vs.v
    self.s = s
    self.w = w
    self.flt = flt
    self.echo = echo
    self.rev = rev
    self.comp = comp
    self.mix = False      # mixer page showing
    self.my = 0           # mixer cursor: rows, then comp on/off, gain, reduction
    self.comp_on = True
    self.cgain = 1.2
    self.cred = 0.5
    self.buf = None
    self.src = None       # keeps a loaded WAV's array alive under self.buf
    self.ch = 1
    self.parts = []       # memoryviews handed to the sampler
    self.slices = []
    self.rows = []
    self.cols = None
    self.ns = len(parse_scale(SCALE)[1])
    self.det = [2 ** (c / 1200) for c in DETUNE[:UNI]]
    self.cx = 0
    self.cy = 0
    self.playing = False
    self.bpm = 110
    self.t0 = 0           # tick of bar 0
    self.horizon = 0      # every event before this tick is already scheduled
    self.fx = False
    self.lfo = 0
    self.cut = 0.7        # 0..1 -> 80..8000 Hz
    self.q = 2.0
    self.scan = 8         # 0..16 -> scan time x1/4 .. x4 of the slice's length
    self.last_f = None
    self.help = False
    self.msg = ''
    self.rec_t0 = None
    self.dirty = True
    self.rt = 100         # audio render speed, % of real time (below ~98 = overloaded)
    self.rt_ms = time.ticks_ms()
    self.rt_tk = audio.get_current_tick()
    for i in range(ROWS * UNI):
      w.frequency(i, 440.0)
      w.set_adsr(i, 5, 200, 0.6, 180)
      w.volume(i, 0.8 * 0.6 / UNI)
    flt.set_type("lpf")
    # Must set params (no transition) BEFORE enabling: an enabled filter that
    # never got params runs with cutoff 0 / q 0, its state goes NaN for good,
    # and the echo turns that into a periodic click.
    flt.set_params(2000, self.q)
    flt.active(True)
    echo.set_type(audio.ECHO_PINGPONG)
    rev.set_params(0.6, 0.5, 10.0, 0.22)   # no transition_ms: reverb ramps never stop
    self.set_fx(False)   # effects start off; v turns them on
    comp.set_params(self.cgain, self.cred)
    comp.active(self.comp_on)

  # ---- sound ---------------------------------------------------------------

  def bar(self):
    return RATE * 240 // self.bpm

  def set_fx(self, on):
    self.fx = on
    self.echo.set_params(min(1000, 45000 // self.bpm), 0.35)   # dotted 8th
    self.echo.active(on)
    self.rev.active(on)

  def quiet(self):
    # stop_all() force-runs every queued hit; mute around it so they don't sound.
    for i in range(ROWS):
      self.s.volume(i, 0.0)
    self.s.stop_all()
    for i in range(ROWS):
      self.s.volume(i, self.rows[i].vol if i < len(self.rows) else 1.0)
    self.w.stop_all()

  def apply_vol(self, i):
    v = self.rows[i].vol
    self.s.volume(i, v)
    for u in range(UNI):
      self.w.volume(i * UNI + u, v * 0.6 / UNI)

  def rebuild(self, i):
    # Grid row -> Pie pattern -> events for each bar of the row's loop.
    r = self.rows[i]
    r.text = row_pattern(r.cells, r.n, r.tone, i, r.pitch, self.ns)
    pat = Pattern.create(r.text)
    if r.tone:
      pat.scale(SCALE)
    r.ev = [pat.get_events(c) for c in range(loop_bars(r.n))]
    self.dirty = True

  def scan_ms(self, i):
    s, e = self.slices[i]
    ms = (e - s) * 500 // (RATE * self.ch)        # the slice's own length
    return max(10, min(8000, int(ms * 4 ** (self.scan / 8 - 1))))

  def set_tone(self, i, on):
    r = self.rows[i]
    if on and not r.built:
      s, e = self.slices[i]
      frames = make_frames(self.buf, s, e, self.ch)
      if not frames:
        self.msg = 'row %d is too short for a tone' % (i + 1)
        return
      # Mutes the synth for a few hundred ms while the engine builds
      # band-limited tables, so it is only done when a row first turns TONE.
      o = i * UNI
      self.w.set_wavetable(o, frames)
      ms = self.scan_ms(i)
      for u in range(UNI):
        if u:
          self.w.copy_table(o + u, o)
        # each note sweeps the wavetable from the start of the moment to its end
        self.w.morph_start(o + u, 0.0)
        self.w.morph(o + u, 1.0)
        self.w.morph_adsr(o + u, ms, 1, 1.0, 200)
        self.w.morph_adsr_enable(o + u, True)
      r.built = True
    r.tone = on
    r.pitch = -2 if on else 0
    r.cells = [(r.note if on else 1) if c else 0 for c in r.cells]
    if not on:
      self.s.speed(i, 1.0)
    self.rebuild(i)

  def load(self, mv, ch=1):
    self.playing = False
    self.quiet()
    env = envelope(mv, ch)
    self.buf = mv
    self.ch = ch
    self.slices = [(s * ch, e * ch) for s, e in find_slices(env)]
    self.parts = [mv[s:e] for s, e in self.slices]
    for i in range(ROWS):
      if i < len(self.parts):
        self.s.set_sample(i, self.parts[i], ch)
        self.s.speed(i, 1.0)
      else:
        self.s.set_sample(i, ZERO, 1)    # drop the sampler's ref to the old take
    n = len(self.parts)
    self.rows = [Row() for i in range(n)]
    self.cx = self.cy = self.my = 0
    for i in range(n):
      self.apply_vol(i)
    # Starter groove: first three moments as kick / snare / hat (the hat on a
    # 6-step loop, so it drifts against the bar), and the longest remaining
    # moment as a TONE bass line.
    for i, (steps, length) in enumerate((((0, 4, 8, 12), 16), ((4, 12), 16), ((0, 2, 3, 5), 6))):
      if i < n:
        self.rows[i].n = length
        for st in steps:
          self.rows[i].cells[st] = 1
    for i in range(n):
      self.rebuild(i)
    if n > 3:
      j = max(range(3, n), key=lambda i: self.slices[i][1] - self.slices[i][0])
      self.set_tone(j, True)
      if self.rows[j].tone:
        self.rows[j].cells = list(BASS)
        self.rebuild(j)
    top = max(env) if env else 1
    ne = len(env)
    self.cols = bytes(env[x * ne // 200] * 12 // max(top, 1) for x in range(200)) if ne else None
    self.dirty = True
    # goes to the REPL screen (screen 1), for debugging
    print("chop: %d bytes, %d ch, %d slices, peak %d/128" % (len(mv), ch, n, top))

  def load_wav(self, filename):
    from wav_loader import load_wav
    data, ch = load_wav(filename, RATE)
    if ch > 2:
      data, ch = load_wav(filename, RATE, 2)
    if data:
      self.src = data
      self.load(byteview(data)[:RATE * MAX_SEC * 2 * ch], ch)

  def record(self):
    self.playing = False
    self.quiet()
    for i in range(ROWS):
      self.s.set_sample(i, ZERO, 1)
    self.parts = []
    self.slices = []
    self.rows = []
    self.buf = None
    self.src = None
    self.cols = None
    gc.collect()
    buf = memoryview(bytearray(RATE * REC_SEC * 2))
    half = len(buf) // 2
    # The two stream buffers are the two halves of one take: no copying.
    audio.stream_setup(1, RATE, 1, RATE * REC_SEC)
    audio.stream_setdata(1, 0, buf[:half])
    audio.stream_setdata(1, 1, buf[half:])
    self.rec_t0 = time.ticks_ms()
    audio.stream_record(True)
    while audio.stream_record() and time.ticks_diff(time.ticks_ms(), self.rec_t0) < REC_SEC * 1000 + 300:
      pdeck.delay_tick(5)
    audio.stream_record(False)
    self.rec_t0 = None
    self.load(buf)

  def set_bpm(self, bpm):
    old = self.bar()
    self.bpm = max(40, min(240, bpm))
    # keep the bar phase at the horizon, so nothing is scheduled twice or lost
    self.t0 = self.horizon - (self.horizon - self.t0) * self.bar() // old
    self.set_fx(self.fx)

  def toggle(self):
    # Stopping just stops scheduling; the <=125 ms already queued plays out.
    self.playing = not self.playing
    if self.playing:
      self.t0 = self.horizon = audio.get_current_tick() + RATE // 20

  def fire(self, i, v, t, dur):
    if not self.rows[i].tone:
      self.s.play(i, False, t)
      return
    if isinstance(v, tuple):
      v = v[0]
    w = self.w
    for u in range(UNI):
      o = i * UNI + u
      w.pitch(o, v / 440.0 * self.det[u], 0, t)
      w.note_on(o, t)
      w.note_off(o, t + dur)

  def tick(self):
    # Schedule ~125 ms ahead with sample-accurate ticks, so edits and stop
    # are heard at once. Everything before self.horizon has been scheduled
    # exactly once; a Pie event at cycle offset o of bar c sits at
    # t0 + c*bar + o*bar.
    if not self.playing:
      return
    now = audio.get_current_tick()
    bar = self.bar()
    t0 = self.t0
    h0 = max(self.horizon, now + 600)     # >=1 render block ahead; skips what we missed
    h1 = now + RATE // 8
    if h1 <= h0:
      return
    for c in range((h0 - t0) // bar, (h1 - 1 - t0) // bar + 1):
      base = t0 + c * bar
      for i in range(len(self.rows)):
        ev = self.rows[i].ev
        for o, d, v in ev[c % len(ev)]:
          t = base + int(o * bar)
          if h0 <= t < h1:
            self.fire(i, v, t, int(d * bar))
    self.horizon = h1

  def modulate(self):
    # Touchpad + LFO -> filter and scan. Only talks to the engine on change.
    tp = self.v.get_tp_keys()
    if tp[1] != 0xFF and tp[2] != 0xFF:
      self.cut = tp[2] / 100
      sc = 16 - tp[1] // 5
      if sc != self.scan:
        self.scan = sc
        for i in range(len(self.rows)):
          if self.rows[i].built:
            ms = self.scan_ms(i)
            for u in range(UNI):
              self.w.morph_adsr(i * UNI + u, ms, 1, 1.0, 200)
      self.dirty = True
    if tp[0] != 0xFF:
      self.q = 0.7 + tp[0] * 7 / 40
      self.dirty = True
    c = self.cut
    if self.lfo and self.playing:
      ph = (audio.get_current_tick() - self.t0) * LFOS[self.lfo] / self.bar()
      c += 0.25 * math.sin(6.2832 * ph)
    hz = int(80 * 100 ** max(0.0, min(1.0, c)))
    f = (hz, self.q)
    if f != self.last_f:
      self.last_f = f
      self.flt.set_params(hz, self.q, 25)

  def meter(self):
    # The render tick advances with the audio task; if it runs slower than
    # the wall clock the engine is overloaded and the output breaks up.
    ms = time.ticks_diff(time.ticks_ms(), self.rt_ms)
    if ms >= 1000:
      tk = audio.get_current_tick()
      self.rt = (tk - self.rt_tk) * 100000 // (RATE * ms)
      self.rt_ms = time.ticks_add(self.rt_ms, ms)
      self.rt_tk = tk
      self.dirty = True

  # ---- keys ----------------------------------------------------------------

  def preview(self, i):
    r = self.rows[i]
    if not r.tone:
      self.s.play(i)
      return
    root, iv = parse_scale(SCALE)
    d = r.note - 1 + self.ns * r.pitch
    midi = root + (d // self.ns) * 12 + iv[d % self.ns]
    self.fire(i, 440.0 * 2 ** ((midi - 69) / 12), audio.get_current_tick() + 600, RATE // 4)

  def mix_key(self, k):
    n = len(self.rows)
    if k == '\x1b[A' or k == '\x1b[B':
      self.my = (self.my + (1 if k[2] == 'B' else -1)) % (n + 3)
    elif k == '\x1b[D' or k == '\x1b[C' or k == ' ':
      d = 0 if k == ' ' else 1 if k[2] == 'C' else -1
      j = self.my - n
      if j < 0:
        r = self.rows[self.my]
        if d:
          r.vol = max(0.0, min(1.0, round(r.vol * 20 + d) / 20))
        else:
          r.vol = 0.0 if r.vol else 0.8      # space = mute / unmute
        self.apply_vol(self.my)
        return
      if j == 0:
        self.comp_on = not self.comp_on
      elif j == 1:
        self.cgain = max(0.5, min(4.0, round(self.cgain * 10 + d) / 10))
      else:
        self.cred = max(0.0, min(2.0, round(self.cred * 10 + d) / 10))
      self.comp.set_params(self.cgain, self.cred)
      self.comp.active(self.comp_on)
    elif k == 'p' and self.my < n:
      self.preview(self.my)

  def key(self, k):
    self.msg = ''
    self.dirty = True
    if k == '?':
      self.help = not self.help
    elif k == 'm':
      self.mix = not self.mix
    elif k == '\r' or k == '\n':
      self.toggle()
    elif k == 'r':
      self.record()
    elif k == 'v':
      self.set_fx(not self.fx)
    elif k == 'l':
      self.lfo = (self.lfo + 1) % len(LFOS)
    elif k == '-':
      self.set_bpm(self.bpm - 5)
    elif k == '=' or k == '+':
      self.set_bpm(self.bpm + 5)
    if self.mix:
      self.mix_key(k)
      return
    if not self.rows:
      return
    i = self.cy
    r = self.rows[i]
    if k == '\x1b[A' or k == '\x1b[B':
      self.cy = (i + (1 if k[2] == 'B' else -1)) % len(self.rows)
    elif k == '\x1b[D' or k == '\x1b[C':
      self.cx = (self.cx + (1 if k[2] == 'C' else -1)) % r.n
    elif k == ' ':
      r.cells[self.cx] = 0 if r.cells[self.cx] else (r.note if r.tone else 1)
    elif k == '0':
      r.cells[self.cx] = 0
    elif k in '12345678':
      if r.tone:
        r.note = int(k)
        self.preview(i)
      r.cells[self.cx] = r.note if r.tone else 1
    elif k == 't':
      self.set_tone(i, not r.tone)
    elif k == '[' or k == ']':
      r.n = max(1, min(STEPS, r.n + (1 if k == ']' else -1)))
    elif k == ',' or k == '.':
      d = 1 if k == '.' else -1
      if r.tone:
        r.pitch = max(-4, min(2, r.pitch + d))
      else:
        r.pitch = max(-24, min(24, r.pitch + d))
        self.s.speed(i, 2 ** (r.pitch / 12))
    elif k == 'c':
      r.cells = [0] * STEPS
    elif k == 'p':
      self.preview(i)
    if k in ' 012345678[],.c':
      self.rebuild(i)
    self.cx = min(self.cx, self.rows[self.cy].n - 1)

  def run(self):
    while True:
      self.tick()
      self.modulate()
      self.meter()
      n, data = self.v.read_nb(16)
      i = 0
      while i < n:
        if data[i] == '\x1b' and data[i + 1:i + 2] == '[':
          k = data[i:i + 3]
        else:
          k = data[i]
        i += len(k)
        if k == 'q':
          return
        self.key(k)
      pdeck.delay_tick(2)

  # ---- drawing -------------------------------------------------------------

  def update(self, e):
    v = self.v
    now_ms = time.ticks_ms()
    if not (e or self.dirty or self.playing or self.rec_t0):
      v.finished()
      return
    self.dirty = False

    v.set_draw_color(1)
    v.set_font("u8g2_font_profont22_mf")
    v.draw_str(4, 18, "CHOP")
    v.set_font("u8g2_font_profont15_mf")
    st = "%s %dbpm%s%s %d%%" % (">" if self.playing else "#", self.bpm,
                                " FX" if self.fx else "",
                                " L%d" % LFOS[self.lfo] if self.lfo else "", self.rt)
    v.draw_str(W - 4 - v.get_str_width(st), 16, st)

    if self.help:
      y = 44
      for t in HELP:
        v.draw_str(8, y, t)
        y += 20
      v.finished()
      return

    if self.mix:
      v.set_font("u8g2_font_profont11_mf")
      v.draw_str(62, 15, "MIXER ud:select lr:adjust")
      v.set_font("u8g2_font_profont15_mf")
      n = len(self.rows)
      items = [("%s%d" % ('T' if r.tone else 'h', i + 1), r.vol, "%d" % (r.vol * 100 + 0.5))
               for i, r in enumerate(self.rows)]
      items += [("comp", -1, "on" if self.comp_on else "off"),
                ("gain", self.cgain / 4, "%.1f" % self.cgain),
                ("reduce", self.cred / 2, "%.1f" % self.cred)]
      for j in range(len(items)):
        name, frac, val = items[j]
        y = 46 + j * 18 + (10 if j >= n else 0)
        v.draw_str(4, y, name)
        if frac >= 0:
          v.draw_frame(56, y - 10, 290, 10)
          v.draw_box(56, y - 10, int(290 * frac), 10)
        v.draw_str(354, y, val)
        if j == self.my:
          v.set_draw_color(2)
          v.draw_box(0, y - 13, W, 17)
          v.set_draw_color(1)
      v.finished()
      return

    # filter cutoff bar, resonance, scan speed
    v.draw_frame(62, 8, 60, 7)
    v.draw_box(62, 8, int(60 * self.cut), 7)
    v.set_font("u8g2_font_profont11_mf")
    v.draw_str(128, 15, "Q%.1f x%.2g" % (self.q, 4 ** (self.scan / 8 - 1)))
    v.set_font("u8g2_font_profont15_mf")

    # global step being heard right now
    g = -1
    if self.playing:
      d = audio.get_current_tick() - LAT - self.t0
      if d >= 0:
        g = d * STEPS // self.bar()

    for i in range(0, STEPS, 4):
      v.draw_box(GX + i * CW, GY - 4, 18, 2)
    for ri in range(len(self.rows)):
      r = self.rows[ri]
      y = GY + ri * RH
      v.draw_str(4, y + 13, "%s%d" % ('T' if r.tone else 'h', ri + 1))
      v.draw_str(GX + STEPS * CW + 4, y + 13, "%d%+d" % (r.n, r.pitch))
      cur = g % r.n if g >= 0 else -1     # each row has its own playhead
      for i in range(r.n):
        x = GX + i * CW
        c = r.cells[i]
        if not c:
          v.draw_box(x + 8, y + 7, 2, 2)
        elif r.tone:
          v.draw_frame(x + 1, y + 1, 16, 14)
          v.draw_str(x + 6, y + 13, str(c))
        else:
          v.draw_box(x + 2, y + 2, 14, 12)
        if i == cur:
          v.set_draw_color(2)
          v.draw_box(x, y, 18, 16)
          v.set_draw_color(1)
      if ri == self.cy:
        v.draw_frame(GX + self.cx * CW - 1, y - 1, 20, 18)

    rec_t0 = self.rec_t0
    if rec_t0:
      v.draw_str(4, 206, "* REC")
      p = min(340, time.ticks_diff(now_ms, rec_t0) * 340 // (REC_SEC * 1000))
      v.draw_frame(56, 196, 340, 10)
      v.draw_box(56, 196, p, 10)
    elif not self.cols:
      v.draw_str(120, 120, "r: record 3 seconds")
    else:
      # the take, with the cursor row's moment highlighted
      cols = self.cols
      for x in range(200):
        h = cols[x]
        v.draw_v_line(x * 2, 206 - h, 2 * h + 1)
      nb = len(self.buf)
      for ri in range(len(self.slices)):
        s, en = self.slices[ri]
        x0 = s * W // nb
        v.draw_v_line(x0, 193, 27)
        if ri == self.cy:
          v.set_draw_color(2)
          v.draw_box(x0, 193, max(2, (en - s) * W // nb), 27)
          v.set_draw_color(1)
      v.set_font("u8g2_font_profont11_mf")
      t = self.msg or "pie: " + self.rows[self.cy].text
      v.draw_str(4, 236, t if len(t) <= 64 else t[:62] + "..")
    v.finished()


def main(vs, args):
  el = elib.esclib()
  v = vs.v
  audio.power(True)
  audio.sample_rate(RATE)
  with audio.router() as master, audio.router() as syn, \
       audio.sampler(ROWS) as s, audio.wavetable(ROWS * UNI) as w, \
       audio.filter() as flt, audio.echo(1000) as echo, audio.reverb() as rev, \
       audio.compressor() as comp:
    # sources first, then effects in chain order; the filter is on the synth only
    syn.add(w)
    syn.add(flt)
    master.add(s)
    master.add(syn)
    master.add(echo)
    master.add(rev)
    master.add(comp)      # last, so it levels (and soft-clips) the whole mix
    app = Chop(vs, s, w, flt, echo, rev, comp)
    try:
      app.load_wav(args[1] if len(args) > 1 else DEMO)
    except OSError:
      if len(args) > 1:
        print("chop: cannot open", args[1], file=vs)
        return
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))
    v.callback(app.update)
    try:
      app.run()
    finally:
      audio.stream_record(False)
      app.quiet()
      v.callback(None)
      v.print(el.display_mode(True))
