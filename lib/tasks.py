import re
import datetime
import time
import math
import pdeck
import esclib as elib
import xbmreader
import fontloader
import pdeck_utils
import os

def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

class tasks_card:
  def __init__(self, vs):
    self.vs = vs
    
    fontname = 'font_unifont_japanese3'
    fontloader.load(fontname)
    self.font = fontloader.font_list[fontname]
    
    self.updated = True
    self.title_width = 50
    self.detail_width = 48
    self.tasks=[]
    self.selected = 0
    self.scroll_head = 0
    self.mode = 'list'
    self.icons = {}
    self.icons['ACTIVE'] = xbmreader.read_xbmr("/sd/lib/data/active.xbmr")
    self.icons['RSPN'] = xbmreader.read_xbmr("/sd/lib/data/response.xbmr")
    self.icons['DONE'] = xbmreader.read_xbmr("/sd/lib/data/checked.xbmr")
    
  def parse_tasks(self,filename):
    self.filename = filename
    tasks = []
    group = ""
    current = None
    due_re = re.compile("(DUE|DEADLINE): <(.+)>")
    if not file_exists(filename):
      print(f"{filename} not found", file=self.vs)
      return False
    with open(filename, "r") as f:
      for raw in f:
        line = raw.rstrip("\n")

        if line.startswith("# GROUP "):
          if current:
            tasks.append(current)
          group = line[len("# GROUP "):]
          current = {
            "group": group,
            "group_title": True,
            "status": None,
            "title": group,
            "due": "",
            "lines": []
          }
          tasks.append(current)
          current = None
          continue

        if line.startswith("## "):
          if current:
            tasks.append(current)
          head = line[3:]
          parts = head.split(" ", 1)
          status = parts[0]
          if status not in self.icons:
            parts[1] = parts[0] + ' ' + parts[1]
          title = parts[1] if len(parts) > 1 else ""
          current = {
            "group": group,
            "group_title": False,
            "status": status,
            "title": title,
            "due": "",
            "lines": []
          }
          continue

        if current is None:
         continue
        m = due_re.match(line.strip())
        if m:
          date_string = m.group(2)
          
          duedate = datetime.date.fromisoformat(date_string[0:10]) 
          #print("ds = f{date_string)")
          tnow = time.localtime(time.time() + 60*15*pdeck_utils.timezone)
          now = datetime.date(tnow[0],tnow[1],tnow[2])
          time_diff = duedate - now
          time_diff_hours = math.floor(time_diff.total_seconds() / 3600)
          current["due"] = time_diff_hours
          current["due_string"] = date_string
          #current["due"] = m.group(1)
          continue
        v = self.vs.v
        while True:
          actual_width = self.detail_width
          
          while True:
            d_line = line[:actual_width]
            if v.get_utf8_width(d_line) < 390:
              break
            actual_width -= 1
          current["lines"].append(d_line)
          if len(line) > actual_width:
            line = line[actual_width:]
            continue
          break

    if current:
      tasks.append(current)

    self.tasks = tasks
    while self.tasks[self.selected]['group_title']:
      self.selected += 1
    return True

  def draw_icon(self, status, x,y, flip = False):
    v = self.vs.v
    if not status in self.icons:
      return
    image = self.icons[status]
    col = 1 if flip else 0
    v.set_draw_color(col)
    v.draw_xbm(x,y, image[1], image[2], image[3])
    v.set_draw_color(1)

  def update(self,e):
    v = self.vs.v
    if not v.active:
      v.finished()
      return

    # Skip redraw to save power
    # Redraw can be skipped when screen is 
    # not updated (e.g., just waiting for key)
    # and redraw is not requested by system 
    # (e is False)
    if (not e) and (not self.updated):
      v.finished()
      return

    #v.set_draw_color(1)
    v.set_font(self.font)#"u8g2_font_profont15_mf")
    #v.draw_utf8(5, 15, "Task List")

    if self.mode == "list":
      y = 32
      for i, t in enumerate(self.tasks):
        if i < self.scroll_head:
          continue

        if t['group_title']:
          v.set_dither(3)
          v.set_draw_color(1)
          v.draw_box(0, y - 25, 399, 8)
          v.set_dither(16)
          v.draw_utf8(5, y-5, str(t['title']))
          y += 32
          continue

        #print(t)
        due = False
        
        if t['due'] != '' and t['status'] != 'DONE':
          x = 38
          if t['due'] < 0:
            num_loop = 0
            due = True
          else:
            num_loop = t['due'] // 24
          while num_loop >=28:
            v.draw_box(x,y-25,20,10)
            num_loop -= 28
            x+=24
          
          while num_loop >=7:
            v.draw_box(x,y-20,10,5)
            num_loop -= 7
            x+=16
          
          while num_loop > 0:
            v.draw_disc(x,y-20,4,0xf)
            num_loop -= 1
            x+=8
          v.draw_utf8(x, y-15, str(t['due']//24))
          if t['due'] < 0:
            v.draw_utf8(x+1, y-15, str(t['due']//24))

        txt = f'{t["title"]}'
        v.set_bitmap_mode(1)
        
        v.draw_utf8(35, y, txt[:65])
        if due:
          v.draw_utf8(36, y, txt[:65])
        v.set_bitmap_mode(0)
        self.draw_icon(t['status'], 0, y-32)
            
        if i == self.selected:
          v.set_draw_color(2)
          v.draw_box(32, y - 12, 396, 18)
          v.set_draw_color(1)
        y += 32
        if y >= 240 + 32:
          break
    else:
      t = self.tasks[self.selected]
      v.draw_utf8(5, 18, t["title"][:50])
      v.draw_utf8(5, 34, f'Status: {t["status"]}')
      if t['due'] != '':
        v.draw_utf8(5, 50, f'Due: {t["due"]//24} days ({t['due_string']})')
      y = 70
      for line in t["lines"][:10]:
        v.draw_utf8(5, y, line[:60])
        y += 16
    self.updated = False
    v.finished()

  def read_key(self):
    k = self.vs.read(1).encode("ascii")
    if k != b'\x1b':
      return k
    seq = [k, self.vs.read(1).encode("ascii"), self.vs.read(1).encode("ascii")]
    if seq[-1] >= b'0' and seq[-1] <= b'9':
      seq.append(self.vs.read(1).encode("ascii"))
    return b"".join(seq)

  def move_cursor(self, offset):
    new_pos = self.selected + offset
    if new_pos < 0:
      new_pos = 0
    if new_pos > len(self.tasks) - 1:
      new_pos = len(self.tasks) - 1
    
    while self.tasks[new_pos]['group_title']:
      new_pos += 1 if offset > 0 else -1
      if new_pos == -1:
        self.selected = 1
        return

    self.selected = new_pos
            
  def loop(self):
    while True:
      self.updated = True
      k = self.read_key()


      if k == b'r':
        self.parse_tasks(self.filename)
        continue
        
      if self.mode == "list":
        if k == b'\x1b[D' or k == b'\x08' or k == b'b' or k == b'\x1b':
          break
        elif k == b'\x1b[6~':
          self.move_cursor(5)
        elif k == b'\x1b[5~':
          self.move_cursor(-5)
        elif k == b'\x1b[A' and self.selected > 0:
          self.move_cursor(-1)
        elif k == b'\x1b[B' and self.selected + 1 < len(self.tasks):
          self.move_cursor(1)
        elif k == b'\r' or k == b'\n' or k == b'\x1b[C':
          self.mode = "detail"
        elif k == b'q':
          break
        if self.selected - self.scroll_head > 5:
          self.scroll_head = self.selected - 5
        if self.scroll_head - self.selected > -1:
          self.scroll_head = self.selected - 1
          self.scroll_head = 0 if self.scroll_head < 0 else self.scroll_head
      else:
        if k == b'\x1b[D' or k == b'\x08' or k == b'b' or k == b'\x1b':
          self.mode = "list"
        elif k == b'q':
          break



def main(vs, args):
  filename = "/sd/Documents/tasks.md"
  if len(args) > 1:
    filename = args[1]

  v = vs.v
  el = elib.esclib()

  obj = tasks_card(vs)
  
  if obj.parse_tasks(filename):
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))

    v.callback(obj.update)
    obj.loop()
    v.callback(None)

  v.print(el.display_mode(True))
  #v.print(el.raw_mode(False))


  
