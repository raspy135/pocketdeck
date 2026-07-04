# dashboard_bars.py — Flat-design BAR CHART dashboard for Pocket deck
#   * Flat monochrome layout: one solid inverted header bar, thin rules, dither
#     fills instead of gradients. No drop shadows, no 3D — the screen is 1-bit.
#   * anm staggered "grow" entrance: bars rise from the baseline one after
#     another with an ease-out curve. Re-plays when you switch datasets.
#   * TEXT THAT FITS: every label is placed with get_utf8_width() so numbers are
#     centered over their bar and the header total is right-aligned to the edge —
#     never hard-coded x offsets that overflow on the mono screen.
#   * The frame-callback pattern: draw only while animating or after a key press,
#     otherwise just call finished() so the device idles cool.
#
# Operation:  Left / Right = switch metric,  q = quit.
#
# Copy this file to /sd/py/ and run it with:  r dashboard_bars

import time
import anm
import esclib as elib

W = 400
H = 240

# ---- small layout helpers — always measure text before you place it ----------

def center_x(v, x, w, text):
  # x of a string so it is centered inside the box [x, x+w).
  return x + (w - v.get_utf8_width(text)) // 2

def right_x(v, right_edge, text):
  # x of a string so its right edge sits at `right_edge`.
  return right_edge - v.get_utf8_width(text)

def fit(v, text, max_w):
  # Truncate with an ellipsis so a label never spills past max_w pixels.
  if v.get_utf8_width(text) <= max_w:
    return text
  while text and v.get_utf8_width(text + '..') > max_w:
    text = text[:-1]
  return text + '..'

def clamp01(t):
  return 0.0 if t < 0 else (1.0 if t > 1 else t)


# ---- dummy data — three metrics, one value per weekday ------------------------

DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

METRICS = (
  # (title, unit, values-per-day, format-fn)
  ('Steps',     '', (5200, 8100, 6400, 9800, 7300, 11200, 4300), lambda x: '%d' % x),
  ('Focus',     'min', (95, 130, 60, 145, 120, 40, 20), lambda x: '%d' % x),
  ('Sleep',     'h', (6.5, 7.2, 5.8, 8.0, 6.9, 9.1, 7.6), lambda x: '%.1f' % x),
)


class BarDashboard:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.metric = 0
    self.dirty = True

    # A single linear timeline; each bar eases off a staggered slice of it.
    # Replaying = seek(0). Keeping one object is cheaper than one per bar.
    self.seq = anm.anm_sequencer()
    self.grow = anm.anm_object(750, {'t': [anm.linear, 0.0, 1.0]})
    self.seq.register('grow', self.grow)

  # geometry of the plot area (below the header, above the day labels)
  PLOT_X = 14
  PLOT_TOP = 46
  PLOT_BOTTOM = 196     # baseline y

  def _bar_progress(self, i, n):
    # Map the global 0..1 timeline onto bar i so bars start in sequence.
    # `spread` is how much of the timeline is used to fan the starts out.
    spread = 0.45
    each = 1.0 - spread
    start = spread * (i / (n - 1)) if n > 1 else 0.0
    return anm.ease_out(clamp01((self.grow.t - start) / each))

  def _animating(self):
    return self.grow.get_time() < 1.0

  def replay(self):
    self.grow.seek(0.0)
    self.dirty = True

  # ---- drawing --------------------------------------------------------------

  def draw_header(self):
    v = self.v
    title, unit, values, fmt = METRICS[self.metric]
    v.set_draw_color(1)
    v.draw_box(0, 0, W, 20)                 # solid inverted header = flat anchor
    v.set_draw_color(0)                     # draw ON the header in background ink
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(6, 15, 'This Week')

    # Right-aligned total, measured so it hugs the edge no matter its length.
    total = sum(values)
    label = 'total ' + fmt(total) + (' ' + unit if unit else '')
    v.draw_str(right_x(v, W - 6, label), 15, label)
    v.set_draw_color(1)

  def draw_bars(self):
    v = self.v
    title, unit, values, fmt = METRICS[self.metric]
    n = len(values)
    peak = max(values)

    plot_w = W - self.PLOT_X * 2
    slot = plot_w / n
    bar_w = int(slot * 0.62)
    full_h = self.PLOT_BOTTOM - self.PLOT_TOP

    # baseline rule
    v.set_draw_color(1)
    v.draw_h_line(self.PLOT_X, self.PLOT_BOTTOM, plot_w)

    v.set_font('u8g2_font_profont15_mf')
    for i, val in enumerate(values):
      prog = self._bar_progress(i, n)
      slot_x = int(self.PLOT_X + i * slot)
      bx = slot_x + (int(slot) - bar_w) // 2
      target_h = int(full_h * (val / peak)) if peak else 0
      bh = int(target_h * prog)
      by = self.PLOT_BOTTOM - bh

      # Flat fill: the peak day is solid ink, the rest a lighter dither so one
      # value pops without any 3D shading.
      if val == peak:
        v.set_dither(16)
        v.draw_box(bx, by, bar_w, bh)
      else:
        v.set_dither(9)
        v.draw_box(bx, by, bar_w, bh)
        v.set_dither(16)
        #v.draw_frame(bx, by, bar_w, bh)     # crisp outline keeps it flat & legible

      # value label above the bar, centered on the bar, only once it settles
      if prog > 0.98:
        vs_txt = fmt(val)
        v.set_dither(16)
        v.draw_str(center_x(v, bx, bar_w, vs_txt), by - 3, vs_txt)

      # day label under the baseline
      day = DAYS[i]
      v.draw_str(center_x(v, slot_x, int(slot), day), self.PLOT_BOTTOM + 14, day)

  def draw_footer(self):
    # A tiny "stat card" strip: average, in a big number, plus a hint line.
    v = self.v
    title, unit, values, fmt = METRICS[self.metric]
    avg = sum(values) / len(values)

    big = fmt(avg) + (' ' + unit if unit else '')

    v.set_draw_color(1)
    v.draw_h_line(0, 214, W)
    v.set_font('u8g2_font_profont15_mf')
    label = fit(v, title + ' avg', 120)
    v.draw_str(6, 230, label)                # the average as a prominent number
    v.draw_str(14 + v.get_utf8_width(label), 230, big)

    # metric pager dots on the right — shows which of the 3 metrics is active
    n = len(METRICS)
    dot_r = 3
    gap = 12
    total_w = (n - 1) * gap
    cx = W - 10 - total_w
    for i in range(n):
      x = cx + i * gap
      if i == self.metric:
        v.draw_disc(x, 226, dot_r,15)
      else:
        v.draw_circle(x, 226, dot_r,15)

  def draw(self):
    v = self.v
    v.clear_buffer()
    self.draw_header()
    self.draw_bars()
    self.draw_footer()
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
      elif k == b'\x1b[C':                 # Right
        self.metric = (self.metric + 1) % len(METRICS)
        self.replay()
      elif k == b'\x1b[D':                 # Left
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
  v.print(el.display_mode(False))          # hide the text cursor over graphics

  app = BarDashboard(vs)
  v.callback(app.update)
  try:
    app.key_loop()
  finally:
    v.callback(None)
    v.print(el.display_mode(True))
