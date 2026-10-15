# Pocket Deck book list menu for the reader app.
#
# Opened by `reader` when it is launched without a file argument. It browses
# /sd/book on the left 2/3 of the screen. Folders are shown as rows (tagged
# [DIR]) and can be entered to reach books in sub-directories; a `..` row goes
# back up, and browsing never leaves /sd/book. The right 1/3 is a
# "properties" section for the selected item: a book's filename, size, reading
# progress, vertical flag and font (a folder shows its name and path).
#
# Keys:
#   Up / Down        : move the cursor between rows
#   Left / Right     : move the cursor between the row and its two properties
#                      (VERTICAL, FONT)
#   A / Enter        : open the book / enter the folder, or change the focused
#                      property
#   BS / B           : step back to the row, then quit
#   q                : quit
#   Touchpad         : move the pointer, tap a row to select it, tap the
#                      selected row again to open it / enter it
#
# Design follows /sd/lib/skills/dashboard_design.md: a flat 1-bit composition,
# a solid inverted header bar, measured text and an animated entrance. Geometry
# is fixed; only the "how much" changes per frame.

import os
import array
import math
import time
import ujson
import anm
import pdeck

import reader as reader_mod

W = 400
H = 240

BOOK_ROOT = "/sd/book"

# A book is any file the reader can open. Folders are detected from the
# directory entry type, never by name.
BOOK_EXTS = ('.txt', '.md', '.markdown')


def _is_readable(name):
  n = name.lower()
  for ext in BOOK_EXTS:
    if n.endswith(ext):
      return True
  return False


FONT_C = 'u8g2_font_profont15_mf'
FONT_T = 'u8g2_font_profont22_mf'

# The font names the reader understands, in the order the font chip cycles them.
FONTS = ('cen1', 'cen2', 'uni', 't15', 'lub1', 'lub2')
FONT_BADGE = {'uni': 'U', 't15': 'T', 'lub1': 'L1', 'lub2': 'L2', 'cen1': 'C1', 'cen2': 'C2'}

HEAD_H = 21
FOOT_H = 22
ROW_H = 44

# The list is the left 60%; the properties section is the right 40%.
LIST_W = 240
PANEL_X = 240
PANEL_W = W - PANEL_X
LIST_TOP = HEAD_H + 6
LIST_BOT = H - FOOT_H

# Progress ring geometry (fixed, so its fan is built once).
RING_CX = PANEL_X + PANEL_W - 34
RING_CY = 138
RING_RO = 24
RING_RI = 16
RING_SEGS = 40


# ---- layout helpers — always measure text before placing it ------------------

def clamp01(t):
  return 0.0 if t < 0 else (1.0 if t > 1 else t)


def center_x(v, x, w, text):
  return x + (w - v.get_utf8_width(text)) // 2


def right_x(v, right_edge, text):
  return right_edge - v.get_utf8_width(text)


def fit(v, text, max_w):
  # Truncate with an ellipsis so a title never spills past max_w pixels.
  if v.get_utf8_width(text) <= max_w:
    return text
  while text and v.get_utf8_width(text + '..') > max_w:
    text = text[:-1]
  return text + '..'


def _human_size(n):
  if n >= 1048576:
    return '%.1fM' % (n / 1048576.0)
  if n >= 1024:
    return '%dk' % ((n + 512) // 1024)
  return '%db' % n


def _join(d, name):
  if d.endswith('/'):
    return d + name
  return d + '/' + name


def _parent(d):
  # The directory above d, but never above BOOK_ROOT.
  if not d or d == BOOK_ROOT:
    return BOOK_ROOT
  up = d.rsplit('/', 1)[0]
  if len(up) < len(BOOK_ROOT):
    return BOOK_ROOT
  return up


def _rel(d):
  # d as a path relative to BOOK_ROOT ('' at the root, else '/sub/dir').
  if not d or d == BOOK_ROOT:
    return ''
  if d.startswith(BOOK_ROOT):
    return d[len(BOOK_ROOT):]
  return d


def _build_ring(cx, cy, r_out, r_in, segs):
  # A fan of `segs` trapezoid quads between r_in and r_out, sweeping 360 deg
  # clockwise from 12 o'clock. Built once (no trig per frame); the same trick
  # as /sd/lib/examples/dashboard_gauge.py.
  arr = array.array('h', bytearray(segs * 8 * 2))
  a0 = -90.0
  da = 360.0
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


def _load_state():
  try:
    with open(reader_mod.READER_STATE_FILE, "r") as f:
      return ujson.loads(f.read())
  except:
    return {}


def _save_state(state):
  try:
    os.makedirs("/config")
  except:
    pass
  try:
    with open(reader_mod.READER_STATE_FILE, "w") as f:
      ujson.dump(state, f, separators=(',\n', ': '))
  except:
    pass


class BookMenu:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.state = _load_state()
    self.rows = []
    self.crow = 0
    self.col = 0          # 0 = the book row, 1 = VERTICAL, 2 = FONT
    self.curdir = BOOK_ROOT
    self.pending = None
    self.dirty = True
    self.touching = False
    self.pointer = (0, 0)

    # The progress ring is a fixed fan of quads, built once.
    self.ring_band = _build_ring(RING_CX, RING_CY, RING_RO, RING_RI, RING_SEGS)

    # One shared timeline: the card's fields reveal in turn and the progress
    # ring sweeps up to the real reading position.
    self.seq = anm.anm_sequencer()
    self.master = anm.anm_object(1100, {
      'f0':    [anm.ease_out, 0.0, 1.0],
      'f1':    [anm.ease_out, 0.0, 1.0],
      'f2':    [anm.ease_out, 0.0, 1.0],
      'f3':    [anm.ease_out, 0.0, 1.0],
      'f4':    [anm.ease_out, 0.0, 1.0],
      'sweep': [anm.ease_out, 0.0, 1.0],
    })
    self.seq.register('master', self.master)

    self.scroll_anm = anm.anm_object(180, {'y': [anm.ease_out, 0, 0]})
    self.seq.register('scroll', self.scroll_anm)
    self.target_off = 0

    self._reload()

  # ---- data -----------------------------------------------------------------

  def _reload(self):
    self.state = _load_state()
    try:
      os.mkdir(BOOK_ROOT)
    except:
      pass
    try:
      os.mkdir(self.curdir)
    except:
      pass

    dirs = []
    files = []
    try:
      for ent in os.ilistdir(self.curdir):
        name = ent[0]
        typ = ent[1] if len(ent) > 1 else 0
        if name in ('.', '..'):
          continue
        if typ & 0x4000:
          dirs.append(name)
        elif _is_readable(name):
          files.append(name)
    except:
      dirs = []
      files = []
    dirs.sort(key=lambda s: s.lower())
    files.sort(key=lambda s: s.lower())

    self.rows = []
    # A `..` row, except at the browsing root, so the user can climb back out.
    if self.curdir != BOOK_ROOT:
      self.rows.append({'kind': 'up', 'name': '..', 'title': '..', 'path': _parent(self.curdir)})
    for name in dirs:
      path = _join(self.curdir, name)
      self.rows.append({
        'kind': 'dir', 'name': name, 'title': name, 'path': path,
        'size': 0, 'prog': 0.0, 'pct': 0,
      })
    for name in files:
      path = _join(self.curdir, name)
      try:
        size = os.stat(path)[6]
      except:
        size = 0
      st = self.state.get(path, {})
      # Prefer the reader's own stored percentage when it is there; otherwise
      # derive it from the saved line position.
      if "pct" in st:
        prog = st.get("pct", 0) / 100.0
      else:
        lines = st.get("lines", 0)
        pos_line = st.get("pos_line", 0)
        if lines > 0:
          prog = (pos_line + 1) / float(lines)
        else:
          prog = 0.0
      if prog < 0:
        prog = 0.0
      if prog > 1:
        prog = 1.0
      title = name
      for ext in BOOK_EXTS:
        if title.lower().endswith(ext):
          title = title[:-len(ext)]
          break
      self.rows.append({
        'kind': 'file',
        'name': name,
        'title': title,
        'path': path,
        'size': size,
        'prog': prog,
        'pct': int(prog * 100 + 0.5),
        'font': st.get("font", self.state.get("_font", "cen1")),
        'vertical': bool(st.get("vertical", self.state.get("_vertical", False))),
        'last_read': st.get("last_read", 0),
      })

    # Folders first, then files; files keep the recency ordering the reader
    # stores (most recently read first, never-opened ones alphabetical).
    dirs_rows = []
    file_rows = []
    for r in self.rows:
      if r['kind'] == 'file':
        file_rows.append(r)
      else:
        dirs_rows.append(r)
    file_rows.sort(key=lambda r: (-r['last_read'], r['name'].lower()))
    self.rows = dirs_rows + file_rows

    if self.crow >= len(self.rows):
      self.crow = max(0, len(self.rows) - 1)
    if self.col and not self.rows:
      self.col = 0
    self._retarget()

  def _cur(self):
    if not self.rows:
      return None
    if self.crow < 0 or self.crow >= len(self.rows):
      return None
    return self.rows[self.crow]

  def _editable(self):
    # Only a real book has editable properties (vertical / font).
    row = self._cur()
    return bool(row) and row['kind'] == 'file'

  def _enter_dir(self, path):
    self.curdir = path
    self.crow = 0
    self.col = 0
    self._reload()
    self._replay()
    self.dirty = True

  def _set_book_prop(self, path, key, value):
    d = self.state.get(path, {})
    d[key] = value
    self.state[path] = d
    _save_state(self.state)

  # ---- animation ------------------------------------------------------------

  def _replay(self):
    self.master.seek(0.0)
    self.dirty = True

  def _field(self, i):
    # Per-field reveal on its own slice of the timeline.
    t = self.master.get_time()
    start = 0.12 + i * 0.09
    return clamp01((t - start) / 0.22)

  def _field_ready(self, i):
    return self._field(i) > 0.5

  # ---- scrolling ------------------------------------------------------------

  def _retarget(self):
    view_h = LIST_BOT - LIST_TOP
    total = len(self.rows) * ROW_H
    target = (self.crow - 2) * ROW_H
    max_off = total - view_h
    if max_off < 0:
      max_off = 0
    if target < 0:
      target = 0
    if target > max_off:
      target = max_off
    self.target_off = target
    self.scroll_anm = anm.anm_object(180, {'y': [anm.ease_out, self.scroll_anm.y, target]})
    self.seq.register('scroll', self.scroll_anm)

  def _animating(self):
    if self.master.get_time() < 1.0:
      return True
    return abs(self.scroll_anm.y - self.target_off) > 0.5

  def _move(self, delta):
    n = len(self.rows)
    if n == 0:
      return
    nc = self.crow + delta
    if nc < 0:
      nc = 0
    if nc >= n:
      nc = n - 1
    if nc == self.crow:
      return
    self.crow = nc
    self.col = 0
    self._retarget()
    self._replay()

  def _change_font(self, direction):
    row = self._cur()
    if not row or row['kind'] != 'file':
      return
    try:
      i = FONTS.index(row['font'])
    except:
      i = 0
    i = (i + direction) % len(FONTS)
    row['font'] = FONTS[i]
    self._set_book_prop(row['path'], 'font', row['font'])
    self.dirty = True

  def _toggle_vertical(self):
    row = self._cur()
    if not row or row['kind'] != 'file':
      return
    row['vertical'] = not row['vertical']
    self._set_book_prop(row['path'], 'vertical', row['vertical'])
    self.dirty = True

  # ---- drawing --------------------------------------------------------------

  def _draw_bar(self, x, y, w, h, prog):
    v = self.v
    v.set_dither(5)
    v.draw_box(x, y, w, h)
    if prog > 0:
      fw = int((w - 2) * prog)
      if fw > 0:
        v.set_dither(16)
        v.draw_box(x + 1, y + 1, fw, h - 2)
    v.set_dither(16)
    v.draw_frame(x, y, w, h)

  def _draw_row(self, row, y, selected):
    v = self.v
    v.set_dither(16)
    v.set_draw_color(1)
    if selected:
      # Cursor: a bright marker bar plus an outline around the whole row, so
      # the selection is easy to see.
      v.draw_box(2, y + 4, 3, ROW_H - 12)
      v.draw_frame(0, y + 1, LIST_W - 2, ROW_H - 5)
    v.set_font(FONT_C)
    if row['kind'] == 'file':
      name = fit(v, row['title'], LIST_W - 20)
      v.draw_str(10, y + 17, name)
      self._draw_bar(10, y + 24, 150, 8, row['prog'])
    elif row['kind'] == 'up':
      # The climb-out row: just a `..` marker.
      v.draw_str(10, y + 17, '..')
      self._draw_dotted(10, y + 26, LIST_W - 24)
    else:
      # A folder: a small tag plus the name.
      v.draw_str(10, y + 17, '[DIR]')
      tx = 10 + v.get_utf8_width('[DIR]') + 6
      name = fit(v, row['title'], LIST_W - tx - 8)
      v.draw_str(tx, y + 17, name)
      # A short rule under folder rows keeps the list rhythm even though a
      # folder has no progress to show.
      self._draw_dotted(10, y + 26, LIST_W - 24)

  def draw_list(self):
    v = self.v
    off = int(self.scroll_anm.y)
    for i, row in enumerate(self.rows):
      y = LIST_TOP + i * ROW_H - off
      if y + ROW_H < 0:
        continue
      if y > H:
        break
      self._draw_row(row, y, i == self.crow)

  def draw_header(self):
    v = self.v
    v.set_dither(16)
    v.set_draw_color(1)
    v.draw_box(0, 0, W, HEAD_H)
    v.set_draw_color(0)
    v.set_font(FONT_C)
    title = 'Book List'
    rel = _rel(self.curdir)
    if rel:
      title += ':' + rel
    v.draw_str(6, 15, fit(v, title, 150))
    pos = '%d/%d' % (self.crow + 1, len(self.rows)) if self.rows else 'empty'
    v.draw_str(right_x(v, LIST_W - 6, pos), 15, pos)
    v.set_draw_color(1)

  def draw_footer(self):
    v = self.v
    v.set_dither(16)
    v.set_draw_color(1)
    v.draw_box(0, H - FOOT_H, LIST_W, FOOT_H)
    v.set_draw_color(0)
    v.set_font(FONT_C)
    hint = 'A:open  L/R:prop  q:quit'
    v.draw_str(center_x(v, 0, LIST_W, hint), H - 7, hint)
    v.set_draw_color(1)

  # ---- properties section ---------------------------------------------------

  def _draw_dotted(self, x, y, w, step=4):
    v = self.v
    v.set_dither(16)
    px = x
    while px < x + w:
      v.draw_pixel(px, y)
      px += step

  def _draw_section_bar(self, x, y, w, h, text):
    v = self.v
    v.set_dither(16)
    v.draw_box(x, y, w, h)
    v.set_dither(16)
    v.set_draw_color(0)
    v.draw_str(x + 5, y + h - 4, text)
    v.set_draw_color(1)

  def _draw_label(self, x, y, text):
    v = self.v
    v.set_font(FONT_C)
    v.draw_str(x, y, text)

  def _draw_value(self, x, y, text):
    v = self.v
    v.set_font(FONT_T)
    v.draw_str(x, y, text)

  def _draw_ring(self, pct, sweep):
    # Flat donut: a quiet full track, then the value band drawn solid to the
    # real reading position. Drawn from the precomputed fan (no per-frame trig).
    v = self.v
    segs = RING_SEGS
    band = self.ring_band
    v.set_dither(4)
    for i in range(segs):
      v.draw_polygon(band[i * 8:(i + 1) * 8])

    frac = (pct / 100.0) * clamp01(sweep)
    k = int(segs * frac + 0.0001)
    if k > 0:
      v.set_dither(16)
      for i in range(k):
        v.draw_polygon(band[i * 8:(i + 1) * 8])
    v.set_dither(16)

    txt = '%d' % int(round(pct))
    v.set_font(FONT_C)
    v.draw_str(RING_CX - v.get_utf8_width(txt) // 2, RING_CY + 5, txt)

  def _draw_focus(self, x, y, w, h):
    v = self.v
    v.set_dither(16)
    v.draw_frame(x, y, w, h)
    v.draw_frame(x + 1, y + 1, w - 2, h - 2)

  def draw_panel(self):
    row = self._cur()
    v = self.v
    ox = PANEL_X

    # section header (solid, inverted — the standard title anchor)
    self._draw_section_bar(ox, 0, PANEL_W, HEAD_H, 'PROPERTIES')

    if not row:
      return

    if row['kind'] != 'file':
      # A folder (or the `..` climb row): show where it is, not a file's
      # properties. There is nothing editable here.
      label = 'PARENT' if row['kind'] == 'up' else 'FOLDER'
      y = 26
      if self._field_ready(0):
        self._draw_label(ox + 8, y + 12, label)
        self._draw_label(ox + 8, y + 30, fit(v, row['name'], PANEL_W - 16))
      y += 38
      self._draw_dotted(ox + 8, y, PANEL_W - 16)
      y += 4
      if self._field_ready(1):
        self._draw_label(ox + 8, y + 12, 'PATH')
        self._draw_label(ox + 8, y + 30, fit(v, _rel(row['path']) or '/', PANEL_W - 16))
      y += 38
      self._draw_dotted(ox + 8, y, PANEL_W - 16)
      return

    y = 26
    # -- FILENAME (small font — a long name would otherwise overflow) --------
    if self._field_ready(0):
      self._draw_label(ox + 8, y + 12, 'FILENAME')
      self._draw_label(ox + 8, y + 30, fit(v, row['name'], PANEL_W - 16))
    y += 38
    self._draw_dotted(ox + 8, y, PANEL_W - 16)
    y += 4

    # -- SIZE ---------------------------------------------------------------
    if self._field_ready(1):
      self._draw_label(ox + 8, y + 12, 'SIZE')
      self._draw_value(ox + 8, y + 30, _human_size(row['size']))
    y += 38
    self._draw_dotted(ox + 8, y, PANEL_W - 16)
    y += 4

    # -- PROGRESS -----------------------------------------------------------
    if self._field_ready(2):
      self._draw_label(ox + 8, y + 12, 'PROGRESS')
      self._draw_ring(row['pct'], self.master.sweep)
    y += 50
    self._draw_dotted(ox + 8, y, PANEL_W - 16)
    y += 4

    # -- VERTICAL (editable) ------------------------------------------------
    vy = y
    if self._field_ready(3):
      self._draw_label(ox + 8, vy + 12, 'VERTICAL')
      self._draw_value(ox + 8, vy + 30, 'YES' if row['vertical'] else 'NO')
      if self.col == 1:
        self._draw_focus(ox + 4, vy - 2, PANEL_W - 8, 36)
    y += 38
    self._draw_dotted(ox + 8, y, PANEL_W - 16)
    y += 4

    # -- FONT (editable) ----------------------------------------------------
    fy = y
    if self._field_ready(4):
      self._draw_label(ox + 8, fy + 12, 'FONT')
      self._draw_value(ox + 8, fy + 30, row['font'])
      if self.col == 2:
        self._draw_focus(ox + 4, fy - 2, PANEL_W - 8, 36)
    y += 38
    self._draw_dotted(ox + 8, y, PANEL_W - 16)

  def draw_pointer(self):
    if not self.touching:
      return
    v = self.v
    x, y = self.pointer
    v.set_dither(16)
    v.draw_circle(x, y, 5, 15)
    v.draw_h_line(x - 8, y, 16)
    v.draw_v_line(x, y - 8, 16)

  def draw(self):
    v = self.v
    v.clear_buffer()
    self.draw_list()
    self.draw_header()
    self.draw_footer()
    self.draw_panel()
    self.draw_pointer()
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

  def _read_key(self):
    ret = self.v.read_nb(1)
    if not ret or ret[0] <= 0:
      return None
    k = ret[1].encode('ascii')
    if k == b'\x1b':
      seq = [k, self.vs.read(1).encode('ascii')]
      if seq[-1] == b'[':
        seq.append(self.vs.read(1).encode('ascii'))
      return b''.join(seq)
    return k

  def handle_key(self, k):
    if k is None:
      return True
    if k == b'q':
      return False
    if k == b'\x08':
      if self.col > 0:
        self.col = 0
        self.dirty = True
        return True
      return False
    if k == b'\r':
      row = self._cur()
      if row and row['kind'] != 'file':
        # Folders and `..` are not editable; Enter enters the folder.
        if self.col != 0:
          self.col = 0
          self.dirty = True
        else:
          self._open_selected()
        return True
      if self.col == 1:
        self._toggle_vertical()
      elif self.col == 2:
        self._change_font(1)
      else:
        self._open_selected()
        return False
      return True
    if k == b'\x1b[A':
      self._move(-1)
    elif k == b'\x1b[B':
      self._move(1)
    elif k == b'\x1b[D':
      if self.col > 0:
        self.col -= 1
        self.dirty = True
    elif k == b'\x1b[C':
      if self.col < 2 and self._editable():
        self.col += 1
        self.dirty = True
    elif k == b'f' or k == b'F':
      self._change_font(1)
    elif k == b'v' or k == b'V':
      self._toggle_vertical()
    return True

  def _record_read(self, path):
    # Remember when a book was last opened, so the list can be sorted by
    # recency. The reader itself does not store this, so the menu does.
    d = self.state.get(path, {})
    d['last_read'] = int(time.time())
    self.state[path] = d
    _save_state(self.state)

  def _open_selected(self):
    row = self._cur()
    if not row:
      return
    if row['kind'] in ('dir', 'up'):
      self._enter_dir(row['path'])
      return
    self._record_read(row['path'])
    self.pending = row['path']

  # ---- touchpad -------------------------------------------------------------

  def _poll_touch(self):
    try:
      keys = self.v.get_tp_keys()
    except:
      return
    if not keys or len(keys) < 3:
      return
    tx = keys[2]
    ty = keys[1]
    touching = not (tx == 255 or ty == 255)
    if touching:
      px = tx * 4
      py = ty * 3
      if px > W - 1:
        px = W - 1
      if py > H - 1:
        py = H - 1
      if not self.touching or self.pointer != (px, py):
        self.pointer = (px, py)
        self.dirty = True
      self.touching = True
      return
    if self.touching:
      self.touching = False
      self.dirty = True
      self._handle_tap(self.pointer[0], self.pointer[1])

  def _handle_tap(self, x, y):
    if not self.rows or x >= PANEL_X:
      return
    off = int(self.scroll_anm.y)
    row_idx = (y - LIST_TOP + off) // ROW_H
    if row_idx < 0 or row_idx >= len(self.rows):
      return
    if row_idx == self.crow:
      self._open_selected()
      return
    self.crow = row_idx
    self.col = 0
    self._retarget()
    self._replay()

  def _open_book(self, path):
    row = None
    for r in self.rows:
      if r['path'] == path:
        row = r
        break
    font = row['font'] if row else 'cen1'
    vertical = row['vertical'] if row else False

    rd = reader_mod.Reader(self.v, self.vs, [path], vertical, font, False)
    self.v.callback(rd.update)
    try:
      rd.load_file(path)
      rd.loop()
    finally:
      self.v.callback(None)

  def loop(self):
    # `pending` is set when a book is chosen; folder changes just redraw in
    # place, so the loop only ends when a book is opened or the user quits.
    while True:
      if self.pending:
        return
      k = self._read_key()
      if k is not None:
        if not self.handle_key(k):
          break
      self._poll_touch()
      if self.touching:
        self.dirty = True
      pdeck.delay_tick(6)

  def run(self):
    # Menu mode: keep showing the list, and hand off to the reader when a book
    # is chosen; come back to the list when that book is closed.
    while True:
      self.pending = None
      self._replay()
      self.v.callback(self.update)
      self.dirty = True
      try:
        self.loop()
      finally:
        self.v.callback(None)

      if not self.pending:
        break
      path = self.pending
      self.pending = None
      self._open_book(path)
      self._reload()
      # The book just closed now has the newest read time; put the cursor on it
      # (it stays in the folder it was opened from).
      self.col = 0
      for i, r in enumerate(self.rows):
        if r.get('path') == path:
          self.crow = i
          break
      self._retarget()
      self.dirty = True
