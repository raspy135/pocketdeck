import os
import mouse
import sys
import re
import datetime
import time
import math
import esclib as elib
import pdeck
import pdeck_utils

DAY_SEC = 60 * 60 * 24

def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

class graph_diary:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.reversed = 1
    self.mouse = mouse.mouse(self.v)
    self.last_mouse_active = False
    self.month_list = (
      "", "January", "Febrary", "March", "April",
      "May", "June", "July", "August", "September",
      "October", "November", "December"
    )

    self.goffset = [0, 10]
    self.groffset = [0, 140]

    self.re_date = re.compile("^(\#+)\\s+<(.+)>")
    self.re_item = re.compile("^-\\s*\[(.+)\]\\s+(.+)")

    self.org_filename = None

    self.shifted_day = None
    self.update_time()

    self.task_list = {}
    self.n_task_list = {}
    self.n_task_list_keys = []
    self.cur_n_task = None

    # Render cache.  update() is called frequently, so all month/day lookup,
    # min/max calculation and graph point scaling are done when the file/month
    # changes, not every frame.
    self.month_title = ""
    self.month_days = []
    self.task_rows = []
    self.graph_task_keys = []
    self.graph_tabs = []
    self.graph_cache = {}

    self.loaded = False
    self.loaded_updated = False

  # ---------------------------
  # Time / month navigation
  # ---------------------------
  def update_time(self):
    ctime = time.gmtime(time.time() + 60*15*pdeck_utils.timezone)
    self.hour = ctime[3]
    self.year = ctime[0]
    self.month = ctime[1]
    self.day = ctime[2]
    self.week = ctime[6]
    self.minute = ctime[4]
    self.second = ctime[5]
    self.micro = 0

  def update_shifted_day(self, offset):
    year = self.shifted_day.year
    month = self.shifted_day.month + offset
    while month < 1:
      year -= 1
      month += 12
    while month > 12:
      year += 1
      month -= 12
    self.shifted_day = datetime.date(year, month, 1)

  def find_last_date(self, filename):
    curdate = None
    if not file_exists(filename):
      return False
    with open(filename, 'r') as file:
      for line in file:
        if not line.startswith('#'):
          continue
        head = self.re_date.search(line)
        if not head:
          continue
        date_string = head.group(2)
        curdate = datetime.date.fromisoformat(date_string[0:10])
        break

    if curdate:
      self.shifted_day = datetime.date(curdate.year, curdate.month, 1)
    return True

  # ---------------------------
  # Parsing
  # ---------------------------
  def _reset_state_for_parse(self, filename):
    self.loaded = False
    self.loaded_updated = False

    self.org_filename = filename

    self.task_list = {}
    self.n_task_list = {}
    self.n_task_list_keys = []
    self.cur_n_task = None

    self.month_title = ""
    self.month_days = []
    self.task_rows = []
    self.graph_task_keys = []
    self.graph_tabs = []
    self.graph_cache = {}

  def _month_matches(self, d):
    return (d.year == self.shifted_day.year and d.month == self.shifted_day.month)

  def _date_key(self, d):
    return str(d.year) + '-' + str(d.month) + '-' + str(d.day)

  def _parse_value(self, result):
    # returns either:
    #  - None (non-numeric, treat as checkbox/string)
    #  - float (numeric)
    #  - ('time', float_hours) for HH:MM style
    try:
      fields = result.split(":")
      if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
        hours = float(fields[0]) + float(fields[1]) / 60.0
        return ('time', hours)
    except Exception:
      pass

    try:
      return float(result)
    except ValueError:
      return None

  def _store_numeric(self, task_name, date_key, fval):
    if task_name not in self.n_task_list:
      self.n_task_list[task_name] = {}

    # special-case conversion for weight
    if task_name == 'Weight' and (not isinstance(fval, tuple)) and fval < 100:
      fval *= 2.204
    self.n_task_list[task_name][date_key] = fval

  def _store_text(self, task_name, date_key, result):
    if task_name not in self.task_list:
      self.task_list[task_name] = {}
    self.task_list[task_name][date_key] = result

  def parse_file(self, filename):
    self._reset_state_for_parse(filename)
    self.date_list = []
    curdate = None
    month_found = False
    with open(filename, 'r') as file:

      # pass 1 get date order
      for line in file:
        if len(line) == 0:
          continue
        # date header
        if line.startswith('#'):
          head = self.re_date.search(line)
          if head:
            date_string = head.group(2)
            curdate = datetime.date.fromisoformat(date_string[0:10])
            self.date_list.append(curdate)
          continue
      if len(self.date_list) > 1 and self.date_list[0] < self.date_list[1]:
        self.reversed = -1

      # pass 2 collect only the displayed month
      file.seek(0,0)
      ct = -1
      for line in file:
        if len(line) == 0:
          continue

        # date header
        if line.startswith('#'):
          head = self.re_date.search(line)
          if head:
            date_string = head.group(2)
            curdate = datetime.date.fromisoformat(date_string[0:10])
            ct += 1
          continue

        if not curdate:
          continue

        # only parse current shifted month
        if not self._month_matches(curdate):
          if month_found:
            break
          continue
        month_found = True

        # task line
        if not line.startswith('-'):
          continue

        match = self.re_item.search(line)
        if not match:
          continue

        result = match.group(1)
        task_name = match.group(2)
        result_list = result.split(",")
        for i, result in enumerate(result_list):
          offset = i if self.reversed else -i
          date_key = self._date_key(curdate - datetime.timedelta(days = offset))
          fval = self._parse_value(result)
          if fval is None:
            self._store_text(task_name, date_key, result)
          else:
            self._store_numeric(task_name, date_key, fval)

    self.n_task_list_keys = sorted(self.n_task_list)
    self._build_render_cache()
    self.loaded = True

  # ---------------------------
  # Cached rendering data
  # ---------------------------
  def _build_month_days(self):
    self.month_days = []
    if self.shifted_day is None:
      return

    d = self.shifted_day
    month = d.month
    while d.month == month:
      self.month_days.append((self._date_key(d), d.day))
      d = d + datetime.timedelta(days = 1)

  def _build_task_cache(self):
    self.task_rows = []
    tl = sorted(self.task_list)

    for task in tl:
      tdata = self.task_list[task]
      boxes = []
      for dt, day in self.month_days:
        checked = False
        today = (self.shifted_day.year == self.year and self.shifted_day.month == self.month and day == self.day)
        if dt in tdata:
          val = tdata[dt]
          if val == 'X' or val == 'x':
            checked = True
        boxes.append((self.goffset[0] + 70 + day * 10, checked, today))
      self.task_rows.append((task[:10], boxes))

  def _entry_value(self, entry):
    if isinstance(entry, tuple) and entry[0] == 'time':
      return entry[1]
    return entry

  def _entry_format(self, entry):
    if isinstance(entry, tuple) and entry[0] == 'time':
      val = entry[1]
      minutes = int(val * 60)
      return "%d:%02d" % (minutes // 60, minutes % 60)
    return "%.1f" % entry

  def _build_graph_cache(self):
    self.graph_cache = {}
    self.graph_task_keys = sorted(self.n_task_list)
    self.graph_tabs = []

    if len(self.graph_task_keys) == 0:
      self.cur_n_task = None
      return

    if self.cur_n_task not in self.n_task_list:
      self.cur_n_task = self.graph_task_keys[0]

    self.n_task_list_keys = self.graph_task_keys
    for i, key in enumerate(self.graph_task_keys):
      self.graph_tabs.append((self.groffset[0] + 20 + i * 90,
        self.groffset[0] + 10 + i * 90, key[:10], key))

    size = 60
    for task in self.graph_task_keys:
      tdata = self.n_task_list[task]
      raw_points = []
      min_entry = None
      max_entry = None
      min_val = None
      max_val = None

      for dt, day in self.month_days:
        if dt not in tdata:
          continue
        entry = tdata[dt]
        val = self._entry_value(entry)
        raw_points.append((day, entry, val))

        if min_val is None or val < min_val:
          min_val = val
          min_entry = entry
        if max_val is None or val > max_val:
          max_val = val
          max_entry = entry

      if min_val is None:
        continue

      points = []
      for day, entry, val in raw_points:
        if max_val == min_val:
          y = int(size / 2)
        else:
          y = size - int((val - min_val) * (size / (max_val - min_val)))
        points.append((self.groffset[0] + 70 + day * 10 + 4,
          self.groffset[1] + y + 20))

      self.graph_cache[task] = {
        'min_label': self._entry_format(min_entry),
        'max_label': self._entry_format(max_entry),
        'points': points
      }

  def _build_render_cache(self):
    self.update_time()

    shifted_day = self.shifted_day
    if shifted_day:
      self.month_title = self.month_list[shifted_day.month][:3]
    else:
      self.month_title = ""

    self._build_month_days()
    self._build_task_cache()
    self._build_graph_cache()

  # ---------------------------
  # Rendering helpers
  # ---------------------------
  def get_date_key(self, d, month):
    gmd = time.gmtime(d)
    if gmd[1] != month:
      return (None, None)
    dt = str(gmd[0]) + '-' + str(gmd[1]) + '-' + str(gmd[2])
    return (dt, gmd[2])

  def extract_entry(self, entry):
    if isinstance(entry, tuple) and entry[0] == 'time':
      val = entry[1]
      formatted = f'{int(val * 60) // 60}:{int(val * 60) % 60}'
    else:
      val = entry
      formatted = f'{val:.1f}'
    return {'value': val, 'format': formatted}

  # ---------------------------
  # Drawing
  # ---------------------------
  def _draw_month_title(self):
    self.v.set_draw_color(1)
    self.v.set_font("u8g2_font_profont29_mf")
    self.v.draw_str(self.goffset[0] + 10, self.goffset[1] + 30, self.month_title)

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return

    self.mouse.update()
    self.point = self.mouse.get_point()

    if (not e) and (self.loaded_updated or not self.loaded) and self.mouse.active == self.last_mouse_active and not self.mouse.active:
      self.v.finished()
      return

    self._draw_month_title()
    self.draw_tasklist()
    self.draw_graph()

    if self.mouse.active:
      x = self.point[0] // 10 * 10 + 85
      self.v.draw_str(x + 3, 16, "%d" % (self.point[0] // 10 + 1))
      self.v.set_dither(10)
      self.v.draw_line(x, 0, x, 240)
      self.v.set_dither(16)
    self.last_mouse_active = self.mouse.active

    if self.loaded:
      self.loaded_updated = True
    self.v.finished()

  def draw_graph(self):
    if len(self.graph_cache) == 0 or self.cur_n_task is None:
      return
    if self.cur_n_task not in self.graph_cache:
      return

    self.v.set_font("u8g2_font_profont15_mf")

    # task tabs
    for tx, bx, label, key in self.graph_tabs:
      self.v.draw_str(tx, self.groffset[1] + 14, label)
      if self.cur_n_task == key:
        self.v.set_draw_color(2)
        self.v.draw_box(bx, self.groffset[1] + 0, 90, 15)
        self.v.set_draw_color(1)

    cache = self.graph_cache[self.cur_n_task]

    # min/max labels for selected task
    self.v.draw_str(self.groffset[0] + 3, self.groffset[1] + 20 + 60, cache['min_label'])
    self.v.draw_str(self.groffset[0] + 3, self.groffset[1] + 20 + 14, cache['max_label'])

    # plot points for selected task
    last_point = None
    for new_point in cache['points']:
      if last_point:
        self.v.set_dither(8)
        self.v.draw_line(last_point[0] + 2, last_point[1] + 2, new_point[0] + 2, new_point[1] + 2)
        self.v.set_dither(16)

      self.v.draw_box(new_point[0], new_point[1], 4, 4)
      last_point = new_point

  def draw_tasklist(self):
    self.v.set_font("u8g2_font_profont15_mf")

    # Row labels
    for i, row in enumerate(self.task_rows):
      task = row[0]
      self.v.draw_str(self.goffset[0] + 3, self.goffset[1] + i * 16 + 40 + 14, task)

    # Day numbers
    for dt, day in self.month_days:
      if (day % 5) == 1:
        self.v.draw_str(self.goffset[0] + 70 + day * 10, self.goffset[1] + 35, str(day))

    # Task boxes
    for i, row in enumerate(self.task_rows):
      boxes = row[1]
      y = self.goffset[1] + i * 16 + 40
      for x, checked, today in boxes:
        if checked:
          self.v.set_dither(12)
          self.v.draw_box(x, y, 10, 16)
          self.v.set_dither(16)
        else:
          if today:
            self.v.set_dither(4)
            self.v.draw_box(x, y, 10, 16)
            self.v.set_dither(16)
          else:
            self.v.draw_frame(x, y, 10, 16)

  # ---------------------------
  # Input loop
  # ---------------------------
  def _read_key(self):
    keys = self.vs.read(1).encode('ascii')
    if keys != b'\x1b':
      return keys

    seq = [keys]
    seq.append(self.vs.read(1).encode('ascii'))
    if seq[-1] == b'[':
      seq.append(self.vs.read(1).encode('ascii'))
      if seq[-1] >= b'0' and seq[-1] <= b'9':
        seq.append(self.vs.read(1).encode('ascii'))
    return b''.join(seq)

  def _select_prev_numeric_task(self):
    if not self.cur_n_task:
      return
    prev = None
    for key in self.n_task_list_keys:
      if self.cur_n_task == key:
        if prev:
          self.cur_n_task = prev
        break
      prev = key

  def _select_next_numeric_task(self):
    if not self.cur_n_task:
      return
    rec_next = False
    for key in self.n_task_list_keys:
      if self.cur_n_task == key:
        rec_next = True
        continue
      if rec_next:
        self.cur_n_task = key
        break

  def keyevent_loop(self):
    while True:

      keys = self._read_key()
      self.loaded_updated = False
      self.loaded = False
      moffset = 0

      if keys == b'\x1b[A':
        moffset = -1
      elif keys == b'\x1b[B':
        moffset = 1
      elif keys == b'\x1b[D':
        self._select_prev_numeric_task()
      elif keys == b'\x1b[C':
        self._select_next_numeric_task()

      if moffset:
        self.update_shifted_day(moffset)
        self.parse_file(self.org_filename)

      if keys == b'q':
        break
      if keys == b'r':
        self.parse_file(self.org_filename)

      self.loaded = True

def main(vs, args):
  org_filename = "/sd/Documents/journal.md"
  if len(args) == 2:
    org_filename = args[1]

  v = vs.v
  el = elib.esclib()
  obj = graph_diary(vs)

  if obj.find_last_date(org_filename):

    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False))

    if obj.shifted_day is None:
      # fallback: current month if file had no date header
      obj.shifted_day = datetime.date(obj.year, obj.month, 1)

    obj.parse_file(org_filename)

    v.callback(obj.update)
    obj.keyevent_loop()
  else:
    print(f"{org_filename} was not found", file=vs)
  v.callback(None)
  v.print(el.display_mode(True))
