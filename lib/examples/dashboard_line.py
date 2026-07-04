# dashboard_line.py — Flat-design LINE / AREA trend dashboard (400x240 mono).
#
# What this example teaches:
#   * A line chart with a DITHERED AREA fill under the curve — the classic way to
#     add "weight" on a 1-bit screen without gradients. The line itself is solid.
#   * journal.py-style MORPH animation: every point rises from a flat midline to
#     its real value on a shared ease-out timeline, so the curve "unfolds" from a
#     line into the data when it opens or switches.
#   * A big current-value read-out plus a delta chip (up/down vs. previous),
#     both positioned with get_utf8_width so they right-align cleanly.
#   * Dotted gridlines + min/max axis labels that are measured, never guessed.
#
# Operation:  Left / Right = switch metric,  q = quit.
#
# Copy to /sd/py/ and run:  r dashboard_line

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


# ---- dummy data — a series of samples per metric ------------------------------

METRICS = (
  ('CPU load', '%',
   (22, 28, 25, 41, 63, 58, 47, 52, 70, 88, 74, 61, 55, 60, 72, 90),
   lambda x: '%d' % x),
  ('Temp', 'C',
   (19.5, 19.8, 20.1, 20.0, 20.6, 21.4, 22.0, 22.3, 21.8, 21.1, 20.7, 20.9,
    21.5, 22.6, 23.1, 22.8),
   lambda x: '%.1f' % x),
  ('Battery', '%',
   (100, 98, 95, 93, 90, 86, 83, 79, 74, 70, 65, 61, 58, 54, 49, 45),
   lambda x: '%d' % x),
)


class LineDashboard:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.metric = 0
    self.dirty = True

    self.seq = anm.anm_sequencer()
    self.morph = anm.anm_object(450, {'m': [anm.ease_out, 0.0, 1.0]})
    self.seq.register('morph', self.morph)

  # plot rectangle
  PX = 12
  PY = 28
  PW = W - 12 - 12
  PH = 150            # plot height; bottom = PY + PH

  def _animating(self):
    return self.morph.get_time() < 1.0

  def replay(self):
    self.morph.seek(0.0)
    self.dirty = True

  # Map samples to screen coords, morphing each point's y from a flat midline
  # (m=0) to its real value (m=1) — journal.py's "unfold from a line" style.
  def _points(self, values, vmin, vmax, m):
    n = len(values)
    span = (vmax - vmin) or 1.0
    bottom = self.PY + self.PH
    mid = self.PY + self.PH // 2          # the flat line we start from
    pts = []
    for i, val in enumerate(values):
      x = self.PX + int(self.PW * i / (n - 1)) if n > 1 else self.PX
      y = bottom - int(self.PH * (val - vmin) / span)
      pts.append((x, int(mid + (y - mid) * m)))
    return pts

  # ---- drawing --------------------------------------------------------------

  def draw_header(self):
    v = self.v
    title, unit, values, fmt = METRICS[self.metric]
    v.set_draw_color(1)
    v.draw_box(0, 0, W, 20)
    v.set_draw_color(0)
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(6, 15, title)
    rng = '%s..%s %s' % (fmt(min(values)), fmt(max(values)), unit)
    v.draw_str(right_x(v, W - 6, rng), 15, rng)
    v.set_draw_color(1)

  def draw_readout(self):
    # Big current value on the left, delta chip beside it.
    v = self.v
    title, unit, values, fmt = METRICS[self.metric]
    cur = values[-1]
    prev = values[-2] if len(values) > 1 else cur
    delta = cur - prev

    v.set_font('u8g2_font_profont29_mf')
    v.set_draw_color(1)
    cur_txt = fmt(cur) + unit
    v.draw_str(6, 230, cur_txt)
    cur_w = v.get_utf8_width(cur_txt)

    # delta chip: filled rounded box with a signed amount, right after the value.
    # Plain ASCII (+/-) always renders — don't gamble on exotic glyphs.
    v.set_font('u8g2_font_profont15_mf')
    chip = ('+' if delta >= 0 else '-') + fmt(abs(delta))
    cw = v.get_utf8_width(chip) + 10
    cx = 6 + cur_w + 12
    cy = 205
    v.set_dither(16)
    v.draw_rbox(cx, cy, cw, 18, 4)
    v.set_draw_color(0)
    v.draw_str(cx + 5, cy + 14, chip)
    v.set_draw_color(1)

  def draw_chart(self):
    v = self.v
    title, unit, values, fmt = METRICS[self.metric]
    vmin = min(values)
    vmax = max(values)
    m = clamp01(self.morph.m)
    pts = self._points(values, vmin, vmax, m)   # y morphs flat -> data
    bottom = self.PY + self.PH

    # frame + dotted gridlines (flat, quiet)
    v.set_draw_color(1)
    v.draw_frame(self.PX, self.PY, self.PW, self.PH)
    v.set_dither(4)
    for g in range(1, 4):
      gy = self.PY + self.PH * g // 4
      x = self.PX + 2
      while x < self.PX + self.PW - 2:
        v.draw_pixel(x, gy)
        x += 5
    v.set_dither(16)

    # dithered area fill under the curve, column by column
    v.set_dither(6)
    for i in range(len(pts) - 1):
      x0, y0 = pts[i]
      x1, y1 = pts[i + 1]
      if x1 <= x0:
        continue
      for x in range(x0, x1 + 1):
        y = int(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
        v.draw_v_line(x, y, bottom - y)
    v.set_dither(16)

    # the solid line on top
    for i in range(len(pts) - 1):
      v.draw_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])

    # marker dot on the latest sample
    v.draw_disc(pts[-1][0], pts[-1][1], 2, 15)

    # axis labels last, on top of the fill, each on a punched background box so
    # they stay legible over the dither (a flat, clean trick).
    v.set_font('u8g2_font_profont15_mf')
    self._boxed_label(self.PX + 3, self.PY + 13, fmt(vmax))
    self._boxed_label(self.PX + 3, bottom - 14, fmt(vmin))

  def _boxed_label(self, x, y, text):
    # y is the text baseline. Clear a 15px-tall box behind the glyphs, then draw.
    v = self.v
    w = v.get_utf8_width(text)
    v.set_draw_color(0)
    v.draw_box(x - 1, y - 12, w + 2, 15)
    v.set_draw_color(1)
    v.draw_str(x, y, text)

  def draw_pager(self):
    v = self.v
    n = len(METRICS)
    gap = 12
    cx = W - 10 - (n - 1) * gap
    for i in range(n):
      x = cx + i * gap
      if i == self.metric:
        v.draw_disc(x, 226, 3,15)
      else:
        v.draw_circle(x, 226, 3,15)

  def draw(self):
    v = self.v
    v.clear_buffer()
    self.draw_header()
    self.draw_chart()
    self.draw_readout()
    self.draw_pager()
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
      elif k == b'\x1b[C':
        self.metric = (self.metric + 1) % len(METRICS)
        self.replay()
      elif k == b'\x1b[D':
        self.metric = (self.metric - 1) % len(METRICS)
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

  app = LineDashboard(vs)
  v.callback(app.update)
  try:
    app.key_loop()
  finally:
    v.callback(None)
    v.print(el.display_mode(True))
