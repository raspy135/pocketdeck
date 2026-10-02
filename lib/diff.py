import argparse


ESC = '\x1b['


class _StopPaging(Exception):
  pass


def _sgr(code, enabled):
  if enabled:
    return ESC + code + 'm'
  return ''


def _bold(text, enabled):
  if not enabled:
    return text
  return _sgr('1', True) + text + _sgr('22', True)


def _underline(text, enabled):
  return _bold(text, enabled)


def _invert(text, enabled):
  return text


def _style_line(text, tag, enabled):
  if not enabled:
    return text
  if tag == '-':
    return _invert(text, True)
  if tag == '+':
    return _underline(text, True)
  if tag == '!':
    return _bold(text, True)
  return text


def _open_lines(path):
  with open(path, 'r') as f:
    return [line.rstrip('\n') for line in f]


class _Writer:
  def __init__(self, stream):
    self.stream = stream

  def line(self, text=''):
    print(text, file=self.stream)


class _PagerWriter:
  def __init__(self, stream, page_lines):
    self.stream = stream
    self.page_lines = page_lines
    if self.page_lines < 1:
      self.page_lines = 1
    self.line_count = 0

  def _pause(self):
    print('--More-- hit any key, q to quit', file=self.stream)
    key = self.stream.read(1)
    if key == 'q' or key == 'Q':
      raise _StopPaging()
    self.line_count = 0

  def line(self, text=''):
    if self.line_count >= self.page_lines:
      self._pause()
    print(text, file=self.stream)
    self.line_count += 1


class _TeeWriter:
  def __init__(self, stream, fp):
    self.stream = stream
    self.fp = fp

  def line(self, text=''):
    if self.stream is not None:
      print(text, file=self.stream)
    self.fp.write(text)
    self.fp.write('\n')


def _line_no_width(ops):
  mx = 1
  for tag, left_no, right_no, _left, _right in ops:
    if left_no > mx:
      mx = left_no
    if right_no > mx:
      mx = right_no
  return len(str(mx))


def _detect_terminal_width(vs, fallback):
  try:
    size = vs.v.get_terminal_size()
    if isinstance(size, tuple) and len(size) >= 1 and size[0] > 0:
      return size[0]
  except Exception:
    pass
  return fallback


def _detect_terminal_height(vs, fallback):
  try:
    size = vs.v.get_terminal_size()
    if isinstance(size, tuple) and len(size) >= 2 and size[1] > 0:
      return size[1]
  except Exception:
    pass
  return fallback


def _truncate(text, width):
  if width <= 0:
    return ''
  if len(text) <= width:
    return text
  if width <= 3:
    return text[:width]
  return text[:width - 3] + '...'


def _diff_lines(left_lines, right_lines, lookahead):
  ops = []
  i = 0
  j = 0
  left_len = len(left_lines)
  right_len = len(right_lines)

  while i < left_len and j < right_len:
    if left_lines[i] == right_lines[j]:
      ops.append((' ', i + 1, j + 1, left_lines[i], right_lines[j]))
      i += 1
      j += 1
      continue

    match_in_right = -1
    end_right = right_len
    if j + lookahead + 1 < end_right:
      end_right = j + lookahead + 1
    k = j + 1
    while k < end_right:
      if left_lines[i] == right_lines[k]:
        match_in_right = k
        break
      k += 1

    match_in_left = -1
    end_left = left_len
    if i + lookahead + 1 < end_left:
      end_left = i + lookahead + 1
    k = i + 1
    while k < end_left:
      if left_lines[k] == right_lines[j]:
        match_in_left = k
        break
      k += 1

    if match_in_right != -1 and (match_in_left == -1 or (match_in_right - j) <= (match_in_left - i)):
      while j < match_in_right:
        ops.append(('+', 0, j + 1, '', right_lines[j]))
        j += 1
      continue

    if match_in_left != -1:
      while i < match_in_left:
        ops.append(('-', i + 1, 0, left_lines[i], ''))
        i += 1
      continue

    ops.append(('!', i + 1, j + 1, left_lines[i], right_lines[j]))
    i += 1
    j += 1

  while i < left_len:
    ops.append(('-', i + 1, 0, left_lines[i], ''))
    i += 1

  while j < right_len:
    ops.append(('+', 0, j + 1, '', right_lines[j]))
    j += 1

  return ops


def _compact_ops(ops, context):
  if context < 0:
    context = 0

  marked = [False] * len(ops)
  changed = []
  for idx, op in enumerate(ops):
    if op[0] != ' ':
      changed.append(idx)

  if not changed:
    return ops

  for idx in changed:
    start = idx - context
    if start < 0:
      start = 0
    end = idx + context + 1
    if end > len(ops):
      end = len(ops)
    i = start
    while i < end:
      marked[i] = True
      i += 1

  out = []
  i = 0
  while i < len(ops):
    if marked[i]:
      out.append(ops[i])
      i += 1
      continue
    j = i
    while j < len(ops) and not marked[j]:
      j += 1
    out.append(('...', 0, 0, str(j - i), ''))
    i = j
  return out


def _changed_indexes(ops):
  indexes = []
  for idx, op in enumerate(ops):
    if op[0] != ' ':
      indexes.append(idx)
  return indexes


def _previous_left_no(ops, idx):
  i = idx - 1
  while i >= 0:
    if ops[i][1] > 0:
      return ops[i][1]
    i -= 1
  return 0


def _previous_right_no(ops, idx):
  i = idx - 1
  while i >= 0:
    if ops[i][2] > 0:
      return ops[i][2]
    i -= 1
  return 0


def _make_hunks(ops, context, show_all):
  if not ops:
    return []

  if show_all:
    return [(0, len(ops))]

  changed = _changed_indexes(ops)
  if not changed:
    return []

  if context < 0:
    context = 0

  ranges = []
  for idx in changed:
    start = idx - context
    if start < 0:
      start = 0
    end = idx + context + 1
    if end > len(ops):
      end = len(ops)

    if ranges and start <= ranges[-1][1]:
      if end > ranges[-1][1]:
        ranges[-1] = (ranges[-1][0], end)
    else:
      ranges.append((start, end))
  return ranges


def _hunk_range(ops, start, end, side):
  nums = []
  count = 0
  for i in range(start, end):
    no = ops[i][1] if side == 'left' else ops[i][2]
    if no > 0:
      nums.append(no)
      count += 1

  if nums:
    first = nums[0]
  else:
    first = _previous_left_no(ops, start) if side == 'left' else _previous_right_no(ops, start)

  if count == 1:
    return str(first)
  return str(first) + ',' + str(count)


def _render_unified(writer, ops, context, show_all, style):
  hunks = _make_hunks(ops, context, show_all)
  if not hunks:
    writer.line('(no differences)')
    return

  for start, end in hunks:
    left_range = _hunk_range(ops, start, end, 'left')
    right_range = _hunk_range(ops, start, end, 'right')
    writer.line(_bold('@@ -' + left_range + ' +' + right_range + ' @@', style))

    i = start
    while i < end:
      tag, _left_no, _right_no, left_text, right_text = ops[i]
      if tag == ' ':
        writer.line(' ' + left_text)
        i += 1
      elif tag == '-':
        writer.line(_style_line('-' + left_text, '-', style))
        i += 1
      elif tag == '+':
        writer.line(_style_line('+' + right_text, '+', style))
        i += 1
      elif tag == '!':
        j = i
        while j < end and ops[j][0] == '!':
          writer.line(_style_line('-' + ops[j][3], '-', style))
          j += 1
        j = i
        while j < end and ops[j][0] == '!':
          writer.line(_style_line('+' + ops[j][4], '+', style))
          j += 1
        i = j
      else:
        i += 1


def _render_header(writer, left_path, right_path, style):
  writer.line(_bold('--- ' + left_path, style))
  writer.line(_bold('+++ ' + right_path, style))


def _render_side_by_side(writer, ops, width, style):
  numw = _line_no_width(ops)
  content_w = (width - (numw * 2) - 7) // 2
  if content_w < 8:
    content_w = 8

  for tag, left_no, right_no, left_text, right_text in ops:
    if tag == '...':
      writer.line(_bold('... ' + left_text + ' unchanged lines ...', style))
      continue

    left_num = '' if left_no == 0 else str(left_no)
    right_num = '' if right_no == 0 else str(right_no)
    mark_left = ' '
    mark_right = ' '
    if tag == '-':
      mark_left = '<'
    elif tag == '+':
      mark_right = '>'
    elif tag == '!':
      mark_left = '!'
      mark_right = '!'

    left_cell = '{:>{nw}} {} {:<{cw}}'.format(left_num, mark_left, _truncate(left_text, content_w), nw=numw, cw=content_w)
    right_cell = '{:>{nw}} {} {:<{cw}}'.format(right_num, mark_right, _truncate(right_text, content_w), nw=numw, cw=content_w)

    if tag == '-':
      left_cell = _style_line(left_cell, '-', style)
    elif tag == '+':
      right_cell = _style_line(right_cell, '+', style)
    elif tag == '!':
      left_cell = _style_line(left_cell, '!', style)
      right_cell = _style_line(right_cell, '!', style)

    writer.line(left_cell + ' | ' + right_cell)


def _build_parser(vs):
  parser = argparse.ArgumentParser(vs=vs, description='compare two text files')
  parser.add_argument('-a', '--all', action='store_true', help='show all unchanged lines in one unified hunk')
  parser.add_argument('-c', '--context', type=int, default=2, help='context lines around changes')
  parser.add_argument('-y', '--side-by-side', action='store_true', help='show side by side view')
  parser.add_argument('-w', '--width', type=int, default=0, help='target width for side by side view')
  parser.add_argument('-l', '--lookahead', type=int, default=12, help='anchor search window')
  parser.add_argument('-m', '--more', action='store_true', help='pause and wait for a key every page')
  parser.add_argument('-o', '--output', help='write output to file path')
  parser.add_argument('-p', '--plain', action='store_true', help='disable syntax highlighting / escape sequences')
  parser.add_argument('--style', action='store_true', help='force syntax highlighting even when using -o')
  parser.add_argument('left', help='left file path')
  parser.add_argument('right', help='right file path')
  return parser


def main(vs, args_in):
  parser = _build_parser(vs)
  try:
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return

  try:
    left_lines = _open_lines(args.left)
  except OSError as e:
    print('diff: cannot open {}: {}'.format(args.left, e), file=vs)
    return

  try:
    right_lines = _open_lines(args.right)
  except OSError as e:
    print('diff: cannot open {}: {}'.format(args.right, e), file=vs)
    return

  style = not args.plain
  if args.output and not args.style:
    style = False

  ops = _diff_lines(left_lines, right_lines, args.lookahead)

  if args.width and args.width > 0:
    width = args.width
  else:
    width = _detect_terminal_width(vs, 76)

  if args.output:
    try:
      with open(args.output, 'w') as fp:
        writer = _TeeWriter(None, fp)
        _render_header(writer, args.left, args.right, style)
        if args.side_by_side:
          out_ops = ops if args.all else _compact_ops(ops, args.context)
          _render_side_by_side(writer, out_ops, width, style)
        else:
          _render_unified(writer, ops, args.context, args.all, style)
    except OSError as e:
      print('diff: cannot write {}: {}'.format(args.output, e), file=vs)
      return
    print('diff output saved to {}'.format(args.output), file=vs)
    return

  if args.more:
    height = _detect_terminal_height(vs, 20)
    writer = _PagerWriter(vs, height - 1)
  else:
    writer = _Writer(vs)

  try:
    _render_header(writer, args.left, args.right, style)
    if args.side_by_side:
      out_ops = ops if args.all else _compact_ops(ops, args.context)
      _render_side_by_side(writer, out_ops, width, style)
    else:
      _render_unified(writer, ops, args.context, args.all, style)
  except _StopPaging:
    return
