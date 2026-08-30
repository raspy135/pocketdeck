# word_count.py — Morning writing word-count dashboard for journal.md
# Top: big progress bar for today vs 400-word goal.
# Bottom: small bars for the last 7 days (including today).
# Enter = reload data, Backspace / q = quit.

import argparse

import time
import os
import anm
import esclib as elib
import pdeck
import pdeck_utils

W = 400
H = 240
GOAL = 400
DEFAULT_JOURNAL = '/sd/Documents/journal.md'
DAY_NAMES = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
# Background poll: re-read journal every N ms while idle.
RELOAD_MS = 3000
# LED1 celebration when today's count first hits the goal.
LED_FLASHES = 6
LED_ON_MS = 120
LED_OFF_MS = 100
LED_BRIGHT = 80


def center_x(v, x, w, text):
  return x + (w - v.get_utf8_width(text)) // 2


def right_x(v, right_edge, text):
  return right_edge - v.get_utf8_width(text)


def fit(v, text, max_w):
  if v.get_utf8_width(text) <= max_w:
    return text
  while text and v.get_utf8_width(text + '..') > max_w:
    text = text[:-1]
  return text + '..'


def clamp01(t):
  return 0.0 if t < 0 else (1.0 if t > 1 else t)


def count_words(text):
  n = 0
  for part in text.split():
    if part:
      n += 1
  return n


def ymd_key(y, m, d):
  return '%04d-%02d-%02d' % (y, m, d)


def now_local():
  # Device clock is UTC; apply system timezone (units of 15 minutes).
  return time.gmtime(time.time() + 60 * 15 * pdeck_utils.timezone)


def today_ymd():
  t = now_local()
  return (t[0], t[1], t[2])


def add_days(y, m, d, delta):
  t = time.mktime((y, m, d, 12, 0, 0, 0, 0))
  t += delta * 86400
  lt = time.gmtime(int(t))
  return (lt[0], lt[1], lt[2])


def weekday_name(y, m, d):
  t = time.mktime((y, m, d, 12, 0, 0, 0, 0))
  lt = time.gmtime(int(t))
  # MicroPython gmtime: tm_wday 0=Mon .. 6=Sun
  return DAY_NAMES[lt[6]]


def parse_header_date(line):
  # Journal day headers look like: ## <2026-07-17 Fri>
  # Avoid MicroPython re quantifier limits; parse with string ops.
  s = line.strip()
  if not s.startswith('##'):
    return None
  lt = s.find('<')
  gt = s.find('>', lt + 1) if lt >= 0 else -1
  if lt < 0 or gt < 0:
    return None
  inside = s[lt + 1:gt].strip()
  if not inside:
    return None
  # first token is YYYY-MM-DD
  token = inside.split()[0] if ' ' in inside else inside
  parts = token.split('-')
  if len(parts) != 3:
    return None
  try:
    return (int(parts[0]), int(parts[1]), int(parts[2]))
  except ValueError:
    return None


def is_checkbox_line(line):
  s = line.lstrip()
  return s.startswith('- [') or s.startswith('- [')


def parse_journal_words(path):
  """Return { 'YYYY-MM-DD': word_count } from free-text body of each day."""
  counts = {}
  try:
    f = open(path, 'r')
  except OSError:
    return counts

  cur = None
  buf = []
  try:
    while True:
      line = f.readline()
      if not line:
        break
      if line.endswith('\n'):
        line = line[:-1]
      if line.endswith('\r'):
        line = line[:-1]

      d = parse_header_date(line)
      if d is not None:
        if cur is not None:
          counts[cur] = count_words(' '.join(buf))
        cur = ymd_key(d[0], d[1], d[2])
        buf = []
        continue

      if cur is None:
        continue
      # Skip checkbox / numeric list items; keep free writing.
      s = line.lstrip()
      if s.startswith('- ['):
        continue
      if s == '':
        continue
      buf.append(line)
  finally:
    f.close()

  if cur is not None:
    counts[cur] = count_words(' '.join(buf))
  return counts


class WordCountApp:
  def __init__(self, vs, path=DEFAULT_JOURNAL):
    self.vs = vs
    self.v = vs.v
    self.path = path
    self.dirty = True
    self.today = today_ymd()
    self.days = []       # list of (ymd_tuple, key, label, words)
    self.today_words = 0
    self.error = None
    self.last_reload_ms = 0
    # Cached journal stat so idle polls skip a full re-parse when unchanged.
    # Tuple is (size, mtime) or None if the file is missing / unreadable.
    self._file_stat = None
    # Goal LED: flash once when we cross GOAL; stay quiet after that day.
    self.goal_reached = False
    self.led_flash_left = 0
    self.led_on = False
    self.led_next_ms = 0

    self.seq = anm.anm_sequencer()
    # Big bar grows first, then the 7 small bars stagger in.
    self.grow = anm.anm_object(900, {'t': [anm.linear, 0.0, 1.0]})
    self.seq.register('grow', self.grow)

    # Initial load: seed state without celebrating a goal already met.
    self.reload(animate=True, celebrate=False)

  def _stat_sig(self):
    """Return (size, mtime) for the journal, or None if unavailable."""
    try:
      st = os.stat(self.path)
      # MicroPython stat: st[6]=size, st[8]=mtime
      return (st[6], st[8])
    except OSError:
      return None

  def reload(self, animate=True, celebrate=True, force=False):
    prev_words = self.today_words
    prev_goal = self.goal_reached
    self.today = today_ymd()
    self.error = None
    self.last_reload_ms = time.ticks_ms()

    # Cheap path: if size+mtime are unchanged, skip opening/parsing the file.
    # Still recompute the day window so a midnight rollover updates labels.
    sig = self._stat_sig()
    if (not force) and sig is not None and sig == self._file_stat and self.days:
      days = []
      for i in range(6, -1, -1):
        y, m, d = add_days(self.today[0], self.today[1], self.today[2], -i)
        key = ymd_key(y, m, d)
        label = weekday_name(y, m, d)
        words = 0
        for old in self.days:
          if old[1] == key:
            words = old[3]
            break
        days.append(((y, m, d), key, label, words))
      changed = days != self.days
      self.days = days
      self.today_words = days[-1][3] if days else 0
      if changed or animate:
        self.replay()
      return

    try:
      counts = parse_journal_words(self.path)
    except Exception as e:
      counts = {}
      self.error = str(e)

    self._file_stat = sig

    days = []
    for i in range(6, -1, -1):
      y, m, d = add_days(self.today[0], self.today[1], self.today[2], -i)
      key = ymd_key(y, m, d)
      label = weekday_name(y, m, d)
      words = counts.get(key, 0)
      days.append(((y, m, d), key, label, words))

    changed = days != self.days
    self.days = days
    self.today_words = days[-1][3] if days else 0

    # Fire LED celebration only on the below-goal -> goal transition.
    if self.today_words >= GOAL:
      if celebrate and (not prev_goal) and prev_words < GOAL:
        self._start_led_flash()
      self.goal_reached = True
    else:
      self.goal_reached = False

    if changed or animate:
      self.replay()
    elif self.error:
      self.dirty = True

  def replay(self):
    self.grow.seek(0.0)
    self.dirty = True

  def _start_led_flash(self):
    self.led_flash_left = LED_FLASHES
    self.led_on = True
    self.led_next_ms = time.ticks_ms() + LED_ON_MS
    try:
      pdeck.led(1, LED_BRIGHT)
    except Exception:
      pass

  def _led_off(self):
    self.led_on = False
    self.led_flash_left = 0
    try:
      pdeck.led(1, 0)
    except Exception:
      pass

  def _update_led(self, now):
    if self.led_flash_left <= 0:
      return
    if time.ticks_diff(now, self.led_next_ms) < 0:
      return
    if self.led_on:
      # turn off between flashes
      try:
        pdeck.led(1, 0)
      except Exception:
        pass
      self.led_on = False
      self.led_flash_left -= 1
      if self.led_flash_left <= 0:
        return
      self.led_next_ms = now + LED_OFF_MS
    else:
      try:
        pdeck.led(1, LED_BRIGHT)
      except Exception:
        pass
      self.led_on = True
      self.led_next_ms = now + LED_ON_MS

  def _animating(self):
    return self.grow.get_time() < 1.0

  def _big_progress(self):
    # Big bar uses the first ~45% of the timeline.
    return anm.ease_out(clamp01(self.grow.t / 0.45))

  def _small_progress(self, i, n):
    # Small bars start after the big bar, staggered, and all finish by t=1.
    # Previously each=0.55 left later bars at ~0.5–0.9 when grow ended, so
    # value labels (prog > 0.98) never appeared for Wed–Fri.
    base = 0.30
    each = 0.40
    last_start = 1.0 - each
    spread = max(0.0, last_start - base)
    start = base + spread * (i / (n - 1) if n > 1 else 0.0)
    return anm.ease_out(clamp01((self.grow.t - start) / each))

  # ---- drawing --------------------------------------------------------------

  def draw_header(self):
    v = self.v
    v.set_draw_color(1)
    v.draw_box(0, 0, W, 20)
    v.set_draw_color(0)
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(6, 15, 'Morning Word')

    ty, tm, td = self.today
    date_s = '%04d-%02d-%02d' % (ty, tm, td)
    v.draw_str(right_x(v, W - 6, date_s), 15, date_s)
    v.set_draw_color(1)

  def draw_today(self):
    v = self.v
    words = self.today_words
    prog = self._big_progress()
    ratio = min(1.0, words / GOAL) if GOAL else 0.0
    shown = ratio * prog

    # Animated word count: counts from 0 → today_words as the bar grows.
    shown_words = int(words * prog)

    # Section title
    v.set_font('u8g2_font_profont15_mf')
    v.set_draw_color(1)
    v.draw_str(10, 38, 'Today')

    # Big readout (animated count)
    big = str(shown_words)
    v.set_font('u8g2_font_profont29_mf')
    v.draw_str(10, 72, big)
    big_w = v.get_utf8_width(big)

    # "/ 400 words" next to the big number
    v.set_font('u8g2_font_profont15_mf')
    unit = '/ %d words' % GOAL
    v.draw_str(14 + big_w, 68, unit)

    # Goal percentage chip on the right (still based on actual words)
    if GOAL:
      pct = int(round(min(999, words * 100 // GOAL)))
    else:
      pct = 0
    chip = 'goal!' if words >= GOAL else ('%d%%' % pct)
    v.set_font('u8g2_font_profont22_mf')
    v.draw_str(right_x(v, W - 10, chip), 68, chip)

    # Progress track
    track_x = 10
    track_y = 84
    track_w = W - 20
    track_h = 22
    v.set_draw_color(1)
    v.set_dither(16)
    v.draw_frame(track_x, track_y, track_w, track_h)

    fill_w = int((track_w - 4) * shown)
    if fill_w > 0:
      # Solid when goal met, dithered otherwise.
      if words >= GOAL:
        v.set_dither(16)
      else:
        # Big bar filling color
        v.set_dither(16)
      v.draw_box(track_x + 2, track_y + 2, fill_w, track_h - 4)
      v.set_dither(16)

    # Mid marker at 50%
    mid_x = track_x + track_w // 2
    v.draw_v_line(mid_x, track_y - 2, track_h + 4)

    # Caption under the bar
    v.set_font('u8g2_font_profont15_mf')
    remain = max(0, GOAL - words)
    if words >= GOAL:
      cap = 'Daily goal reached'
    else:
      cap = '%d to go - goal %d' % (remain, GOAL)
    v.draw_str(center_x(v, 0, W, cap), 124, cap)

  def draw_week(self):
    v = self.v
    days = self.days
    n = len(days)
    if n == 0:
      return

    # Section header + rule
    v.set_draw_color(1)
    v.set_dither(16)
    v.draw_h_line(0, 134, W)
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(10, 150, 'Last 7 days')

    peak = max(GOAL, max((d[3] for d in days), default=0))
    plot_x = 14
    plot_w = W - plot_x * 2
    plot_top = 158
    plot_bottom = 214
    full_h = plot_bottom - plot_top
    slot = plot_w / n
    bar_w = int(slot * 0.55)

    # Goal reference line across the plot
    goal_y = plot_bottom - int(full_h * (GOAL / peak)) if peak else plot_bottom
    v.set_dither(6)
    v.draw_h_line(plot_x, goal_y, plot_w)
    v.set_dither(16)
    gtxt = str(GOAL)
    v.set_font('u8g2_font_profont15_mf')
    v.draw_str(right_x(v, W - 6, gtxt), goal_y - 2, gtxt)

    # Baseline
    v.draw_h_line(plot_x, plot_bottom, plot_w)

    for i, (_ymd, _key, label, words) in enumerate(days):
      prog = self._small_progress(i, n)
      slot_x = int(plot_x + i * slot)
      bx = slot_x + (int(slot) - bar_w) // 2
      target_h = int(full_h * (words / peak)) if peak else 0
      bh = int(target_h * prog)
      by = plot_bottom - bh
      is_today = (i == n - 1)

      if bh > 0:
        if is_today or words >= GOAL:
          v.set_dither(16)
        else:
          v.set_dither(9)
        v.draw_box(bx, by, bar_w, bh)
        v.set_dither(16)

      # Animated count: rises with the bar (show from the moment bar appears)
      shown_words = int(words * prog)
      if shown_words > 0:
        vs_txt = str(shown_words)
        v.draw_str(center_x(v, bx, bar_w, vs_txt), by - 2, vs_txt)

      # Day label; mark today with a small underline
      v.set_font('u8g2_font_profont15_mf')
      v.draw_str(center_x(v, slot_x, int(slot), label), plot_bottom + 14, label)
      if is_today:
        uw = v.get_utf8_width(label)
        ux = center_x(v, slot_x, int(slot), label)
        v.draw_h_line(ux, plot_bottom + 16, uw)

  def draw_error(self):
    if not self.error:
      return
    v = self.v
    v.set_font('u8g2_font_profont15_mf')
    v.set_draw_color(1)
    msg = fit(v, 'err: ' + self.error, W - 20)
    v.draw_str(10, H - 4, msg)

  def draw(self):
    v = self.v
    v.clear_buffer()
    self.draw_header()
    self.draw_today()
    self.draw_week()
    self.draw_error()
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
    # Non-blocking loop so we can poll the journal in the background.
    while True:
      now = time.ticks_ms()
      self._update_led(now)

      # Periodic background reload (also works while app is in background).
      # reload() stats the file first and only re-parses when it changed.
      if time.ticks_diff(now, self.last_reload_ms) >= RELOAD_MS:
        self.reload(animate=False)

      ret = self.v.read_nb(1)
      if not ret or ret[0] <= 0:
        if not self.v.active:
          pdeck.delay_tick(200)
        else:
          pdeck.delay_tick(4)
        continue

      k = self._decode_key(ret[1])
      if k in (b'q', b'Q', b'\x08', b'\x7f'):
        break
      elif k in (b'\r', b'\n'):
        # Enter forces a full re-parse even if stat looks the same.
        self.reload(animate=True, force=True)

  def _decode_key(self, keys):
    keys = keys.encode('ascii')
    if keys != b'\x1b':
      return keys
    seq = [keys]
    seq.append(self.vs.read(1).encode('ascii'))
    if seq[-1] == b'[':
      seq.append(self.vs.read(1).encode('ascii'))
    return b''.join(seq)


def main(vs, args):
  global GOAL

  parser = argparse.ArgumentParser()
  parser.add_argument('-g', '--goal', type=int, default=GOAL,
                       help='Daily word count goal (default: %d)' % GOAL)
  parser.add_argument('filename', nargs='?', default=DEFAULT_JOURNAL,
                       help='Journal file path (default: %s)' % DEFAULT_JOURNAL)
  parsed = parser.parse_args(args[1:])

  path = parsed.filename
  GOAL = parsed.goal

  v = vs.v
  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  app = WordCountApp(vs, path)
  v.callback(app.update)
  try:
    app.key_loop()
  finally:
    app._led_off()
    v.callback(None)
    v.print(el.display_mode(True))
