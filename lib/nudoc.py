import time
import random
import array
import pdeck
import esclib as elib
import mouse
import audio
import math
import wav_loader
import xbmreader

KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_RIGHT = b'\x1b[C'
KEY_LEFT = b'\x1b[D'
KEY_ENTER = b'\r'
KEY_BS = b'\b'
KEY_PAGE_UP = b'\x1b[5~'
KEY_PAGE_DOWN = b'\x1b[6~'

GRID_X = 8
GRID_Y = 28
CELL = 23
GRID_W = CELL * 9
GRID_H = CELL * 9

SIDE_X = GRID_X + GRID_W + 16
SIDE_Y = GRID_Y + 10
STATUS_H = 24
MAX_MISTAKES = 3

STATE_TITLE = 0
STATE_BUILDING = 1
STATE_PLAYING = 2
STATE_QUIT_DIALOG = 3
STATE_GAMEOVER_DIALOG = 4

DIFFS = {
  'Easy': 36,
  'Medium': 46,
  'Hard': 54,
}

DIFF_ORDER = ['Easy', 'Medium', 'Hard']
FULL_MASK = 0x1FF

def bit_count(x):
  c = 0
  while x:
    x &= x - 1
    c += 1
  return c

def lowest_bit(x):
  return x & -x

def clamp(v, a, b):
  if v < a:
    return a
  if v > b:
    return b
  return v

def shuffle_list(lst):
  for i in range(len(lst) - 1, 0, -1):
    j = random.getrandbits(16) % (i + 1)
    t = lst[i]
    lst[i] = lst[j]
    lst[j] = t

def make_square_wave(table_size=256):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    phase = i / table_size
    frame[i] = 18000 if phase < 0.4 else -18000
  return [frame]

def make_triangle_wave(table_size=256):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    phase = (i / table_size) * 2 * math.pi
    val = math.sin(phase)
    frame[i] = int(val * 20000)
  return [frame]

def make_noise_wave(table_size=256):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    frame[i] = int(random.uniform(-1, 1) * 14000)
  return [frame]


class NudocGame:
  def __init__(self, vs, difficulty):
    self.vs = vs
    self.v = vs.v
    self.el = elib.esclib()
    self.m = mouse.mouse(self.v)
    self.m.set_limit([GRID_X, GRID_Y], [GRID_X + CELL * 9, GRID_Y + CELL * 9])
    self.running = True
    self.state = STATE_TITLE
    self.completed = False
    self.flash_tick = 0
    self.start_tick = time.ticks_ms()
    self.score = 0
    self.mistakes = 0
    self.selected_num = 1
    self.difficulty = difficulty
    self.cursor_x = 0
    self.cursor_y = 0
    self.last_scroll = 255
    self.last_mouse_cell = None
    self.anim_lines = []
    self.anim_boxes = []
    self.anim_win = 0
    self.time_bonus_anm = 0
    self.current_tick = time.ticks_us()
    self.solution = [[0 for _ in range(9)] for _ in range(9)]
    self.board = [[0 for _ in range(9)] for _ in range(9)]
    self.fixed = [[0 for _ in range(9)] for _ in range(9)]
    self.audio_init()
    self.images = {}
    img = xbmreader.read_xbmr("/sd/lib/data/easy.xbmr")
    self.images['Easy'] = xbmreader.scale(img,2)
    img = xbmreader.read_xbmr("/sd/lib/data/medium.xbmr")
    self.images['Medium'] = xbmreader.scale(img,2)

    img = xbmreader.read_xbmr("/sd/lib/data/hard.xbmr")
    self.images['Hard'] = xbmreader.scale(img,2)

    img = xbmreader.read_xbmr("/sd/lib/data/nudoc.xbmr")
    self.images['title'] = img

  def reset_game(self, difficulty):
    self.state = STATE_BUILDING
    self.completed = False
    self.flash_tick = 0
    self.start_tick = time.ticks_ms()
    self.score = 0
    self.mistakes = 0
    self.selected_num = 1
    self.difficulty = difficulty
    self.cursor_x = 0
    self.cursor_y = 0
    self.last_scroll = 255
    self.last_mouse_cell = None
    self.anim_lines = []
    self.anim_boxes = []
    self.anim_win = 0
    self.current_tick = time.ticks_us()
    self.solution = [[0 for _ in range(9)] for _ in range(9)]
    self.board = [[0 for _ in range(9)] for _ in range(9)]
    self.fixed = [[0 for _ in range(9)] for _ in range(9)]
    self.generate_puzzle()
    while self.vs.poll():
      self.vs.read(1)
    self.state = STATE_PLAYING

  def audio_init(self):
    try:
      audio.sample_rate(24000)
      self.sound_enabled = True
    except Exception as e:
      print("audio init failed:", e)
      self.sound_enabled = False
    self.sound = None
    if self.sound_enabled:
      self.s_clear, ch_clear = wav_loader.load_wav("/sd/lib/data/clear.wav")
      self.sample = audio.sampler(1)
      self.sample.__enter__()
      self.sample.set_sample(0, self.s_clear, ch_clear)
      self.sample.volume(0, 0.8)

      self.sound = audio.wavetable(3)
      self.sound.__enter__()
      self.sound.set_wavetable(0, make_square_wave(256))
      self.sound.set_wavetable(1, make_triangle_wave(256))
      self.sound.set_wavetable(2, make_noise_wave(256))
      self.sound.set_adsr(0, 2, 680, 1.0, 0.05)
      self.sound.set_adsr(1, 1, 1500, 0.2, 500)
      self.sound.set_adsr(2, 1, 40, 0.0, 0.08)

  def play_sound(self, idx):
    self.sample.play(idx)
    pass

  def beep_error(self):
    if self.sound_enabled:
      self.sound.frequency(0, 180)
      self.sound.volume(0, 0.2)
      self.sound.note_on(0)
      self.sound.note_off(0, "+0.2s")

  def beep_ok(self):
    if self.sound_enabled:
      self.sound.frequency(1, 400)
      self.sound.pitch(1, 1)
      self.sound.volume(1, 0.8)
      self.sound.note_on(1)
      self.sound.pitch(1, 1.5, 0, "+0.1s")
      self.sound.note_off(1, "+0.2s")

  def beep_gameover(self):
    if self.sound_enabled:
      self.sound.frequency(2, 140)
      self.sound.volume(2, 0.9)
      self.sound.note_on(2)
      self.sound.note_off(2, "+0.35s")
      self.sound.frequency(0, 110)
      self.sound.volume(0, 0.25)
      self.sound.note_on(0)
      self.sound.note_off(0, "+0.45s")

  def board_copy(self, src):
    out = []
    for y in range(9):
      row = []
      for x in range(9):
        row.append(src[y][x])
      out.append(row)
    return out

  def box_index(self, r, c):
    return (r // 3) * 3 + (c // 3)


  def init_masks_from_board(self, board):
    rows = [0] * 9
    cols = [0] * 9
    boxes = [0] * 9
    for r in range(9):
      for c in range(9):
        n = board[r][c]
        if n:
          bit = 1 << (n - 1)
          rows[r] |= bit
          cols[c] |= bit
          boxes[self.box_index(r, c)] |= bit
    return rows, cols, boxes

  def find_best_cell_masks(self, board, rows, cols, boxes):
    min_count = 10
    best_r = -1
    best_c = -1
    best_mask = 0

    for r in range(9):
      for c in range(9):
        if board[r][c] == 0:
          used = rows[r] | cols[c] | boxes[self.box_index(r, c)]
          avail = (~used) & FULL_MASK
          cnt = bit_count(avail)
          if cnt < min_count:
            min_count = cnt
            best_r = r
            best_c = c
            best_mask = avail
            if cnt == 1:
              return best_r, best_c, best_mask
    return best_r, best_c, best_mask

  def randomize_bits(self, mask):
    arr = []
    while mask:
      b = lowest_bit(mask)
      arr.append(b)
      mask ^= b

    for i in range(len(arr) - 1, 0, -1):
      j = random.getrandbits(16) % (i + 1)
      arr[i], arr[j] = arr[j], arr[i]

    return arr

  def ordered_bits(self, mask):
    arr = []
    while mask:
      b = lowest_bit(mask)
      arr.append(b)
      mask ^= b
    return arr

  def bit_to_num(self, bit):
    n = 1
    while bit > 1:
      bit >>= 1
      n += 1
    return n

  def place_bit(self, board, rows, cols, boxes, r, c, bit):
    board[r][c] = self.bit_to_num(bit)
    rows[r] |= bit
    cols[c] |= bit
    boxes[self.box_index(r, c)] |= bit

  def remove_bit(self, board, rows, cols, boxes, r, c, bit):
    board[r][c] = 0
    rows[r] ^= bit
    cols[c] ^= bit
    boxes[self.box_index(r, c)] ^= bit

  def make_candidate_bits(self, mask, randomize):
    if randomize:
      return self.randomize_bits(mask)
    return self.ordered_bits(mask)

  def backtrack_next(self, board, rows, cols, boxes, stack):
    while stack:
      pr, pc, cand, idx = stack[-1]
      last_bit = cand[idx - 1]
      self.remove_bit(board, rows, cols, boxes, pr, pc, last_bit)

      if idx >= len(cand):
        stack.pop()
        continue

      bit = cand[idx]
      stack[-1][3] += 1
      self.place_bit(board, rows, cols, boxes, pr, pc, bit)
      return True
    return False

  def solve_board_mdv(self, board, randomize=True, limit=1):
    rows, cols, boxes = self.init_masks_from_board(board)
    stack = []
    total = 0

    while True:
      r, c, mask = self.find_best_cell_masks(board, rows, cols, boxes)

      if r == -1:
        total += 1
        if total >= limit:
          return total
        if not self.backtrack_next(board, rows, cols, boxes, stack):
          return total
        continue

      if mask == 0:
        if not self.backtrack_next(board, rows, cols, boxes, stack):
          return total
        continue

      cand = self.make_candidate_bits(mask, randomize)
      bit = cand[0]
      self.place_bit(board, rows, cols, boxes, r, c, bit)
      stack.append([r, c, cand, 1])

  def build_solution(self):
    for y in range(9):
      for x in range(9):
        self.solution[y][x] = 0
    self.solve_board_mdv(self.solution, True, 1)

  def has_unique_solution(self, board):
    temp = self.board_copy(board)
    return self.solve_board_mdv(temp, False, 2) == 1

  def remove_cells(self, holes):
    for y in range(9):
      for x in range(9):
        self.board[y][x] = self.solution[y][x]
        self.fixed[y][x] = 1

    ids = []
    for i in range(81):
      ids.append(i)
    shuffle_list(ids)

    removed = 0
    for idx in ids:
      if removed >= holes:
        break
      y = idx // 9
      x = idx % 9
      old = self.board[y][x]
      self.board[y][x] = 0
      if self.has_unique_solution(self.board):
        self.fixed[y][x] = 0
        removed += 1
      else:
        self.board[y][x] = old
        self.fixed[y][x] = 1

  def generate_puzzle(self):
    self.build_solution()
    holes = DIFFS.get(self.difficulty, 46)
    self.remove_cells(holes)

  def elapsed_text(self):
    sec = time.ticks_diff(time.ticks_ms(), self.start_tick) // 1000
    mm = sec // 60
    ss = sec % 60
    if mm < 10:
      m = "0" + str(mm)
    else:
      m = str(mm)
    if ss < 10:
      s = "0" + str(ss)
    else:
      s = str(ss)
    return m + ":" + s

  def popup_text_width(self, text):
    self.v.set_font("u8g2_font_profont15_mf")
    return self.v.get_str_width(text)

  def move_cursor(self, dx, dy):
    self.cursor_x = (self.cursor_x + dx) % 9
    self.cursor_y = (self.cursor_y + dy) % 9

  def set_selected_from_scroll(self, raw):
    if raw == 255:
      self.last_scroll = 255
      return
    if self.last_scroll == 255:
      self.last_scroll = raw
      return
    diff = raw - self.last_scroll
    if diff <= -10:
      self.selected_num += 1
      if self.selected_num > 9:
        self.selected_num = 1
      self.last_scroll -= 10
    elif diff >= 10:
      self.selected_num -= 1
      if self.selected_num < 1:
        self.selected_num = 9
      self.last_scroll += 10

  def trigger_gameover(self):
    if self.state == STATE_GAMEOVER_DIALOG:
      return
    self.state = STATE_GAMEOVER_DIALOG
    self.beep_gameover()

  def fill_selected(self):
    if self.completed or self.state != STATE_PLAYING:
      return
    if self.fixed[self.cursor_y][self.cursor_x]:
      return
    if self.solution[self.cursor_y][self.cursor_x] == self.selected_num:
      if self.board[self.cursor_y][self.cursor_x] == 0:
        self.board[self.cursor_y][self.cursor_x] = self.selected_num
        time_bonus = 0
        base_bonus = 10
        sec = time.ticks_diff(time.ticks_ms(), self.start_tick) // 1000
        if self.difficulty == 'Easy':
          time_bonus = 0 if sec > 600 else int(600 - sec)//10
          base_bonus = 10
        if self.difficulty == 'Medium':
          time_bonus = 0 if sec > 600 else int(600 - sec)//8
          base_bonus = 12
        if self.difficulty == 'Hard':
          time_bonus = 0 if sec > 600 else int(1000 - sec)//8
          base_bonus = 15
        
        self.score += base_bonus + time_bonus
        if time_bonus > 0:
          self.time_bonus = time_bonus
          self.time_bonus_anm = 60
        self.beep_ok()
        self.check_animations()
        self.check_complete()
    else:
      self.board[self.cursor_y][self.cursor_x] = 0
      self.mistakes += 1
      self.score -= 3
      if self.score < 0:
        self.score = 0
      self.beep_error()
      if self.mistakes >= MAX_MISTAKES:
        self.trigger_gameover()

  def is_row_filled(self, y):
    for x in range(9):
      if self.board[y][x] != self.solution[y][x]:
        return False
    return True

  def is_col_filled(self, x):
    for y in range(9):
      if self.board[y][x] != self.solution[y][x]:
        return False
    return True

  def is_box_filled(self, bx, by):
    for yy in range(by * 3, by * 3 + 3):
      for xx in range(bx * 3, bx * 3 + 3):
        if self.board[yy][xx] != self.solution[yy][xx]:
          return False
    return True

  def check_animations(self):
    y = self.cursor_y
    x = self.cursor_x
    if self.is_row_filled(y):
      found = False
      for item in self.anim_lines:
        if item[0] == 'r' and item[1] == y:
          found = True
      if not found:
        self.anim_lines.append(['r', y, 18])
        self.score += 30
    if self.is_col_filled(x):
      found = False
      for item in self.anim_lines:
        if item[0] == 'c' and item[1] == x:
          found = True
      if not found:
        self.anim_lines.append(['c', x, 18])
        self.score += 30
    bx = x // 3
    by = y // 3
    if self.is_box_filled(bx, by):
      found = False
      for item in self.anim_boxes:
        if item[0] == bx and item[1] == by:
          found = True
      if not found:
        self.anim_boxes.append([bx, by, 24])
        self.score += 50

  def check_complete(self):
    for y in range(9):
      for x in range(9):
        if self.board[y][x] != self.solution[y][x]:
          return
    self.completed = True
    self.anim_win = 80
    self.score += 200 + 200*(2 - self.mistakes)
    self.play_sound(0)
    self.state = STATE_GAMEOVER_DIALOG

  def update_anims(self):
    out = []
    for item in self.anim_lines:
      item[2] -= 1
      if item[2] > 0:
        out.append(item)
    self.anim_lines = out

    out = []
    for item in self.anim_boxes:
      item[2] -= 1
      if item[2] > 0:
        out.append(item)
    self.anim_boxes = out

    if self.anim_win > 0:
      self.anim_win -= 1

  def draw_status(self):
    self.v.set_draw_color(1)
    self.v.draw_box(0, 0, 400, STATUS_H)
    self.v.set_draw_color(0)
    self.v.set_font("u8g2_font_profont15_mf")
    txt = " Score:{}  Mistakes:{}/{}  Elapsed:{} ".format(
      self.score,
      self.mistakes,
      MAX_MISTAKES,
      self.elapsed_text()
    )
    self.v.draw_str(8, 17, txt)
    self.v.set_dither(8)
    self.v.draw_line(0, STATUS_H - 1, 399, STATUS_H - 1)
    self.v.set_dither(16)
    self.v.set_draw_color(1)

  def draw_grid_highlight(self):
    self.v.set_draw_color(0)
    self.v.set_dither(16)
    self.v.draw_box(GRID_X, GRID_Y, CELL * 9, CELL * 9)
    self.v.set_draw_color(1)

    row_y = GRID_Y + self.cursor_y * CELL
    col_x = GRID_X + self.cursor_x * CELL

    self.v.set_dither(2)
    self.v.draw_box(GRID_X, row_y, GRID_W, CELL)
    self.v.draw_box(col_x, GRID_Y, CELL, GRID_H)

    self.v.set_dither(7)
    self.v.draw_box(col_x, row_y, CELL, CELL)
    self.v.set_dither(16)

  def draw_grid_lines(self):
    for i in range(10):
      x = GRID_X + i * CELL
      y = GRID_Y + i * CELL
      if (i % 3) == 0:
        self.v.draw_v_line(x, GRID_Y, GRID_H)
        if x + 1 < GRID_X + GRID_W + 1:
          self.v.draw_v_line(x + 1, GRID_Y, GRID_H)
        self.v.draw_h_line(GRID_X, y, GRID_W)
        if y + 1 < GRID_Y + GRID_H + 1:
          self.v.draw_h_line(GRID_X, y + 1, GRID_W)
      else:
        self.v.set_dither(10)
        self.v.draw_v_line(x, GRID_Y, GRID_H)
        self.v.draw_h_line(GRID_X, y, GRID_W)
        self.v.set_dither(16)

  def draw_numbers(self):
    self.v.set_font("u8g2_font_profont22_mf")
    self.v.set_bitmap_mode(1)
    self.v.set_font_pos_baseline()
    for y in range(9):
      for x in range(9):
        n = self.board[y][x]
        if n == 0:
          continue
        px = GRID_X + x * CELL + 7
        py = GRID_Y + y * CELL + 19
        if self.fixed[y][x]:
          self.v.set_draw_color(1)
          self.v.draw_str(px, py, str(n))
        else:
          self.v.set_draw_color(1)
          self.v.draw_str(px, py, str(n))
          self.v.set_dither(6)
          self.v.draw_str(px + 1, py, str(n))
          self.v.set_dither(16)
    self.v.set_draw_color(1)

  def draw_side_numbers(self):
    self.v.set_draw_color(1)
    self.v.set_font("u8g2_font_profont22_mf")
    center_idx = self.selected_num - 1
    for i in range(-4, 5):
      n = center_idx + i
      while n < 0:
        n += 9
      while n > 8:
        n -= 9
      num = n + 1
      y = SIDE_Y + 100 + i * 26
      if y < 40 or y > 225:
        continue

      if i == 0:
        self.v.set_dither(16)
        self.v.set_draw_color(1)
        self.v.draw_rbox(SIDE_X - 6, y - 18, 40, 24, 3)
        self.v.set_draw_color(0)
        self.v.draw_str(SIDE_X + 8, y, str(num))
        self.v.set_draw_color(1)
      else:
        self.v.set_dither(12)
        self.v.draw_str(SIDE_X + 8, y, str(num))
        self.v.set_dither(16)

  def draw_completion_effect(self):
    if self.anim_win <= 0:
      return
    phase = self.anim_win % 16
    self.v.set_dither(phase)
    self.v.draw_frame(GRID_X - 4, GRID_Y - 4, GRID_W + 8, GRID_H + 8)
    self.v.draw_frame(GRID_X - 6, GRID_Y - 6, GRID_W + 12, GRID_H + 12)

  def draw_line_box_anims(self):
    for item in self.anim_lines:
      mode = item[0]
      idx = item[1]
      life = item[2]
      d = 4 + (life % 10)
      self.v.set_dither(d)
      if mode == 'r':
        y = GRID_Y + idx * CELL
        self.v.draw_box(GRID_X, y, GRID_W, CELL)
      else:
        x = GRID_X + idx * CELL
        self.v.draw_box(x, GRID_Y, CELL, GRID_H)
      self.v.set_dither(16)

    for item in self.anim_boxes:
      bx = item[0]
      by = item[1]
      life = item[2]
      d = 5 + (life % 10)
      self.v.set_dither(d)
      self.v.draw_box(GRID_X + bx * CELL * 3, GRID_Y + by * CELL * 3, CELL * 3, CELL * 3)
      self.v.set_dither(16)

  def draw_quit_dialog(self):
    w = 190
    h = 70
    x = (400 - w) // 2
    y = (240 - h) // 2
    self.v.set_dither(2)
    self.v.draw_box(0, 0, 400, 240)
    self.v.set_dither(16)
    self.v.set_draw_color(1)
    self.v.draw_rbox(x, y, w, h, 4)
    self.v.set_draw_color(0)
    self.v.draw_rframe(x, y, w, h, 4)
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(x + 18, y + 26, "Go back title?")
    self.v.draw_str(x + 18, y + 48, "Enter: title  BS: cancel")
    self.v.set_draw_color(1)

  def draw_gameover_dialog(self):
    w = 220
    h = 84
    x = (400 - w) // 2
    y = (240 - h) // 2
    self.v.set_dither(2)
    self.v.draw_box(0, 0, 400, 240)
    self.v.set_dither(16)
    self.v.set_draw_color(1)
    self.v.draw_rbox(x, y, w, h, 4)
    self.v.set_draw_color(0)
    self.v.draw_rframe(x, y, w, h, 4)
    self.v.set_font("u8g2_font_profont22_mf")
    if self.completed:
      self.v.draw_str(x + 22, y + 26, "CLEAR!")
      self.v.draw_str(x + 22, y + 50, f"Score:{self.score}")
    else:
      self.v.draw_str(x + 22, y + 26, "GAME OVER")
      self.v.set_font("u8g2_font_profont15_mf")
      self.v.draw_str(x + 22, y + 50, "You made 3 mistakes.")
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(x + 22, y + 68, "Enter or BS: title")
    self.v.set_draw_color(1)

  def draw_title(self):
    w = 240
    h = 132
    x = (400 - w) // 2 - 10
    y = (240 - h) // 2 + 40

    self.v.set_draw_color(1)
    self.v.draw_image(200-160,120-100,self.images['title'])

    self.v.set_font("u8g2_font_profont15_mf")
    for i in range(len(DIFF_ORDER)):
      item = DIFF_ORDER[i]
      yy = y + 48 + i * 22
      if item == self.difficulty:
        self.v.draw_rbox(x + 14, yy - 13, w - 28, 18, 3)
        self.v.set_draw_color(0)
        self.v.draw_str(x + 24, yy, item)
        self.v.set_draw_color(1)
      else:
        self.v.draw_str(x + 24, yy, item)

    self.v.draw_str(x + 18, y + h - 16, "Arrows/scroll + Enter  BS: quit")

  def handle_mouse(self):
    self.m.update()
    if not self.m.active:
      self.last_mouse_cell = None
      return
    pt = self.m.get_point()
    mx = pt[0]
    my = pt[1]
    if mx >= GRID_X and mx < GRID_X + GRID_W and my >= GRID_Y and my < GRID_Y + GRID_H:
      cx = (mx - GRID_X) // CELL
      cy = (my - GRID_Y) // CELL
      self.cursor_x = clamp(cx, 0, 8)
      self.cursor_y = clamp(cy, 0, 8)

  def read_key(self):
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

  def move_difficulty(self, d):
    idx = 0
    for i in range(len(DIFF_ORDER)):
      if DIFF_ORDER[i] == self.difficulty:
        idx = i
        break
    idx += d
    if idx < 0:
      idx = len(DIFF_ORDER) - 1
    elif idx >= len(DIFF_ORDER):
      idx = 0
    self.difficulty = DIFF_ORDER[idx]

  def set_difficulty_from_scroll(self, raw):
    if raw == 255:
      self.last_scroll = 255
      return
    if self.last_scroll == 255:
      self.last_scroll = raw
      return
    diff = raw - self.last_scroll
    if diff <= -10:
      self.move_difficulty(1)
      self.last_scroll -= 10
    elif diff >= 10:
      self.move_difficulty(-1)
      self.last_scroll += 10

  def handle_key(self, k):
    if k is None:
      return

    if self.state == STATE_TITLE:
      if k == KEY_UP or k == KEY_LEFT:
        self.move_difficulty(-1)
      elif k == KEY_DOWN or k == KEY_RIGHT:
        self.move_difficulty(1)
      elif k == KEY_ENTER:
        self.reset_game(self.difficulty)
      elif k == KEY_BS:
        self.running = False
      elif k == b'1':
        self.difficulty = 'Easy'
      elif k == b'2':
        self.difficulty = 'Medium'
      elif k == b'3':
        self.difficulty = 'Hard'
      return

    if self.state == STATE_GAMEOVER_DIALOG:
      if k == KEY_ENTER or k == KEY_BS or k == b'q':
        self.state = STATE_TITLE
        self.last_scroll = 255
      return

    if self.state == STATE_QUIT_DIALOG:
      if k == KEY_ENTER:
        self.state = STATE_TITLE
        self.last_scroll = 255
      elif k == KEY_BS or k == b'q':
        self.state = STATE_PLAYING
      return

    sound = False
    if k == KEY_UP:
      self.move_cursor(0, -1)
      sound = True
    elif k == KEY_DOWN:
      self.move_cursor(0, 1)
      sound = True
    elif k == KEY_LEFT:
      self.move_cursor(-1, 0)
      sound = True
    elif k == KEY_RIGHT:
      self.move_cursor(1, 0)
      sound = True
    elif k == KEY_ENTER:
      self.fill_selected()
    elif k == b'q' or k == KEY_BS:
      self.state = STATE_QUIT_DIALOG
    elif k >= b'1' and k <= b'9':
      self.selected_num = k[0] - 48
    if sound:
      pass

  def handle_touch_buttons(self):
    keys = self.v.get_tp_keys()
    if not keys:
      return

    if self.state == STATE_TITLE:
      self.set_difficulty_from_scroll(keys[0])
      return

    if self.state != STATE_PLAYING:
      return

    self.set_selected_from_scroll(keys[0])

    if keys[3] & 1:
      self.state = STATE_QUIT_DIALOG

  def draw_difficulty(self, x, y):
    d = self.difficulty
    self.v.set_draw_color(1)
    self.v.set_dither(16)
    self.v.draw_image(x,y,self.images[d])
    self.v.set_font("u8g2_font_profont22_mf")
    w = self.v.get_utf8_width(d)
    self.v.draw_utf8(x+48-w//2,y+140,d)

  def draw_bonus_message(self):
    if self.time_bonus_anm == 0:
      return
    if self.time_bonus_anm == 60:
      self.time_bonus_op_y = 110

    self.time_bonus_anm -= 1
    
    if self.time_bonus_op_y > 70:
      self.time_bonus_op_y -= (self.time_bonus_op_y -70)//4
    y = max(70, self.time_bonus_op_y)
    self.v.set_dither(min(16, self.time_bonus_anm))
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(275,y,f"Time Bonus! {self.time_bonus}")
    self.v.draw_str(276,y,f"Time Bonus! {self.time_bonus}")

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return
    self.v.set_font_mode(1)
    self.v.set_bitmap_mode(1)
    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()

    self.v.set_dither(16)

    if self.state == STATE_TITLE:
      self.draw_title()
      self.v.finished()
      return
    if self.state == STATE_BUILDING:
      self.v.set_font("u8g2_font_profont15_mf")
      self.v.draw_str(20, 130, "Building the level..")
      self.v.finished()
      return
      

    self.draw_status()
    self.draw_grid_highlight()
    self.draw_line_box_anims()
    self.draw_numbers()
    self.draw_grid_lines()
    self.draw_side_numbers()
    self.draw_difficulty(275,50)
    self.draw_completion_effect()
    self.draw_bonus_message()

    if self.state == STATE_QUIT_DIALOG:
      self.draw_quit_dialog()

    if self.state == STATE_GAMEOVER_DIALOG:
      self.draw_gameover_dialog()

    self.v.finished()

  def loop(self):
    self.v.callback(self.update)
    while self.running:
      if not self.v.callback_exists():
        break
      k = self.read_key()
      self.handle_key(k)
      if self.state == STATE_PLAYING:
        self.handle_mouse()
        self.handle_touch_buttons()
        self.update_anims()
      else:
        self.handle_touch_buttons()
      if not self.v.active:
        pdeck.delay_tick(50)
      else:
        time.sleep_ms(60)
    if self.sound:
      self.sound.__exit__(None, None, None)
      self.sample.__exit__(None, None, None)
    self.v.callback(None)


def main(vs, args):
  diff = 'Medium'
  if len(args) >= 2:
    a = args[1].lower()
    if a == 'easy':
      diff = 'Easy'
    elif a == 'medium':
      diff = 'Medium'
    elif a == 'hard':
      diff = 'Hard'

  v = vs.v
  el = elib.esclib()

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  game = NudocGame(vs, diff)
  game.loop()

  v.print(el.display_mode(True))
  print("Finished.", file=vs)
