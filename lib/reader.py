# Pocket Deck text reader app
# - Smooth scrolling
# - UTF-8 support
# - Remembers read position per file
#
# Keys:
#   Up/Down : scroll
#   Left/Right : page up/down
#   Enter / A : toggle auto-scroll
#   B / Backspace : quit
#   q : quit

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


def _wrap_line(v, line, height, max_width, vertical, pre, font):
  """
  Wrap one UTF-8 line by character width.
  Works reasonably for mixed ASCII/UTF-8 text.
  """
  if line == "":
    return [""]

  
  line_pre=line[pre:]
  out = []
  cur = line[:pre]
  index = 0
  while index < len(line_pre):
    ch = line_pre[index]
    test = cur + ch
    if vertical and font=='uni':
      w = height * len(test)
    else:
      w = v.get_utf8_width(test)
    if vertical and font == 'uni':
      if (ch in ("、" ,"。","っ","ゃ","ゅ","ょ","ッ","ャ","ュ","ョ","」",")","ー","？","！")):
        wrap = not (w <= max_width or cur == "")
      else:
        wrap = not (w <= max_width-height or cur == "")    
    else:
      wrap = not (w <= max_width or cur == "")
      
    if not wrap:
      cur = test
    else:
      if not vertical and ch != ' ' and cur[-1] !=' ':
        cur += '-'
      out.append(cur)
      cur = line_pre[index:index+pre+1]
      index += pre
    index += 1
  out.append(cur)
  return out


class Reader:
  def __init__(self, v, vs, paths, isvertical, font):
    self.v = v
    self.vertical = isvertical
    self.pre=20
    self.vs = vs
    self.paths = paths if paths else []
    self.file_index = 0
    self.state = _load_state()
    self.auto_scroll = False
    self.scroll_px = 0
    self.op_scroll_px = 0
    self.scroll_speed = 150  # pixels per frame
    self.current_tick=0
    self.screen_w, self.screen_h = pdeck.get_screen_size()
    self.margin_x = 0
    self.margin_top = 23
    self.margin_bottom = -10
    self.line_gap = 2
    self.fontname = font
    
    if font == 'lub1':
      self.pre=40
      #self.font = "u8g2_font_profont15_mf"
      fontname = 'u8g2_font_lubR10_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 20
      self.margin_x = 5
    elif font == 'lub2':
      self.pre=30
      fontname = 'u8g2_font_lubR12_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 25
      self.margin_x = 5
    elif font == 'uni':
      self.pre=20
      fontname = 'unifont_large'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 18
    elif font == 'cen1':
      self.pre=40
      fontname = 'u8g2_font_ncenR10_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.line_height = 20
      self.margin_x = 5
    elif font == 'cen2':
      self.pre=30
      fontname = 'u8g2_font_ncenR12_te'
      fontloader.load(fontname)
      self.font = fontloader.font_list[fontname]
      self.v.set_font(self.font)
      self.margin_x = 5
      self.line_height = 24
    

    self.help_h = 18
    self.text_h = (self.screen_h - self.margin_top - self.margin_bottom - self.help_h )//self.line_height * self.line_height

    self.status = ""
    self.status_life = 0

    #self.raw_text = ""
    #self.lines = []
    self.wrapped_lines = []
    self.total_height = 0
    self.current_path = None
    self.current_key = None

    #
    #if not self.paths:
    #  self.status = "No file given"
    #  self.status_life = 9999
    #else:
    #  self.load_file(self.paths[self.file_index])

  def _state_key(self, path):
    return path

  def basename(self, path):
    return path.rsplit('/',1)[-1]  

  def load_file(self, path):
    #print(path)
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
    #print("position saved")
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
    self.scroll_by((self.text_h//self.line_height ) *self.line_height+self.line_height)

  def page_up(self):
    self.scroll_by(-(self.text_h//self.line_height) * self.line_height-self.line_height)

  def draw_header(self):
    # Header
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
      self.v.draw_box(0,0,400,23)
      self.v.set_draw_color(1)

      self.v.set_dither(8)
      self.v.draw_line(0,21, 399,21)
      self.v.set_dither(16)
      self.v.draw_str(self.margin_x, 18, header)

  def update(self,e):
    if not self.v.active:
      self.v.finished()
      return
      

    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = (self.current_tick - self.last_tick)

    self.v.set_draw_color(1)
    self.v.set_font(self.font)
    
    if not self.current_path:
      self.v.draw_str(50, 100, f"Loading book...{len(self.wrapped_lines)}")
      self.v.finished()
      return      

    if self.auto_scroll:
      self.scroll_px += self.scroll_speed * (self.time_diff / 1000000)
 
    if self.op_scroll_px < self.scroll_px:
      speed = int(self.scroll_px - self.op_scroll_px)  // 3
      speed = 1 if speed < 1 else speed
      self.op_scroll_px += speed

    if self.op_scroll_px > self.scroll_px:
      speed = int(self.op_scroll_px - self.scroll_px)  // 3
      speed = 1 if speed < 1 else speed
      self.op_scroll_px -= speed

    # Text area
    start_line = self.op_scroll_px // self.line_height
    y_offset = -(self.op_scroll_px % self.line_height)

    y = self.margin_top + y_offset + self.line_height
    max_lines = (self.screen_h - y - self.margin_bottom - self.help_h) // self.line_height + 2

    for i in range(max_lines):
      idx = start_line + i
      if idx >= len(self.wrapped_lines):
        break
      line = self.wrapped_lines[idx]
      if self.vertical:
        if self.fontname == 'uni':
          self.v.draw_utf8_v(self.margin_x, y, line)
        else:
          self.v.set_font_direction(1)
          self.v.draw_utf8(self.margin_x, y, line)
          self.v.set_font_direction(0)
      else:
        self.v.set_font_pos_bottom()
        self.v.draw_utf8(self.margin_x, y, line)
        self.v.set_font_pos_baseline()

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
    elif k == KEY_RIGHT:
      self.page_down()
    elif k == KEY_LEFT:
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

      my,mx = keys[1:3]
      lbutton = 1 if keys[3]&1 else 0
      rbutton = 1 if keys[3]&2 else 0
      
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
          self.touch_mouse= False
        else:
          if abs(self.mouse_spoint - my) > 10:
            lines = (self.mouse_spoint - my) //10 + 1
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
            lines = (self.slide_spoint - keys[0]) //4 + 1
            self.scroll_by(self.line_height * lines)
            self.slide_spoint = keys[0]
            


      #if self.auto_scroll:
      #  self.scroll_by(self.scroll_speed)

      # save position periodically
      now = time.ticks_ms()
      if time.ticks_diff(now, last_save) > 30000:
        self.save_position()
        last_save = now
      
      if not self.v.active:
        pdeck.delay_tick(100)
      else:
        time.sleep(0.1)
        #pdeck.delay_tick(15)

    self.save_position()


def main(vs, args_in):
  v = vs.v
  el = elib.esclib()

  parser = argparse.ArgumentParser(
            description='Book Reader')
  parser.add_argument('-v', '--vertical',action='store_true', help='Japanese vertical style')
  parser.add_argument('-f', '--font',action='store', default = 'cen1' , help='Specify font. Options are : uni (unicode), lub1, lub2, cen1, cen2')
  parser.add_argument('filename', args='*',  help='filename to read')

  args = parser.parse_args(args_in[1:])

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  # Parse paths from args
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
  
