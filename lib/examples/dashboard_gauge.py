# dashboard_gauge.py — Flat-design RADIAL GAUGE dashboard (400x240 mono).
#
# What this example teaches:
#   * FAST filled gauge bands: precompute each ring once as a fan of quad polygons
#     into an array('h'), then every frame just draw_polygon() the slices — no
#     per-frame sin/cos. This is the same trick analog_clock uses for its timer
#     disc; draw_polygon is a batched C call, far cheaper than hundreds of
#     draw_line/draw_arc calls. Angles are DEGREES, 0 = 3 o'clock, CLOCKWISE
#     (screen y grows down); the 270-deg gauge leaves a gap at the bottom.
#   * A gauge that actually shows its value: the solid arc fills to val% (not just
#     "however far the animation got"), while set_dither() keeps the unfilled
#     track quiet so track + value read as one flat component.
#   * Spring animation on the main sweep, ease-out on the rings, from one shared
#     0..1 timeline. Perfectly centered read-outs via get_utf8_width.
#
# Operation:  Left / Right = switch scenario,  r = refresh (replay),  q = quit.
#
# Copy to /sd/py/ and run:  r dashboard_gauge

import math
import array
import time
import anm
import esclib as elib

W = 400
H = 240


def center_x(v, x, w, text):
  return x + (w - v.get_utf8_width(text)) // 2

def right_x(v, right_edge, text):
  return right_edge - v.get_utf8_width(text)

def clamp01(t):
  return 0.0 if t < 0 else (1.0 if t > 1 else t)


# ---- dummy data — each scenario has a main % and two secondary rings ----------

SCENARIOS = (
  ('Now',  78, (('Disk', 54), ('Net', 31))),
  ('Peak', 96, (('Disk', 88), ('Net', 72))),
  ('Idle', 12, (('Disk', 41), ('Net',  6))),
)

MAIN_LABEL = 'CPU'


class GaugeDashboard:
  # gauge geometry (centers, radii). Fixed, so the polygons are built once.
  MAIN = (108, 138, 74, 65)     # cx, cy, r_out, r_in ; 270-deg sweep
  RINGS = ((300, 82, 40, 33),   # cx, cy, r_out, r_in ; full 360-deg
           (300, 174, 40, 33))
  SEGS = 48                     # facets per band — more = smoother, slower

  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.scenario = 0
    self.dirty = True

    self.seq = anm.anm_sequencer()
    self.t = anm.anm_object(850, {'t': [anm.linear, 0.0, 1.0]})
    self.seq.register('t', self.t)

    # Precompute the vertex fans ONCE (no trig per frame). The main gauge sweeps
    # 135 -> 405 deg; each ring sweeps 270 -> 630 so the value grows clockwise
    # from 12 o'clock. Drawing the first k of SEGS quads gives a partial fill.
    cx, cy, ro, ri = self.MAIN
    self.main_band = self._build_band(cx, cy, ro, ri, 135, 405, self.SEGS)
    self.ring_bands = [self._build_band(rx, ry, rro, rri, 270, 630, self.SEGS)
                       for (rx, ry, rro, rri) in self.RINGS]

  def _animating(self):
    return self.t.get_time() < 1.0

  def replay(self):
    self.t.seek(0.0)
    self.dirty = True

  # ---- ring primitives ------------------------------------------------------

  def _build_band(self, cx, cy, r_out, r_in, a0, a1, segs):
    # Fan of `segs` trapezoid quads between r_in and r_out, a0..a1 (degrees,
    # clockwise, 0 = 3 o'clock). Stored flat as [x1..x4, y1..y4] per quad — the
    # order draw_polygon() wants. Returned as a memoryview for cheap slicing.
    arr = array.array('h', bytearray(segs * 8 * 2))
    da = a1 - a0
    for i in range(segs):
      t0 = math.radians(a0 + da * i / segs)
      t1 = math.radians(a0 + da * (i + 1) / segs)
      c0 = math.cos(t0); s0 = math.sin(t0)
      c1 = math.cos(t1); s1 = math.sin(t1)
      o = i * 8
      arr[o + 0] = int(cx + r_out * c0)   # outer @ a0
      arr[o + 1] = int(cx + r_out * c1)   # outer @ a1
      arr[o + 2] = int(cx + r_in * c1)    # inner @ a1
      arr[o + 3] = int(cx + r_in * c0)    # inner @ a0
      arr[o + 4] = int(cy + r_out * s0)
      arr[o + 5] = int(cy + r_out * s1)
      arr[o + 6] = int(cy + r_in * s1)
      arr[o + 7] = int(cy + r_in * s0)
    return memoryview(arr)

  def _draw_band(self, band, frac):
    # Quiet full track, then the solid value fill over its first `frac` (0..1).
    v = self.v
    segs = len(band) // 8
    v.set_dither(4)
    for i in range(segs):
      v.draw_polygon(band[i * 8:(i + 1) * 8])
    k = int(segs * clamp01(frac) + 0.0001)
    if k > 0:
      v.set_dither(16)
      for i in range(k):
        v.draw_polygon(band[i * 8:(i + 1) * 8])
    v.set_dither(16)

  # ---- drawing --------------------------------------------------------------

  def draw_header(self):
    v = self.v
    name = SCENARIOS[self.scenario][0]
    v.set_draw_color(1)
    v.draw_box(0, 0, W, 20)
    v.set_draw_color(0)
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(6, 15, 'System')
    tag = 'scenario: ' + name
    v.draw_str(right_x(v, W - 6, tag), 15, tag)
    v.set_draw_color(1)

  def draw_main_gauge(self, prog):
    # prog is the eased 0..1 animation; the arc fills to (main_val/100)*prog so
    # it settles at the real value, not a full ring.
    v = self.v
    name, main_val, subs = SCENARIOS[self.scenario]
    cx, cy = self.MAIN[0], self.MAIN[1]
    self._draw_band(self.main_band, (main_val / 100.0) * prog)

    # centered percentage on the hub
    v.set_draw_color(1)
    pct = '%d' % int(round(main_val * prog))
    v.set_font('u8g2_font_profont29_mf')
    pw = v.get_utf8_width(pct)
    v.draw_str(cx - pw // 2, cy + 6, pct)
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(cx - pw // 2 + pw + 2, cy + 6, '%')
    lbl_w = v.get_utf8_width(MAIN_LABEL)
    v.draw_str(cx - lbl_w // 2, cy + 22, MAIN_LABEL)

  def draw_side_rings(self, prog):
    v = self.v
    name, main_val, subs = SCENARIOS[self.scenario]
    for i, (lbl, val) in enumerate(subs):
      cx, cy = self.RINGS[i][0], self.RINGS[i][1]
      self._draw_band(self.ring_bands[i], (val / 100.0) * prog)
      # value + caption both stacked inside the ring, centered (like the main hub)
      v.set_draw_color(1)
      v.set_font('u8g2_font_profont15_mf')
      pct = '%d%%' % int(round(val * prog))
      pw = v.get_utf8_width(pct)
      v.draw_str(cx - pw // 2, cy, pct)
      lw = v.get_utf8_width(lbl)
      v.draw_str(cx - lw // 2, cy + 14, lbl)

  def draw_hint(self):
    v = self.v
    v.set_draw_color(1)
    v.set_font('u8g2_font_profont15_mf')
    hint = 'L/R scenario  r refresh  q quit'
    v.draw_str(center_x(v, 0, W, hint), 236, hint)

  def draw(self):
    v = self.v
    v.clear_buffer()
    # main gauge springs past target and settles; rings ease out smoothly
    tval = clamp01(self.t.t)
    main_prog = clamp01(anm.spring(tval))
    ring_prog = anm.ease_out(tval)
    self.draw_header()
    self.draw_main_gauge(main_prog)
    self.draw_side_rings(ring_prog)
    self.draw_hint()
    v.finished()

  # ---- lifecycle ------------------------------------------------------------

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return
    self.seq.update(time.ticks_ms())
    if e or self.dirty or self._animating():
      self.draw()
      self.dirty = False
    else:
      self.v.finished()

  def key_loop(self):
    while True:
      k = self._read_key()
      if k == b'q':
        break
      elif k == b'r':
        self.replay()
      elif k == b'\x1b[C':
        self.scenario = (self.scenario + 1) % len(SCENARIOS)
        self.replay()
      elif k == b'\x1b[D':
        self.scenario = (self.scenario - 1) % len(SCENARIOS)
        self.replay()

  def _read_key(self):
    k = self.vs.read(1).encode('ascii')
    if k != b'\x1b':
      return k
    seq = [k, self.vs.read(1).encode('ascii')]
    if seq[-1] == b'[':
      seq.append(self.vs.read(1).encode('ascii'))
    return b''.join(seq)


def main(vs, args):
  v = vs.v
  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  app = GaugeDashboard(vs)
  v.callback(app.update)
  try:
    app.key_loop()
  finally:
    v.callback(None)
    v.print(el.display_mode(True))
