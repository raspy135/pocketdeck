# Pocket Deck text reader app
# - UTF-8 support
# - Remembers read position per file
# - Markdown style **bold** support via fake bold rendering
#
# Keys:
#   Up/Down : scroll
#   Left/Right : page up/down
#   PageUp/PageDown : page up/down
#   q / Backspace : quit
#   n / p : next / previous file

import fontloader
import os
import time
import ujson
import pdeck
import esclib as elib
import argparse
import anm

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

  return data.decode("utf-8")


def _load_state():
  try:
    with open(READER_STATE_FILE, "r") as f:
      return ujson.loads(f.read())
  except:
    return {}


def _save_state(state):
  #print(state)
  try:
    os.makedirs("/config")
  except:
    pass
  try:
    with open(READER_STATE_FILE, "w") as f:
      ujson.dump(state, f, separators = (',\n',': '))
  except:
    pass


def _split_lines(text):
  # Preserve paragraphs but normalize line endings
  text = text.replace("\r\n", "\n").replace("\r", "\n")
  return text.split("\n")


def _is_md_path(path):
  try:
    return path.lower().endswith(".md") or path.lower().endswith(".markdown")
  except:
    return False


def _parse_md_table_row(line):
  """Return Markdown table cells, or None if line is not a table row."""
  if line is None or "|" not in line:
    return None
  t = line.strip()
  if t == "":
    return None
  if t.startswith("|"):
    t = t[1:]
  if t.endswith("|"):
    t = t[:-1]
  cells = []
  for c in t.split("|"):
    cells.append(c.strip())
  if len(cells) < 2:
    return None
  return cells


def _is_md_table_separator(line):
  cells = _parse_md_table_row(line)
  if not cells:
    return False
  for c in cells:
    t = c.strip()
    if t == "":
      return False
    # Markdown allows :---, ---:, :---:
    t = t.replace(":", "")
    if len(t) < 3:
      return False
    for ch in t:
      if ch != "-":
        return False
  return True


def _table_text_width(v, text):
  try:
    w = v.get_utf8_width(text) 
    if w < 7:
      w+=1
    return w
  except:
    return len(text) * 8


def _fit_text_width(v, text, max_w):
  """Trim text so it fits max_w pixels. Adds .. when trimmed."""
  if max_w <= 0:
    return ""
  if _table_text_width(v, text) <= max_w:
    return text
  ell = ".."
  ell_w = _table_text_width(v, ell)
  if max_w <= ell_w:
    return ""
  out = ""
  w = 0
  for ch in text:
    cw = _table_text_width(v, ch)
    if w + cw + ell_w > max_w:
      break
    out += ch
    w += cw
  return out + ell


def _wrap_text_to_width(v, text, max_w):
  """Wrap text to width. Returns list of strings."""
  if text == "":
    return [""]
  out = []
  n = len(text)
  start = 0

  while start < n:
    cur_w = 0
    end = start
    last_space = -1

    while end < n:
      ch = text[end]
      cw = _table_text_width(v, ch)
      if cur_w + cw > max_w and end > start:
        break
      cur_w += cw
      if ch == ' ':
        last_space = end
      end += 1

    if end < n and last_space >= start:
      cut = last_space
      seg = text[start:cut].strip()
      if seg == "":
        seg = text[start:end].strip()
        start = end
      else:
        start = cut + 1
      out.append(seg)
    else:
      seg = text[start:end]
      if seg == "" and end < n:
        seg = text[start:start + 1]
        start += 1
      else:
        start = end
      out.append(seg.strip())

    while start < n and text[start] == ' ':
      start += 1

  if not out:
    return [""]
  return out


def _cell_plain_text(cell):
  if cell is None:
    return ""
  return cell


def _make_md_table_rows(v, rows, max_width, line_height):
  """Create renderable table row objects from parsed Markdown table rows."""
  if not rows:
    return []
  col_count = 0
  for r in rows:
    if len(r) > col_count:
      col_count = len(r)
  if col_count < 2:
    return []

  pad = 5
  border_w = col_count + 1

  raw_w = [1] * col_count
  for r in rows:
    for i in range(col_count):
      txt = r[i] if i < len(r) else ""
      lines = txt.split("\n")
      for line in lines:
        w = _table_text_width(v, line)
        if w > raw_w[i]:
          raw_w[i] = w

  total_raw = 0
  for w in raw_w:
    total_raw += w

  usable = max_width - border_w - pad * 2 * col_count
  if usable < col_count * 16:
    usable = col_count * 16

  col_w = []
  if total_raw + pad * 2 * col_count + border_w <= max_width:
    for w in raw_w:
      col_w.append(w + pad * 2)
  else:
    min_content_w = 24
    remaining = usable - min_content_w * col_count
    if remaining < 0:
      remaining = 0
    for w in raw_w:
      extra = 0
      if total_raw > 0:
        extra = int(remaining * w / total_raw)
      content_w = min_content_w + extra
      col_w.append(content_w + pad * 2)

  out = []
  for ri, r in enumerate(rows):
    cells = []
    wrapped_cells = []
    row_lines = 1
    for i in range(col_count):
      txt = r[i] if i < len(r) else ""
      cells.append(txt)
      inner_w = col_w[i] - pad * 2
      wrapped = _wrap_text_to_width(v, _cell_plain_text(txt), inner_w)
      if len(wrapped) < 1:
        wrapped = [""]
      wrapped_cells.append(wrapped)
      if len(wrapped) > row_lines:
        row_lines = len(wrapped)

    total_w = col_count + 1
    for w in col_w:
      total_w += w

    vlines = []
    text_x = []
    text_y = []
    cur_x = 1
    for ci in range(col_count):
      text_x.append(cur_x + pad)
      text_y.append(line_height)
      cur_x += col_w[ci]
      if ci < col_count - 1:
        vlines.append(cur_x)
      cur_x += 1

    out.append({
      "type": "md_table_row",
      "cells": cells,
      "wrapped_cells": wrapped_cells,
      "widths": col_w,
      "header": ri == 0,
      "pad": pad,
      "row_lines": row_lines,
      "height_px": row_lines * line_height,
      "border_px": 1,
      "total_height_px": row_lines * line_height + 1,
      "total_width_px": total_w,
      "vlines": vlines,
      "header_line_y": -1,
      "text_x": text_x,
      "text_y": text_y,
    })
  return out


def _strip_md_header_marks(line):
  if line is None:
    return 0, ""
  i = 0
  while i < len(line) and line[i] == '#':
    i += 1
  if i == 0:
    return 0, line
  if i < len(line) and line[i] == ' ':
    # Do not remove '#', it is important information.
    return i, line
  return 0, line


def _markdownify_header_segments(line):
  level, text = _strip_md_header_marks(line)
  if level <= 0:
    return _tokenize_markdown_bold(line), 0
  segs = _tokenize_markdown_bold(text)
  if len(segs) == 1 and segs[0][1] == "":
    return [(True, "")], level
  out = []
  for is_bold, part in segs:
    out.append((True, part))
  return out, level


def _append_wrapped_md_line(out, v, line, height, max_width, vertical, pre, font, japanese):
  out.extend(_wrap_line(v, line, height, max_width, vertical, pre, font, japanese, markdown=True))


def _build_md_lines(v, lines, height, max_width, vertical, pre, font, japanese):
  """Build wrapped render lines, detecting Markdown pipe tables.

  This is called only for .md/.markdown files to avoid extra processing for
  ordinary text files.
  """
  out = []
  i = 0
  while i < len(lines):
    if i + 1 < len(lines) and _parse_md_table_row(lines[i]) and _is_md_table_separator(lines[i + 1]):
      table_rows = []
      header = _parse_md_table_row(lines[i])
      table_rows.append(header)
      i += 2
      while i < len(lines):
        row = _parse_md_table_row(lines[i])
        if not row:
          break
        table_rows.append(row)
        i += 1
      made = _make_md_table_rows(v, table_rows, max_width, height)
      if made:
        out.extend(made)
        continue
      else:
        _append_wrapped_md_line(out, v, lines[i], height, max_width, vertical, pre, font, japanese)
        i += 1
        continue

    _append_wrapped_md_line(out, v, lines[i], height, max_width, vertical, pre, font, japanese)
    i += 1
  return out


def _is_cjk(text):
  for ch in text:
    o = ord(ch)
    if (0x3000 <= o <= 0x9FFF or
        0xF900 <= o <= 0xFAFF or
        0xFF00 <= o <= 0xFFEF):
      return True
  return False


def _tokenize_markdown_bold(line):
  """
  Split a line into [(is_bold, text), ...] using Markdown style **bold**.
  Unmatched ** is treated as normal text.
  """
  if not line:
    return [(False, "")]

  if line.find('**') == -1:
    return [(False, line)]

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


def _hyphen_pos(word, v, avail_w):
  """Return index i to break word as word[:i]+'-' | word[i:], or -1.
  Ensures >= 2 chars before and >= 3 after; prefers vowel/consonant boundary."""
  n = len(word)
  if n < 5:
    return -1
  cap = n - 3
  best = -1
  for i in range(2, cap + 1):
    if v.get_utf8_width(word[:i] + '-') <= avail_w:
      best = i
    else:
      break
  if best < 0:
    return -1
  for i in range(best, 1, -1):
    if (word[i-1] in 'aeiouAEIOU') != (word[i] in 'aeiouAEIOU'):
      return i
  return best


def _wrap_line(v, line, height, max_width, vertical, pre, font, japanese=False, markdown=False):
  """
  Wrap one UTF-8 line by character width with Markdown bold support.
  Returns a list of wrapped lines, each line is [(is_bold, text), ...]
  """
  if line == "":
    return [[(False, "")]]

  if markdown:
    segments, header_level = _markdownify_header_segments(line)
  else:
    segments = _tokenize_markdown_bold(line)
    #segments = [(False, line)]
    header_level = 0

  plain = _plain_text_from_segments(segments)
  if plain == "":
    return [segments]

  if vertical:
    is_vert_uni = font == 'uni'
    out = []
    start = 0
    index = 0
    line_pre = plain[pre:]
    cur_prefix = plain[:pre]
    cur_len = len(cur_prefix)
    if is_vert_uni:
      height -= 2
      cur_w = height * cur_len
    else:
      cur_w = v.get_utf8_width(cur_prefix) if cur_prefix else 0
    last_ch = cur_prefix[-1] if cur_prefix else ''

    while index < len(line_pre):
      ch = line_pre[index]
      if is_vert_uni:
        ch_w = height
      else:
        ch_w = v.get_utf8_width(ch) + 1
      w = cur_w + ch_w

      if is_vert_uni:
        if ch in ("、","。","っ","ゃ","ゅ","ょ","ッ","ャ","ュ","ョ","」",")","ー","？","！"):
          wrap = not (w <= max_width + height or cur_len == 0)
        else:
          wrap = not (w <= max_width or cur_len == 0)
      else:
        wrap = not (w <= max_width or cur_len == 0)

      if not wrap:
        cur_w = w
        cur_len += 1
        last_ch = ch
      else:
        end = pre + index
        out.append(_slice_segments(segments, start, end))
        start = end
        new_cur = line_pre[index:index + pre + 1]
        cur_len = len(new_cur)
        if is_vert_uni:
          cur_w = height * cur_len
        else:
          cur_w = v.get_utf8_width(new_cur) if new_cur else 0
        last_ch = new_cur[-1] if new_cur else ''
        index += pre
      index += 1

    out.append(_slice_segments(segments, start, len(plain)))
    return out

  if japanese or ' ' not in plain:
    out = []
    n = len(plain)
    ls = 0
    while ls < n:
      cur_w = 0
      end = ls
      for ch in plain[ls:]:
        ch_w = v.get_utf8_width(ch)
        if cur_w + ch_w > max_width and end > ls:
          break
        cur_w += ch_w
        end += 1
      out.append(_slice_segments(segments, ls, end))
      ls = end
    return out if out else [_slice_segments(segments, 0, n)]

  out = []
  n = len(plain)
  ls = 0

  while ls < n:
    best_end = ls
    i = ls

    while i < n:
      while i < n and plain[i] == ' ':
        i += 1
      if i >= n:
        break
      j = i
      while j < n and plain[j] != ' ':
        j += 1
      if v.get_utf8_width(plain[ls:j]) <= max_width:
        best_end = j
        i = j
      else:
        break

    if best_end == ls:
      j = ls
      while j < n and plain[j] != ' ':
        j += 1
      word = plain[ls:j]
      pos = _hyphen_pos(word, v, max_width)
      if pos > 0:
        seg = _slice_segments(segments, ls, ls + pos)
        bold = seg[-1][0] if seg else False
        seg.append((bold, '-'))
        out.append(seg)
        ls += pos
        continue
      best_end = j if j > ls else ls + 1

    out.append(_slice_segments(segments, ls, best_end))
    ls = best_end
    while ls < n and plain[ls] == ' ':
      ls += 1

  return out if out else [_slice_segments(segments, 0, n)]


class Reader:
  def __init__(self, v, vs, paths, isvertical, font, japanese=False):
    self.v = v
    self.vertical = isvertical
    self.pre = 20
    self.vs = vs
    self.seq = anm.anm_sequencer()
    self.scroll_anm = anm.anm_object(100,
      { 'y' : [anm.ease_out, 0,0 ]}
      )
    self.seq.register('scroll',self.scroll_anm)
    
    self.paths = paths if paths else []
    self.file_index = 0
    self.state = _load_state()
    self.scroll_px = 0
    self.op_scroll_px = 0
    self.scroll_speed = 150  # pixels per frame
    self.current_tick = 0
    self.screen_w, self.screen_h = pdeck.get_screen_size()
    self.margin_x = 0
    self.margin_top = 23
    self.margin_bottom = 0
    self.line_gap = 2
    self.japanese = japanese
    self.markdown_mode = False
    self.help_h = 0
    self.el = elib.esclib()

    self._setup_font(font)

    self.status = ""
    self.status_life = 0

    self.wrapped_lines = []
    self.line_offsets = []
    self.total_height = 0
    self.current_path = None
    self.current_key = None

  def _setup_font(self, font):
    self.fontname = font
    self.margin_x = 0
    if font == 't15':
      self.pre = 40
      fontname = 'u8g2_font_t0_15_me'
      self.font = fontname
      self.v.set_font(self.font)
      self.line_height = 16
      self.margin_x = 5
    elif font == 'lub1':
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
      self.margin_x = 2
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
    self.text_h = (self.screen_h - self.margin_top - self.margin_bottom - self.help_h) // self.line_height * self.line_height + self.line_height

  def _state_key(self, path):
    return path

  def basename(self, path):
    return path.rsplit('/', 1)[-1]

  def _line_height_px(self, line):
    if isinstance(line, dict) and line.get("type", "") == "md_table_row":
      return line.get("total_height_px", self.line_height + 1)
    return self.line_height

  def _rebuild_line_offsets(self):
    self.line_offsets = []
    y = 0
    for line in self.wrapped_lines:
      self.line_offsets.append(y)
      y += self._line_height_px(line)
    self.total_height = y

  def _find_start_line(self, scroll_px):
    if not self.line_offsets:
      return 0
    lo = 0
    hi = len(self.line_offsets) - 1
    while lo <= hi:
      mid = (lo + hi) // 2
      y = self.line_offsets[mid]
      h = self._line_height_px(self.wrapped_lines[mid])
      if scroll_px < y:
        hi = mid - 1
      elif scroll_px >= y + h:
        lo = mid + 1
      else:
        return mid
    if lo >= len(self.line_offsets):
      return len(self.line_offsets) - 1
    return lo

  def load_file(self, path):
    self.current_key = self._state_key(path)
    raw_text = _read_text_file(path)

    if _is_cjk(raw_text):
      if self.fontname != 'uni':
        self._setup_font('uni')
      if not self.vertical:
        self.japanese = True

    self.v.set_font(self.font)

    max_width = self.screen_w - self.margin_x * 2
    
    lines = _split_lines(raw_text)
    self.markdown_mode = _is_md_path(path)

    if self.markdown_mode:
      self.wrapped_lines = _build_md_lines(self.v, lines, self.line_height, max_width, self.vertical, self.pre, self.fontname, self.japanese)
    else:
      self.wrapped_lines = []
      for line in lines:
        self.wrapped_lines.extend(_wrap_line(self.v, line, self.line_height, max_width, self.vertical, self.pre, self.fontname, self.japanese))

    self._rebuild_line_offsets()

    saved = self.state.get(self.current_key, {})
    self.scroll_px = int(saved.get("scroll_px", -self.line_height))
    self.update_scroll_px()
    if self.scroll_px < 0:
      self.scroll_px = 0
    if self.total_height > 0 and self.scroll_px > self.total_height - self.text_h:
      self.scroll_px = max(0, self.total_height - self.text_h)

    self.op_scroll_px = self.scroll_px

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

  def update_scroll_px(self):
    self.scroll_anm = anm.anm_object(140,
    {'y': [anm.ease_out, self.scroll_anm.y,self.scroll_px]})
    self.seq.register('scroll',self.scroll_anm)
    #print(f'scroll_px {self.scroll_px}')

  def scroll_by(self, delta):
    self.scroll_px += int(delta)
    self.scroll_px = self.scroll_px // self.line_height * self.line_height
    if self.scroll_px < -self.line_height:
      self.scroll_px = -self.line_height
    max_scroll = max(0, self.total_height - self.text_h)
    if self.scroll_px > max_scroll:
      self.scroll_px = max_scroll
    self.update_scroll_px()

  def page_down(self):
    #self.scroll_by((self.text_h // self.line_height) * self.line_height-self.line_height)
    self.scroll_by(self.screen_h - self.margin_top - self.margin_bottom)

  def page_up(self):
    #self.scroll_by(-(self.text_h // self.line_height) * self.line_height+self.line_height)
    self.scroll_by(-(self.screen_h - self.margin_top - self.margin_bottom)+1)

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

      self.v.set_dither(15)
      self.v.draw_line(0, 21, 399, 21)
      self.v.set_dither(16)
      self.v.draw_str(self.margin_x, 18, header)

  def _draw_segments_horizontal(self, x, y, segments):
    self.v.set_font_pos_bottom()
    for is_bold, text in segments:
      if text == "":
        continue
      if is_bold:
        self.v.draw_utf8(x, y, text)
        self.v.draw_utf8(x + 1, y, text)
      else:
        self.v.draw_utf8(x, y, text)
      x += self.v.get_utf8_width(text)
    self.v.set_font_pos_baseline()

  def _draw_segments_vertical(self, x, y, segments):
    text = _plain_text_from_segments(segments)
    if self.fontname == 'uni':
      self.v.draw_utf8_v(x, y, text)
    else:
      self.v.set_font_direction(1)
      self.v.draw_utf8(x, y, text)
      self.v.set_font_direction(0)

  def _draw_md_table_row(self, x, y, row):
    widths = row.get("widths", [])
    wrapped_cells = row.get("wrapped_cells", [])
    pad = row.get("pad", 6)
    height_px = row.get("height_px", self.line_height)
    total_w = row.get("total_width_px", 0)

    if total_w <= 0:
      total_w = len(widths) + 1
      for w in widths:
        total_w += w

    top = y
    border_h = height_px + 1

    self.v.set_draw_color(1)
    self.v.set_dither(15)
    self.v.draw_frame(x, top, total_w, border_h)

    vlines = row.get("vlines", [])
    if not vlines and len(widths) > 1:
      vlines = []
      cur_x = 1
      for i in range(len(widths) - 1):
        cur_x += widths[i]
        vlines.append(cur_x)
        cur_x += 1

    for vx in vlines:
      self.v.draw_v_line(x + vx, top, border_h)

    header_y = row.get("header_line_y", -1)
    if header_y >= 0:
      self.v.draw_h_line(x, top + header_y, total_w)

    self.v.set_dither(16)
    self.v.set_font_pos_bottom()

    text_x = row.get("text_x", [])
    text_y = row.get("text_y", [])

    if len(text_x) < len(widths) or len(text_y) < len(widths):
      text_x = []
      text_y = []
      cur_x = 1
      for i in range(len(widths)):
        text_x.append(cur_x + pad)
        text_y.append(self.line_height)
        cur_x += widths[i] + 1

    for i in range(len(widths)):
      lines = wrapped_cells[i] if i < len(wrapped_cells) else [""]
      tx = x + text_x[i]
      inner_y = top + text_y[i]
      if row.get("header", False):
        for text in lines:
          self.v.draw_utf8(tx, inner_y, text)
          self.v.draw_utf8(tx + 1, inner_y, text)
          inner_y += self.line_height
      else:
        for text in lines:
          self.v.draw_utf8(tx, inner_y, text)
          inner_y += self.line_height

    self.v.set_font_pos_baseline()

  def _draw_segments(self, x, y, segments):
    if isinstance(segments, dict) and segments.get("type", "") == "md_table_row":
      self._draw_md_table_row(x, y, segments)
    elif self.vertical:
      self._draw_segments_vertical(x, y, segments)
    else:
      self._draw_segments_horizontal(x, y, segments)

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return

    self.seq.update(time.ticks_ms())
    
    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = (self.current_tick - self.last_tick)

    self.v.set_draw_color(1)
    self.v.set_font(self.font)

    if not self.current_path:
      self.v.draw_str(50, 100, "Loading book...")
      self.v.finished()
      return


    self.op_scroll_px = self.scroll_anm.y

    start_line = self._find_start_line(int(self.op_scroll_px))
    if start_line < len(self.line_offsets):
      y_offset = self.line_offsets[start_line] - int(self.op_scroll_px)
    else:
      y_offset = 0

    y = self.margin_top + y_offset
    idx = start_line
    limit_y = self.screen_h - self.help_h - self.margin_bottom

    while idx < len(self.wrapped_lines) and y < limit_y:
      line = self.wrapped_lines[idx]
      self._draw_segments(self.margin_x, y, line)
      y += self._line_height_px(line)
      idx += 1

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
        pdeck.delay_tick(30)
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
      if time.ticks_diff(now, last_save) > 10000:
        #print('saved')
        self.save_position()
        last_save = now

      if not self.v.active:
        pdeck.delay_tick(100)
      else:
        pdeck.delay_tick(4)



def main(vs, args_in):
  v = vs.v
  el = elib.esclib()

  parser = argparse.ArgumentParser(vs=vs,
            description='Book Reader')
  parser.add_argument('-v', '--vertical', action='store_true', help='Japanese vertical style')
  parser.add_argument('-j', '--japanese', action='store_true', help='Japanese horizontal (character-by-character wrap, no hyphenation)')
  parser.add_argument('-f', '--font', action='store', default='cen1', help='Specify font. Options are : uni (unicode), t15(monospace), lub1, lub2, cen1, cen2')
  parser.add_argument('filename', args='*', help='filename to read')

  args = parser.parse_args(args_in[1:])

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  if isinstance(args.filename, str):
    paths = [args.filename]
  else:
    paths = args.filename

  reader = Reader(v, vs, paths, args.vertical, args.font, args.japanese)
  v.callback(reader.update)
  reader.load_file(paths[0])
  reader.loop()
  v.callback(None)

  v.print(el.display_mode(True))
  print("finished.", file=vs)
