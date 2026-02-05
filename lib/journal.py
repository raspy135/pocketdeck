import os
import sys
import re
import datetime
import time
import math
import esclib as elib
import pdeck
import pdeck_utils

DAY_SEC = 60 * 60 * 24

class graph_diary:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v

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
      self.n_task_list_keys.append(task_name)
      if self.cur_n_task is None:
        self.cur_n_task = task_name

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

    curdate = None
    month_found = False

    with open(filename, 'r') as file:
      for line in file:
        if len(line) == 0:
          continue

        # date header
        if line.startswith('#'):
          head = self.re_date.search(line)
          if head:
            date_string = head.group(2)
            curdate = datetime.date.fromisoformat(date_string[0:10])
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

        date_key = self._date_key(curdate)
        fval = self._parse_value(result)

        if fval is None:
          self._store_text(task_name, date_key, result)
        else:
          self._store_numeric(task_name, date_key, fval)

    self.loaded = True

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
    shifted_day = self.shifted_day
    self.v.set_draw_color(1)
    self.v.set_font("u8g2_font_profont29_mf")
    month_str = self.month_list[shifted_day.month][:3]
    self.v.draw_str(self.goffset[0] + 10, self.goffset[1] + 30, f"{month_str}")

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return
    
    if (not e) and (self.loaded_updated or not self.loaded):
      self.v.finished()
      return

    shifted_day = self.shifted_day
    d = time.mktime((shifted_day.year, shifted_day.month, 1, 0, 0, 0, 0, 0))

    self._draw_month_title()
    self.draw_tasklist(d)
    self.draw_graph(d)

    if self.loaded:
      self.loaded_updated = True
    self.v.finished()

  def draw_graph(self, d):
    if len(self.n_task_list) == 0 or self.cur_n_task is None:
      return

    self.v.set_font("u8g2_font_profont15_mf")
    org_d = d
    month = time.gmtime(d)[1]

    tl = sorted(self.n_task_list)
    mm_list = {}
    mm_list_keys = []

    # pass 1: min/max per numeric task for this month
    while True:
      dt, _ = self.get_date_key(d, month)
      if not dt:
        break

      for task in tl:
        if dt not in self.n_task_list[task]:
          continue
        entry = self.extract_entry(self.n_task_list[task][dt])

        if task not in mm_list:
          mm_list_keys.append(task)
          mm_list[task] = [entry, entry]
        else:
          if mm_list[task][0]['value'] > entry['value']:
            mm_list[task][0] = entry
          if mm_list[task][1]['value'] < entry['value']:
            mm_list[task][1] = entry

      d += DAY_SEC

    # pass 2: task tabs + plot
    size = 60
    last_point = [0, 0]
    d = org_d

    # task tabs
    i = 0
    for key in mm_list_keys:
      self.v.draw_str(self.groffset[0] + 20 + i * 90, self.groffset[1] + 14, key[:10])
      if self.cur_n_task == key:
        self.v.set_draw_color(2)
        self.v.draw_box(self.groffset[0] + 10 + i * 90, self.groffset[1] + 0, 90, 15)
        self.v.set_draw_color(1)
      i += 1

    # min/max labels for selected task
    cur_key = self.cur_n_task
    self.v.draw_str(self.groffset[0] + 3, self.groffset[1] + 20 + size, f"{mm_list[cur_key][0]['format']}")
    self.v.draw_str(self.groffset[0] + 3, self.groffset[1] + 20 + 14, f"{mm_list[cur_key][1]['format']}")

    # plot points for selected task
    while True:
      dt, day = self.get_date_key(d, month)
      if not dt:
        break

      if dt in self.n_task_list[cur_key]:
        entry = self.extract_entry(self.n_task_list[cur_key][dt])
        minmax = mm_list[cur_key]

        if minmax[1]['value'] == minmax[0]['value']:
          y = int(size / 2)
        else:
          y = size - int((entry['value'] - minmax[0]['value']) * (size / (minmax[1]['value'] - minmax[0]['value'])))

        new_point = [self.groffset[0] + 70 + day * 10, self.groffset[1] + y + 20]

        if last_point[0] != 0:
          self.v.set_dither(8)
          self.v.draw_line(last_point[0] + 2, last_point[1] + 2, new_point[0] + 2, new_point[1] + 2)
          self.v.set_dither(16)

        self.v.draw_box(new_point[0], new_point[1], 4, 4)
        last_point = new_point

      d += DAY_SEC

  def draw_tasklist(self, d):
    self.v.set_font("u8g2_font_profont15_mf")
    tl = sorted(self.task_list)

    for i, task in enumerate(tl):
      self.v.draw_str(self.goffset[0] + 3, self.goffset[1] + i * 16 + 40 + 14, task[:10])

    month = time.gmtime(d)[1]
    while True:
      gmd = time.gmtime(d)
      if gmd[1] != month:
        break

      dt = str(gmd[0]) + '-' + str(gmd[1]) + '-' + str(gmd[2])
      day = gmd[2]

      today = (gmd[0] == self.year and gmd[1] == self.month and gmd[2] == self.day)

      if (day % 5) == 1:
        self.v.draw_str(self.goffset[0] + 70 + day * 10, self.goffset[1] + 35, str(day))

      for i, task in enumerate(tl):
        checked = False
        if dt in self.task_list[task]:
          val = self.task_list[task][dt]
          if val == 'X' or val == 'x':
            checked = True

        x = self.goffset[0] + 70 + day * 10
        y = self.goffset[1] + i * 16 + 40

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

      d += DAY_SEC

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

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  obj.find_last_date(org_filename)
  if obj.shifted_day is None:
    # fallback: current month if file had no date header
    obj.shifted_day = datetime.date(obj.year, obj.month, 1)

  obj.parse_file(org_filename)

  v.callback(obj.update)
  obj.keyevent_loop()

  v.callback(None)
  v.print(el.display_mode(True))

