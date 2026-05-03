# Pocket Deck text reader app
# - Smooth scrolling
# - UTF-8 support
# - Remembers read position per file
# - Markdown style **bold** support via fake bold rendering
#
# Keys:
#   Up/Down : scroll
#   Left/Right : page up/down
#   PageUp/PageDown : page up/down
#   q / Backspace : quit
#   Enter / A : toggle auto-scroll
#   n / p : next / previous file

import fontloader
import os
import time
import ujson
import pdeck
import esclib as elib
import argparse

try:
  import pdeck_utils as pu
except:
  pu = None

READER_STATE_FILE = "/config/reader_state.json"

KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_RIGHT = b'\x1b[C'
KEY_LEFT = b'\x1b[D'
KEY_ENTER = b'\r'
KEY_BS = b'\b'
KEY_PAGE_UP = b'\x1b[5~'
KEY_PAGE_DOWN = b'\x1b[6~'


def _read_text_file(path):
  # Read as bytes first, then decode UTF-8 with replacement
  with open(path, "rb") as f:
    data = f.read()
  try:
    return data.decode("utf-8")
  except:
    return data.decode("utf-8", "replace")


def _load_state():
  try:
    with open(READER_STATE_FILE, "r") as f:
      return ujson.loads(f.read())
  except:
    return {}


def _save_state(state):
  try:
    os.makedirs("/config")
  except:
    pass
  try:
    with open(READER_STATE_FILE, "w") as f:
      f.write(ujson.dumps(state))
  except:
    pass


def _split_lines(text):
  # Preserve paragraphs but normalize line endings
  text = text.replace("\r\n", "\n").replace("\r", "\n")
  return text.split("\n")


def _tokenize_markdown_bold(line):
  """
  Split a line into [(is_bold, text), ...] using Markdown style **bold**.
  Unmatched ** is treated as normal text.
  """
  if not line:
    return [(False, "")]
  parts = line.split("**")
  if len(parts) < 3:
    return [(False, line)]

  out = []
  for i in range(len(parts)):
    part = parts[i]
    if part == "" and i == len(parts) - 1:
      continue
    if i % 2 == 0:
      if part != "":
        out.append((False, part))
    else:
      if part != "":
        out.append((True, part))
  if not out:
    return [(False, "")]
  return out


def _plain_text_from_segments(segments):
  s = ""
  for is_bold, text in segments:
    s += text
  return s


def _slice_segments(segments, start, end):
  """
  Slice by visible character index while preserving bold attributes.
  """
  out = []
  pos = 0
  for is_bold, text in segments:
    tlen = len(text)
    seg_start = start - pos
    seg_end = end - pos
    if seg_end <= 0:
      break
    if seg_start < tlen and seg_end > 0:
      a = 0 if seg_start < 0 else seg_start
      b = tlen if seg_end > tlen else seg_end
      if a < b:
        out.append((is_bold, text[a:b]))
    pos += tlen
  return out


def _segments_width(v, segments, vertical, height, font):
  text = _plain_text_from_segments(segments)
  if vertical and font == 'uni':
    return height * len(text)
  return v.get_utf8_width(text)


def _wrap_segments(v, segments, height, max_width, vertical, pre, font):
  """
  Wrap one parsed line preserving bold spans.
  Returns list of wrapped line segments:
    [[(is_bold, text), ...], ...]
  """
  plain = _plain_text_from_segments(segments)
  if plain == "":
    return [[(False, "")]]

  cur_end = pre if pre < len(plain) else len(plain)
  out = []

  while cur_end < len(plain):
    cur_segments = _slice_segments(segments, 0, cur_end)
    ch_segments = _slice_segments(segments, cur_end, cur_end + 1)
    test_segments = _slice_segments(segments, 0, cur_end + 1)
    ch = plain[cur_end]

    w = _segments_width(v, test_segments, vertical, height, font)

    if vertical and font == 'uni':
      if ch in ("、", "。", "っ", "ゃ", "ゅ", "ょ", "ッ", "ャ", "ュ", "ョ", "」", ")", "ー", "？", "！"):
        wrap = not (w <= max_width or len(_plain_text_from_segments(cur_segments)) == 0)
      else:
        wrap = not (w <= max_width - height or len(_plain_text_from_segments(cur_segments)) == 0)
    else:
      wrap = not (w <= max_width or len(_plain_text_from_segments(cur_segments)) == 0)

    if not wrap:
      cur_end += 1
      continue

    cur_plain = _plain_text_from_segments(cur_segments)
    if not vertical and ch != ' ' and cur_plain != "" and cur_plain[-1] != ' ':
      if len(cur_segments) > 0:
        last_bold = cur_segments[-1][0]
      else:
        last_bold = False
      cur_segments.append((last_bold, '-'))
    out.append(cur_segments)

    next_start = cur_end
    next_end = cur_end + pre + 1
    if next_end > len(plain):
      next_end = len(plain)
    cur_end = next_end

  out.append(_slice_segments(segments, 0 if len(out) == 0 else len(_plain_text_from_segments(_slice_segments(segments, 0, 0))), len(plain)))

  rebuilt = []
  consumed = 0
  for wrapped in out[:-1]:
    rebuilt.append(wrapped)
    consumed += len(_plain_text_from_segments(wrapped))
    if _plain_text_from_segments(wrapped).endswith('-'):
      consumed -= 1
  last_seg = _slice_segments(segments, consumed, len(plain))
  if len(out) == 1:
    return [last_seg]
  rebuilt.append(last_seg)
  return rebuilt


def _wrap_line(v, line, height, max_width, vertical, pre, font):
  """
  Wrap one UTF-8 line by character width with Markdown bold support.
  Returns a list of wrapped lines, each line is [(is_bold, text), ...]
  """
  if line == "":
    return [[(False, "")]]

  segments = _tokenize_markdown_bold(line)
  plain = _plain_text_from_segments(segments)
  if plain == "":
    return [[(False, "")]]

  out = []
  start = 0
  cur = plain[:pre]
  index = 0
  line_pre = plain[pre:]

  while index < len(line_pre):
    ch = line_pre[index]
    test = cur + ch
    if vertical and font == 'uni':
      w = height * len(test)
    else:
      w = v.get_utf8_width(test)

    if vertical and font == 'uni':
      if ch in ("、" ,"。","っ","ゃ","ゅ","ょ","ッ","ャ","ュ","ョ","」",")","ー","？","！"):
        wrap = not (w <= max_width or cur == "")
      else:
        wrap = not (w <= max_width - height or cur == "")
    else:
      wrap = not (w <= max_width or cur == "")

    if not wrap:
      cur = test
    else:
      end = pre + index
      wrapped = _slice_segments(segments, start, end)
      if not vertical and ch != ' ' and cur[-1] != ' ':
        last_bold = wrapped[-1][0] if len(wrapped) > 0 else False
        wrapped.append((last_bold, '-'))
      out.append(wrapped)

      start = end
      cur = line_pre[index:index + pre + 1]
      index += pre
    index += 1

  out.append(_slice_segments(segments, start, len(plain)))
  return out


class Reader:
  def __init__(self, v, vs, paths, isvertical, font):
    self.v = v
    self.vertical = isvertical
    self.pre = 20
    self.vs = vs
    self.paths = paths if paths else []
    self.file_index = 0
    self.state = _load_state()
    self.auto_scroll = False
    self.scroll_px = 0
    self.op_scroll_px = 0
    self.scroll_speed = 150  # pixels per frame
    self.current_tick = 0
    self.screen_w, self.screen_h = pdeck.get_screen_size()
    self.margin_x = 0
    self.margin_top = 23
    self.margin_bottom = -10
    self.line_gap = 2
    self.fontname = font
    self.el = elib.esclib()

    if font == 'lub1':
      self.pre = 40
      fontname = 'u8g2_font_lubR10_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 20
      self.margin_x = 5
    elif font == 'lub2':
      self.pre = 30
      fontname = 'u8g2_font_lubR12_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 25
      self.margin_x = 5
    elif font == 'uni':
      self.pre = 20
      fontname = 'unifont_large'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 18
    elif font == 'cen1':
      self.pre = 40
      fontname = 'u8g2_font_ncenR10_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 20
      self.margin_x = 5
    elif font == 'cen2':
      self.pre = 30
      fontname = 'u8g2_font_ncenR12_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.margin_x = 5
      self.line_height = 24

    self.help_h = 18
    self.text_h = (self.screen_h - self.margin_top - self.margin_bottom - self.help_h) // self.line_height * self.line_height

    self.status = ""
    self.status_life = 0

    self.wrapped_lines = []
    self.total_height = 0
    self.current_path = None
    self.current_key = None

  def _state_key(self, path):
    return path

  def basename(self, path):
    return path.rsplit('/', 1)[-1]

  def load_file(self, path):
    self.current_key = self._state_key(path)
    raw_text = _read_text_file(path)

    self.v.set_font(self.font)

    max_width = self.screen_w - self.margin_x * 2
    lines = _split_lines(raw_text)
    self.wrapped_lines = []
    for line in lines:
      self.wrapped_lines.extend(_wrap_line(self.v, line, 16, max_width, self.vertical, self.pre, self.fontname))

    self.total_height = len(self.wrapped_lines) * self.line_height

    saved = self.state.get(self.current_key, {})
    self.scroll_px = int(saved.get("scroll_px", 0))
    if self.scroll_px < 0:
      self.scroll_px = 0
    if self.total_height > 0 and self.scroll_px > self.total_height - self.text_h:
      self.scroll_px = max(0, self.total_height - self.text_h)

    self.status = "Loaded: " + self.basename(path)
    self.status_life = 60
    self.current_path = path

  def save_position(self):
    if not self.current_key:
      return
    self.state[self.current_key] = {
      "scroll_px": int(self.scroll_px),
    }
    _save_state(self.state)

  def next_file(self):
    if len(self.paths) <= 1:
      return
    self.save_position()
    self.file_index = (self.file_index + 1) % len(self.paths)
    self.load_file(self.paths[self.file_index])

  def prev_file(self):
    if len(self.paths) <= 1:
      return
    self.save_position()
    self.file_index = (self.file_index - 1) % len(self.paths)
    self.load_file(self.paths[self.file_index])

  def scroll_by(self, delta):
    self.scroll_px += int(delta)
    if self.scroll_px < 0:
      self.scroll_px = 0
    max_scroll = max(0, self.total_height - self.text_h)
    if self.scroll_px > max_scroll:
      self.scroll_px = max_scroll

  def page_down(self):
    self.scroll_by((self.text_h // self.line_height) * self.line_height + self.line_height)

  def page_up(self):
    self.scroll_by(-(self.text_h // self.line_height) * self.line_height - self.line_height)

  def draw_header(self):
    if self.current_path:
      base = self.basename(self.current_path)
      header = base
      try:
        pct = 0
        if self.total_height > self.text_h:
          pct = int(self.scroll_px * 100 / (self.total_height - self.text_h))
        header = "{}  {}%".format(base, pct)
      except:
        pass
      self.v.set_draw_color(0)
      self.v.draw_box(0, 0, 400, 23)
      self.v.set_draw_color(1)

      self.v.set_dither(8)
      self.v.draw_line(0, 21, 399, 21)
      self.v.set_dither(16)
      self.v.draw_str(self.margin_x, 18, header)

  def _draw_segments_horizontal(self, x, y, segments):
    self.v.set_font_pos_bottom()
    cur_x = x
    for is_bold, text in segments:
      if text == "":
        continue
      if is_bold:
        self.v.draw_utf8(cur_x, y, text)
        self.v.draw_utf8(cur_x + 1, y, text)
      else:
        self.v.draw_utf8(cur_x, y, text)
      cur_x += self.v.get_utf8_width(text)
    self.v.set_font_pos_baseline()

  def _draw_segments_vertical(self, x, y, segments):
    text = _plain_text_from_segments(segments)
    if self.fontname == 'uni':
      self.v.draw_utf8_v(x, y, text)
    else:
      self.v.set_font_direction(1)
      self.v.draw_utf8(x, y, text)
      self.v.set_font_direction(0)

  def _draw_segments(self, x, y, segments):
    if self.vertical:
      self._draw_segments_vertical(x, y, segments)
    else:
      self._draw_segments_horizontal(x, y, segments)

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return

    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = (self.current_tick - self.last_tick)

    self.v.set_draw_color(1)
    self.v.set_font(self.font)

    if not self.current_path:
      self.v.draw_str(50, 100, "Loading book...")
      self.v.finished()
      return

    if self.auto_scroll:
      self.scroll_px += self.scroll_speed * (self.time_diff / 1000000)

    if self.op_scroll_px < self.scroll_px:
      speed = int(self.scroll_px - self.op_scroll_px) // 3
      speed = 1 if speed < 1 else speed
      self.op_scroll_px += speed

    if self.op_scroll_px > self.scroll_px:
      speed = int(self.op_scroll_px - self.scroll_px) // 3
      speed = 1 if speed < 1 else speed
      self.op_scroll_px -= speed

    start_line = self.op_scroll_px // self.line_height
    y_offset = -(self.op_scroll_px % self.line_height)

    y = self.margin_top + y_offset + self.line_height
    max_lines = (self.screen_h - y - self.margin_bottom - self.help_h) // self.line_height + 2

    for i in range(max_lines):
      idx = start_line + i
      if idx >= len(self.wrapped_lines):
        break
      line = self.wrapped_lines[idx]
      self._draw_segments(self.margin_x, y, line)
      y += self.line_height

    self.draw_header()
    self.v.finished()

  def _read_key(self):
    ret = self.v.read_nb(1)
    if not ret or ret[0] <= 0:
      return None
    k = ret[1].encode("ascii")
    if k == b"\x1b":
      seq = [k]
      seq.append(self.vs.read(1).encode("ascii"))
      if seq[-1] == b"[":
        seq.append(self.vs.read(1).encode("ascii"))
        if seq[-1] >= b"0" and seq[-1] <= b"9":
          seq.append(self.vs.read(1).encode("ascii"))
      return b"".join(seq)
    return k

  def handle_key(self, k):
    if k is None:
      return True
    if k == b"q" or k == KEY_BS:
      self.save_position()
      return False

    if k == KEY_DOWN:
      self.scroll_by(self.line_height)
    elif k == KEY_UP:
      self.scroll_by(-self.line_height)
    elif k == KEY_RIGHT or k == KEY_PAGE_DOWN:
      self.page_down()
    elif k == KEY_LEFT or k == KEY_PAGE_UP:
      self.page_up()
    elif k == KEY_ENTER:
      self.auto_scroll = not self.auto_scroll
      self.status = "Auto-scroll ON" if self.auto_scroll else "Auto-scroll OFF"
      if not self.auto_scroll:
        self.scroll_px = self.scroll_px // self.line_height * self.line_height + self.line_height
      self.status_life = 40
    elif k == b"n":
      self.next_file()
    elif k == b"p":
      self.prev_file()

    return True

  def loop(self):
    last_save = time.ticks_ms()

    self.touch_slide = False
    self.slide_spoint = 0
    self.touch_mouse = False
    self.slide_mouse = 0
    self.lbutton = False
    self.rbutton = False

    while True:
      k = self._read_key()
      if not self.handle_key(k):
        break

      keys = self.v.get_tp_keys()

      if not keys:
        pdeck.delay_tick(100)
        continue

      my, mx = keys[1:3]
      lbutton = 1 if keys[3] & 1 else 0
      rbutton = 1 if keys[3] & 2 else 0

      if not self.lbutton and lbutton:
        self.handle_key(KEY_RIGHT)
        self.lbutton = True
      if self.lbutton and not lbutton:
        self.lbutton = False
      if not self.rbutton and rbutton:
        self.handle_key(KEY_LEFT)
        self.rbutton = True
      if self.rbutton and not rbutton:
        self.rbutton = False

      touch_mouse = not (mx == 255 or my == 255)
      if not self.touch_mouse and touch_mouse:
        self.touch_mouse = True
        self.mouse_spoint = my
      if self.touch_mouse:
        if not touch_mouse:
          self.touch_mouse = False
        else:
          if abs(self.mouse_spoint - my) > 10:
            lines = (self.mouse_spoint - my) // 10 + 1
            self.scroll_by(self.line_height * lines)
            self.mouse_spoint = my

      if keys[0] != 0xff and not self.touch_slide:
        self.touch_slide = True
        self.slide_spoint = keys[0]
      if self.touch_slide:
        if keys[0] == 0xff:
          self.touch_slide = False
        else:
          if abs(self.slide_spoint - keys[0]) > 3:
            lines = (self.slide_spoint - keys[0]) // 4 + 1
            self.scroll_by(self.line_height * lines)
            self.slide_spoint = keys[0]

      now = time.ticks_ms()
      if time.ticks_diff(now, last_save) > 30000:
        self.save_position()
        last_save = now

      if not self.v.active:
        pdeck.delay_tick(100)
      else:
        time.sleep(0.1)

    self.save_position()


def main(vs, args_in):
  v = vs.v
  el = elib.esclib()

  parser = argparse.ArgumentParser(
            description='Book Reader')
  parser.add_argument('-v', '--vertical', action='store_true', help='Japanese vertical style')
  parser.add_argument('-f', '--font', action='store', default='cen1', help='Specify font. Options are : uni (unicode), lub1, lub2, cen1, cen2')
  parser.add_argument('filename', args='*', help='filename to read')

  args = parser.parse_args(args_in[1:])

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  if isinstance(args.filename, str):
    paths = [args.filename]
  else:
    paths = args.filename

  reader = Reader(v, vs, paths, args.vertical, args.font)
  v.callback(reader.update)
  reader.load_file(paths[0])
  reader.loop()
  v.callback(None)

  v.print(el.display_mode(True))
  print("finished.", file=vs)
