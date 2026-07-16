import time
import math
import random
import array
import os
import argparse
import pdeck
import esclib as elib
import audio
import fontloader
import gpt_l as gpt
import json
import misc_utils
import gc
from anm import anm_sequencer, anm_object

KEY_ENTER = b'\r'
KEY_BS = b'\b'
KEY_ESC = b'\x1b'
KEY_UP_SEQ = b'\x1b[A'
KEY_DOWN_SEQ = b'\x1b[B'

STATE_QUESTION = 0
STATE_REVEAL = 1
STATE_TRANSITION = 2

STATUS_LOADING = 0
STATUS_READY = 1
STATUS_DONE = 2
STATUS_ERROR = 3

DIALOG_NONE = 0
DIALOG_MENU = 1
DIALOG_MESSAGE = 2

CARD_W = 340
CARD_H = 116+30
ANSWER_MAX = 40
QUESTION_MAX_LINES = 4
QUESTION_LINE_GAP = 22
QUESTION_TOP_Y = 24

MENU_W = 250
MENU_H = 86
MESSAGE_W = 320
MESSAGE_H = 112

EXAMPLE_CACHE_FILE = "/sd/data/flashcards.json"


def clamp(v, a, b):
  if v < a:
    return a
  if v > b:
    return b
  return v


def parse_flashcards(filename):
  cards = []
  with open(filename, 'r') as f:
    for line in f:
      s = line.strip()
      if not s:
        continue
      if s.startswith('- '):
        body = s[2:]
        pos = body.find(':')
        if pos <= 0:
          continue
        word = body[:pos].strip()
        meaning = body[pos + 1:].strip()
        if word and meaning:
          cards.append((word, meaning))
  return cards


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


def shuffle_list(lst):
  for i in range(len(lst) - 1, 0, -1):
    j = random.getrandbits(16) % (i + 1)
    t = lst[i]
    lst[i] = lst[j]
    lst[j] = t


def wrap_text_lines(v, text, max_width, max_lines, font):
  v.set_font(font)
  words = text.split(' ')
  lines = []
  cur = ""

  i = 0
  while i < len(words):
    word = words[i]
    candidate = word if cur == "" else cur + " " + word
    if cur == "" and v.get_utf8_width(word) > max_width:
      part = ""
      j = 0
      while j < len(word):
        c = word[j]
        test = part + c
        if part != "" and v.get_utf8_width(test) > max_width:
          lines.append(part)
          if len(lines) >= max_lines:
            return lines
          part = c
        else:
          part = test
        j += 1
      cur = part
      i += 1
      continue

    if v.get_utf8_width(candidate) <= max_width:
      cur = candidate
      i += 1
      continue

    if cur != "":
      lines.append(cur)
      if len(lines) >= max_lines:
        return lines
      cur = ""
      continue

    lines.append(word)
    if len(lines) >= max_lines:
      return lines
    i += 1

  if cur != "" and len(lines) < max_lines:
    lines.append(cur)

  if len(lines) == 0:
    lines.append("")

  return lines


class FlashcardsApp:
  def __init__(self, vs, filename, reverse_mode=False, novoice = False, model_name = None):
    self.vs = vs
    self.novoice = novoice
    self.model_name = model_name    # -m: LLM registry entry for example sentences
    self.v = vs.v
    self.filename = filename
    self.el = elib.esclib()
    self.running = True

    self.cards = []
    self.index = 0
    self.total = 0
    self.correct = 0
    self.wrong = 0

    self.status = STATUS_LOADING
    self.error_message = ""

    self.reverse_mode = reverse_mode
    self.state = STATE_QUESTION
    self.answer = ""
    self.submitted_correct = False
    self.show_answer = False
    self.cursor_phase = 0
    self.current_tick = time.ticks_us()
    fontname = 'u8g2_lubb12_te'
    fontloader.load(fontname)
    self.q_font = fontloader.font_list[fontname]
    self.a_font = "u8g2_font_profont22_mf"

    fontname = 'u8g2_font_lubR10_te'
    fontloader.load(fontname)
    self.m_font = fontloader.font_list[fontname]
    self.card_from_x = 400
    self.card_to_x = 30
    self.card_x = 400
    self.card_y = 44
    
    self.anim_seq = anm_sequencer()
    self.card_anim = None
    self.dialog_anim_obj = None

    self.anim_mode = 'idle'
    self.transition_old = None
    self.transition_new = None
    self.transition_dir = -1

    self.dialog_mode = DIALOG_NONE
    self.dialog_anim = False
    self.dialog_y_hidden = -140
    self.dialog_menu_y = 74
    self.dialog_message_y = 62
    self.menu_items = ["Make an example", "Read aloud"]
    self.menu_index = 0
    self.dialog_busy = False
    self.dialog_status = ""
    self.example_text = ""
    self.example_lines = []
    self.example_word = ""
    self.dialog_task = None
    self.dialog_task_word = ""
    self.tts_filename = "/sd/work/flashcards_tts.wav"

    self.gpt = None
    self.gpt_ready = False

    self.example_cache = {}
    self.load_example_cache()

    self.audio_init()
    self.ai_init()
    self.load_cards()

  def audio_init(self):
    self.sound_enabled = False
    self.sound = None
    try:
      audio.sample_rate(24000)
      self.sound = audio.wavetable(3)
      self.sound.__enter__()
      self.sound.set_wavetable(0, make_square_wave(256))
      self.sound.set_wavetable(1, make_triangle_wave(256))
      self.sound.set_adsr(0, 2, 680, 1.0, 0.05)
      self.sound.set_adsr(1, 1, 1500, 0.2, 500)
      self.sound_enabled = True
    except Exception as e:
      print("flashcards audio init failed:", e)
      self.sound_enabled = False

  def ai_init(self):
    # Defer building the LLM client until the first example/TTS request: it
    # imports the heavier gpt frontend and reads /config/gpt.json, so keeping it
    # off the launch path keeps flashcards quick to open.
    self.gpt = None
    self.gpt_ready = False
    self.model = None
    self._ai_tried = False

  def ensure_ai(self):
    """Build the LLM client on first use from /config/gpt.json (-m picks the
    entry; default is the registry default). Handles OpenAI Responses and local /
    third-party Chat endpoints alike. Returns True when ready."""
    if self._ai_tried:
      return self.gpt_ready
    self._ai_tried = True
    try:
      import gpt as gpt_front   # lazy: model registry + Responses/Chat client builder
      registry = gpt_front.load_registry(None)
      entry = gpt_front.resolve_entry(registry, self.model_name)
      self.gpt = gpt_front.init_client(entry, self.vs, False, registry)
      self.model = entry['model']
      self.gpt_ready = self.gpt is not None
    except Exception as e:
      print("flashcards gpt init failed:", e)
      self.gpt = None
      self.gpt_ready = False
    return self.gpt_ready

  def load_example_cache(self):
    self.example_cache = {}
    try:
      if not misc_utils.file_exists(EXAMPLE_CACHE_FILE):
        return

      with open(EXAMPLE_CACHE_FILE, 'r') as f:
        data = json.load(f)

      if type(data) is dict:
        self.example_cache = data
    except Exception as e:
      print("flashcards cache load error:", e)
      self.example_cache = {}

  def save_example_cache(self):
    try:

      tmpfile = EXAMPLE_CACHE_FILE + ".tmp"
      with open(tmpfile, 'w') as f:
        json.dump(self.example_cache, f)
      try:
        os.remove(EXAMPLE_CACHE_FILE)
      except OSError:
        pass
      os.rename(tmpfile, EXAMPLE_CACHE_FILE)
      return True
    except Exception as e:
      print("flashcards cache save error:", e)
      return False

  def get_example_cache_key(self, word):
    return word.strip().lower()

  def get_cached_example(self, word):
    key = self.get_example_cache_key(word)
    if key in self.example_cache:
      value = self.example_cache[key]
      if type(value) is str and value.strip():
        return value.strip()
    return None

  def set_cached_example(self, word, example):
    key = self.get_example_cache_key(word)
    if not key:
      return False
    example = example.strip()
    if not example:
      return False
    self.example_cache[key] = example
    return self.save_example_cache()

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

  def cleanup(self):
    if self.sound:
      self.sound.__exit__(None, None, None)
      self.sound = None

  def load_cards(self):
    try:
      self.cards = parse_flashcards(self.filename)
      if len(self.cards) == 0:
        self.status = STATUS_ERROR
        self.error_message = "No flashcards found."
        return
      self.reset_session()
    except Exception as e:
      self.status = STATUS_ERROR
      self.error_message = str(e)
      print("flashcards load error:", e)

  def reset_session(self):
    if len(self.cards) == 0:
      self.status = STATUS_ERROR
      self.error_message = "No flashcards found."
      return
    shuffle_list(self.cards)
    self.index = 0
    self.total = len(self.cards)
    self.correct = 0
    self.wrong = 0
    self.transition_old = None
    self.transition_new = None
    self.close_dialog()
    self.status = STATUS_READY
    self.start_question_anim()

  def get_card(self, idx=None):
    if idx is None:
      idx = self.index
    if idx < 0 or idx >= len(self.cards):
      return None
    return self.cards[idx]

  def start_question_anim(self):
    self.state = STATE_QUESTION
    card = self.get_card()
    if self.reverse_mode:
      self.answer = ""
    elif card and card[0]:
      self.answer = card[0][0].upper()
    else:
      self.answer = ""
    self.submitted_correct = False
    self.show_answer = False
    self.anim_mode = 'question_in'
    self.card_anim = anm_object(
        duration_ms = 200,
        props = {'card_x': [anm_object.ease_out, 400, 30]}
    )
    self.anim_seq.register('card', self.card_anim)

  def start_transition(self):
    next_idx = self.index + 1
    if next_idx >= self.total:
      self.status = STATUS_DONE
      self.anim_mode = 'idle'
      return
    self.transition_old = self.get_card(self.index)
    self.transition_new = self.get_card(next_idx)
    self.state = STATE_TRANSITION
    self.anim_mode = 'swap'
    self.card_anim = anm_object(
        duration_ms = 200,
        props = {
            'old_x': [anm_object.ease_in_out, 30, -400],
            'new_x': [anm_object.ease_in_out, 400, 30]
        }
    )
    self.anim_seq.register('card', self.card_anim)

  def finish_transition(self):
    self.index += 1
    self.transition_old = None
    self.transition_new = None
    self.state = STATE_QUESTION
    card = self.get_card()
    if self.reverse_mode:
      self.answer = ""
    elif card and card[0]:
      self.answer = card[0][0].upper()
    else:
      self.answer = ""
    self.submitted_correct = False
    self.show_answer = False
    self.anim_mode = 'idle'
    self.card_x = self.card_to_x
    if 'card' in self.anim_seq.anms:
      self.anim_seq.unregister('card')
    self.card_anim = None

  def normalize_word(self, s):
    return s.strip().lower()

  def toggle_reverse_mode(self):
    self.reverse_mode = not self.reverse_mode
    if self.status == STATUS_READY:
      self.start_question_anim()

  def submit_answer(self):
    card = self.get_card()
    if not card:
      return

    if self.reverse_mode:
      self.state = STATE_REVEAL
      self.submitted_correct = False
      self.show_answer = True
      return

    word = card[0]
    if self.normalize_word(self.answer) == self.normalize_word(word):
      self.submitted_correct = True
      self.correct += 1
      self.beep_ok()
    else:
      self.submitted_correct = False
      self.wrong += 1
      self.show_answer = True
    self.state = STATE_REVEAL

  def next_after_reveal(self):
    self.start_transition()

  def read_key(self):
    ret = self.v.read_nb(8)
    if not ret or ret[0] <= 0:
      return None
    data = ret[1].encode("ascii")
    if data == b"\x1b":
      return KEY_ESC
    return data

  def open_menu_dialog(self):
    if self.dialog_mode != DIALOG_NONE:
      return
    self.menu_index = 0
    self.dialog_busy = False
    self.dialog_status = ""
    self.dialog_mode = DIALOG_MENU
    self.dialog_anim = True
    self.dialog_anim_obj = anm_object(
        duration_ms=160,
        props={'dialog_y': [anm_object.ease_out, self.dialog_y_hidden, self.dialog_menu_y]}
    )
    self.anim_seq.register('dialog', self.dialog_anim_obj)

  def open_message_dialog(self, text, busy=False):
    self.example_text = text
    self.example_lines = wrap_text_lines(self.v, text, MESSAGE_W - 28, 5, self.q_font)
    self.dialog_busy = busy
    self.dialog_mode = DIALOG_MESSAGE
    self.dialog_anim = True
    if busy:
      self.dialog_anim_obj = anm_object(
          duration_ms=160,
          props={'dialog_y': [anm_object.ease_out, self.dialog_y_hidden, self.dialog_message_y]}
      )
      self.anim_seq.register('dialog', self.dialog_anim_obj)

  def close_dialog(self):
    self.dialog_mode = DIALOG_NONE
    self.dialog_anim = False
    if 'dialog' in self.anim_seq.anms:
      self.anim_seq.unregister('dialog')
    self.dialog_anim_obj = None
    self.dialog_busy = False
    self.dialog_status = ""
    self.dialog_task = None
    self.example_text = ""
    self.example_lines = []

  def current_word(self):
    card = self.get_card()
    if not card:
      return ""
    return card[0]

  def speak_tts(self, word):

    if not self.ensure_ai():
      self.open_message_dialog("AI unavailable. Check /config/gpt.json or API key.", False)
      return
    try:
      # We don't want gc run for a while
      gc.collect()
      print("Asking tts..")
      res = self.gpt.tts_stream(word)#, voice='alloy')

      if res and res.status_code == 200:
        print("Got response")
        stream = getattr(res, "raw", getattr(res, "s", res))
        try:
          gpt.play_audio_stream(self.vs, stream)
        except Exception as e:
          print(f"Streaming failed: {e}. Falling back to file mode.", file=self.vs)
        res.close()

      if not res:
        self.open_message_dialog("Failed to synthesize speech.", False)
        return
    except Exception as e:
      print("flashcards tts error:", e)
      self.open_message_dialog("TTS error: " + str(e), False)
    return True


  def make_example(self, word):
    cached = self.get_cached_example(word)
    if cached:
      self.open_message_dialog(cached, False)
      if not self.novoice:
        self.speak_tts(cached)
      return

    if not self.ensure_ai():
      self.open_message_dialog("AI unavailable. Check /config/gpt.json or API key.", False)
      return
    try:
      prompt = 'Make one short and natural example sentence using this word or idiom: "{}". Return only the sentence.'.format(word)
      message = self.gpt.complete(prompt, self.model)
      if not message:
        self.open_message_dialog("Failed to get example.", False)
        return
      message = message.strip()
      self.set_cached_example(word, message)
      self.open_message_dialog(message, False)
      if not self.novoice:
        self.speak_tts(message)
    except Exception as e:
      print("flashcards example error:", e)
      self.open_message_dialog("AI error: " + str(e), False)

  def run_menu_action(self):
    word = self.current_word()
    if not word:
      return
    if self.menu_index == 1:
      self.speak_tts(word)
      return
    if self.menu_index == 0:
      cached = self.get_cached_example(word)
      if cached:
        self.open_message_dialog(cached, False)
        if not self.novoice:
          self.speak_tts(cached)
        return
      self.open_message_dialog("Generating example...", True)
      self.dialog_task = 'example'
      self.dialog_task_word = word

  def handle_dialog_key(self, k):
    if self.dialog_mode == DIALOG_MENU:
      if k == KEY_BS or k == KEY_ESC:
        self.close_dialog()
        return True
      if k == KEY_DOWN_SEQ:
        self.menu_index += 1
        if self.menu_index >= len(self.menu_items):
          self.menu_index = 0
        return True
      if k == KEY_UP_SEQ:
        self.menu_index -= 1
        if self.menu_index < 0:
          self.menu_index = len(self.menu_items) - 1
        return True
      if k == KEY_ENTER:
        self.run_menu_action()
        return True
      return True

    if self.dialog_mode == DIALOG_MESSAGE:
      if self.dialog_busy:
        return True
      if k == KEY_BS or k == KEY_ESC or k == KEY_ENTER:
        self.close_dialog()
        return True
      return True

    return False

  def handle_key(self, k):
    keys = self.v.get_tp_keys()

    if keys and (keys[3] & 1):
      self.running = False
      return

    if k is None:
      return

    if self.dialog_mode != DIALOG_NONE:
      self.handle_dialog_key(k)
      return

    if k == KEY_UP_SEQ and self.status == STATUS_READY and self.state != STATE_TRANSITION:
      self.toggle_reverse_mode()
      return

    if k == KEY_DOWN_SEQ and self.status == STATUS_READY and self.state != STATE_TRANSITION:
      self.open_menu_dialog()
      return

    if k == KEY_ESC:
      self.running = False
      return
    if self.status == STATUS_DONE and k == KEY_BS:
      self.running = False
      return

    if self.status != STATUS_READY:
      if self.status == STATUS_DONE and k == KEY_ENTER:
        self.reset_session()
      return

    if self.state == STATE_TRANSITION:
      return

    if self.state == STATE_QUESTION:
      if k == KEY_ENTER:
        self.submit_answer()
        return

      if self.reverse_mode:
        return

      if k == KEY_BS:
        if len(self.answer) > 1:
          self.answer = self.answer[:-1]
        return
      if len(k) == 1 and k >= b'a' and k <= b'z':
        if len(self.answer) < ANSWER_MAX:
          self.answer += chr(k[0] - 32)
        return
      if len(k) == 1 and k >= b'A' and k <= b'Z':
        if len(self.answer) < ANSWER_MAX:
          self.answer += chr(k[0])
        return
      return

    if self.state == STATE_REVEAL:
      if k == KEY_ENTER:
        self.next_after_reveal()

  def update_anim(self):
    self.cursor_phase += 1
    self.anim_seq.update(time.ticks_ms())
    
    if self.card_anim:
      if hasattr(self.card_anim, 'card_x'):
        self.card_x = int(self.card_anim.card_x)
        
    if self.anim_mode == 'question_in':
      if self.card_anim and self.card_anim.get_time() >= 1.0:
        self.anim_mode = 'idle'
        
    elif self.anim_mode == 'swap':
      if self.card_anim and self.card_anim.get_time() >= 1.0:
        self.finish_transition()

    if self.dialog_anim:
      if self.dialog_anim_obj and self.dialog_anim_obj.get_time() >= 1.0:
        self.dialog_anim = False

  def process_dialog_task(self):
    if self.dialog_task == 'example':
      task_word = self.dialog_task_word
      self.dialog_task = None
      self.make_example(task_word)

  def draw_centered_text(self, y, text, font="u8g2_font_profont22_mf"):
    self.v.set_font(font)
    w = self.v.get_utf8_width(text)
    x = 200 - w // 2
    self.v.draw_utf8(x, y, text)

  def draw_question_lines(self, x, meaning):
    self.v.set_font(self.q_font)
    lines = wrap_text_lines(self.v, meaning, CARD_W - 24, QUESTION_MAX_LINES, self.q_font)
    y = self.card_y + QUESTION_TOP_Y + 40 - len(lines)*10
    i = 0
    while i < len(lines):
      line = lines[i]
      lw = self.v.get_utf8_width(line)
      lx = x + CARD_W // 2 - lw // 2
      if lx < x + 10:
        lx = x + 10
      self.v.draw_utf8(lx, y + i * QUESTION_LINE_GAP, line)
      i += 1

  def draw_card(self, x, card, answer_text, reveal_answer, state_mode):
    if not card:
      return

    word = card[0]
    meaning = card[1]

    self.v.set_draw_color(1)
    self.v.set_dither(16)
    self.v.draw_rbox(x, self.card_y, CARD_W, CARD_H, 5)

    self.v.set_draw_color(0)

    if self.reverse_mode:
      #self.v.set_font("u8g2_font_profont22_mf")
      word_lines = wrap_text_lines(self.v, word, CARD_W - 24, 3, self.a_font)
      y = self.card_y + QUESTION_TOP_Y + 44 - len(word_lines) * 10
      i = 0
      while i < len(word_lines):
        line = word_lines[i].upper()
        lw = self.v.get_utf8_width(line)
        lx = x + CARD_W // 2 - lw // 2
        if lx < x + 10:
          lx = x + 10
        self.v.draw_utf8(lx, y + i * QUESTION_LINE_GAP, line)
        i += 1
      self.v.set_font(self.q_font)
    else:
      self.v.set_font(self.q_font)
      self.draw_question_lines(x, meaning)
      self.v.set_font("u8g2_font_profont22_mf")


    if self.reverse_mode:
      display_text = ""
      if reveal_answer:
        display_text = meaning
      if display_text:
        lines = wrap_text_lines(self.v, display_text, CARD_W - 24, 3, self.q_font)
        answer_y = self.card_y + 96
        i = 0
        while i < len(lines):
          lw = self.v.get_utf8_width(lines[i])
          ax = x + CARD_W // 2 - lw // 2
          self.v.draw_utf8(ax, answer_y + i * 20, lines[i])
          i += 1
    else:
      display_text = answer_text.upper()
      if reveal_answer:
        display_text = word.upper()

      aw = self.v.get_str_width(display_text)
      ax = x + CARD_W // 2 - aw // 2
      answer_y = self.card_y + 88 + 30
      self.v.draw_str(ax, answer_y, display_text)

      blink_on = ((self.cursor_phase // 36) % 2) == 0
      if state_mode == STATE_QUESTION and blink_on:
        line_w = 100
        if aw + 16 > line_w:
          line_w = aw + 16
        self.v.draw_h_line(x + CARD_W // 2 - line_w // 2, answer_y + 6 , line_w)

    self.v.set_draw_color(1)

  def draw_header(self):
    self.v.set_draw_color(1)
    self.v.draw_box(0, 0, 400, 20)
    self.v.set_draw_color(0)
    self.v.set_font("u8g2_font_profont15_mf")
    if self.status == STATUS_READY:
      if self.reverse_mode:
        txt = " Flashcards [Reverse]  {}/{}".format(self.index + 1, self.total)
      else:
        txt = " Flashcards  {}/{}  OK:{}  NG:{}".format(self.index + 1, self.total, self.correct, self.wrong)
    elif self.status == STATUS_DONE:
      if self.reverse_mode:
        txt = " Flashcards [Reverse] finished"
      else:
        txt = " Flashcards finished  OK:{}  NG:{}".format(self.correct, self.wrong)
    elif self.status == STATUS_ERROR:
      txt = " Flashcards error"
    else:
      txt = " Flashcards loading"
    self.v.draw_str(6, 15, txt)
    self.v.set_draw_color(1)

  def draw_footer(self):
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.set_draw_color(1)
    if self.status == STATUS_READY:
      if self.reverse_mode:
        if self.state == STATE_QUESTION:
          self.draw_centered_text(220, "Enter reveal meaning, Up toggle, Down menu, Esc/L quit", "u8g2_font_profont15_mf")
        elif self.state == STATE_REVEAL:
          self.draw_centered_text(220, "Enter next, Up toggle, Down menu", "u8g2_font_profont15_mf")
      else:
        if self.state == STATE_QUESTION:
          self.draw_centered_text(220, "Enter submit, Up reverse, Down menu, Esc/L quit", "u8g2_font_profont15_mf")
        elif self.state == STATE_REVEAL:
          if self.submitted_correct:
            self.draw_centered_text(220, "Correct! Enter next, Up reverse, Down menu", "u8g2_font_profont15_mf")
          else:
            self.draw_centered_text(220, "Wrong. Enter next, Up reverse, Down menu", "u8g2_font_profont15_mf")
    elif self.status == STATUS_DONE:
      self.draw_centered_text(210, "All cards done.", "u8g2_font_profont22_mf")
      if self.reverse_mode:
        self.draw_centered_text(232, "Enter repeat, Esc/BS/L quit", "u8g2_font_profont15_mf")
      else:
        self.draw_centered_text(232, "Enter repeat, Esc/BS/L quit", "u8g2_font_profont15_mf")
    elif self.status == STATUS_ERROR:
      self.draw_centered_text(210, "Load error", "u8g2_font_profont22_mf")
      self.draw_centered_text(232, self.error_message, "u8g2_font_profont15_mf")
    else:
      self.draw_centered_text(220, "Loading...", "u8g2_font_profont22_mf")

  def draw_ready(self):
    card = self.get_card()
    if not card:
      return

    if self.state == STATE_TRANSITION:
      old_x = int(self.card_anim.old_x) if self.card_anim and hasattr(self.card_anim, 'old_x') else -400
      new_x = int(self.card_anim.new_x) if self.card_anim and hasattr(self.card_anim, 'new_x') else 30

      if self.transition_old:
        self.draw_card(old_x, self.transition_old, self.answer, self.show_answer, STATE_REVEAL)
      if self.transition_new:
        self.draw_card(new_x, self.transition_new, "", False, STATE_QUESTION)
      return

    reveal = self.state == STATE_REVEAL and (self.reverse_mode or (not self.submitted_correct))
    shown_answer = self.answer
    if (not self.reverse_mode) and self.state == STATE_REVEAL and self.submitted_correct:
      shown_answer = card[0]

    self.draw_card(self.card_x, card, shown_answer, reveal, self.state)

  def get_dialog_y(self, target_y):
    if not self.dialog_anim and (not self.dialog_anim_obj or self.dialog_anim_obj.get_time() >= 1.0):
      return target_y
    if self.dialog_anim_obj and hasattr(self.dialog_anim_obj, 'dialog_y'):
      return int(self.dialog_anim_obj.dialog_y)
    return target_y

  def draw_dialog_backdrop(self):
    self.v.set_draw_color(1)
    self.v.set_dither(4)
    self.v.draw_box(0, 20, 400, 220)
    self.v.set_dither(16)

  def draw_menu_dialog(self):
    y = self.get_dialog_y(self.dialog_menu_y)
    x = (400 - MENU_W) // 2

    self.v.set_draw_color(1)
    self.v.draw_rbox(x, y, MENU_W, MENU_H, 6)
    self.v.set_draw_color(0)
    self.v.draw_rframe(x, y, MENU_W, MENU_H, 6)
    self.v.set_font("u8g2_font_profont22_mf")

    self.v.set_font("u8g2_font_profont15_mf")
    i = 0
    while i < len(self.menu_items):
      iy = y + 30 + i * 20
      if i == self.menu_index:
        self.v.set_draw_color(0)
        self.v.draw_box(x + 10, iy - 12, MENU_W - 20, 16)
        self.v.set_draw_color(1)
        self.v.draw_str(x + 18, iy, self.menu_items[i])
        self.v.set_draw_color(0)
      else:
        self.v.draw_str(x + 18, iy, self.menu_items[i])
      i += 1

    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(x + 12, y + MENU_H - 8, "Enter select  BS close  Up/Down move")
    self.v.set_draw_color(1)

  def draw_message_dialog(self):
    y = self.get_dialog_y(self.dialog_message_y)
    x = (400 - MESSAGE_W) // 2

    self.v.set_draw_color(1)
    self.v.draw_rbox(x, y, MESSAGE_W, MESSAGE_H, 6)
    self.v.set_draw_color(0)
    self.v.draw_rframe(x, y, MESSAGE_W, MESSAGE_H, 6)

    self.v.set_font("u8g2_font_profont22_mf")
    if self.dialog_busy:
      self.v.draw_str(x + 14, y + 22, "Working")

    self.v.set_font(self.m_font)
    lines = self.example_lines
    if not lines:
      lines = [""]

    ly = y + 44
    i = 0
    while i < len(lines):
      self.v.draw_utf8(x + 14, ly + i * 17 - (0 if self.dialog_busy else 20), lines[i])
      i += 1

    if self.dialog_busy:
      dots = (self.cursor_phase // 10) % 4
      self.v.draw_str(x + 14, y + MESSAGE_H - 10, "Please wait" + "." * dots)
    else:
      self.v.draw_str(x + 14, y + MESSAGE_H - 10, "Enter/BS close")

    self.v.set_draw_color(1)

  def draw_dialog(self):
    if self.dialog_mode == DIALOG_NONE:
      return
    self.draw_dialog_backdrop()
    if self.dialog_mode == DIALOG_MENU:
      self.draw_menu_dialog()
    elif self.dialog_mode == DIALOG_MESSAGE:
      self.draw_message_dialog()

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return
    self.update_anim()
    self.v.set_font_mode(1)
    self.v.set_bitmap_mode(1)
    self.v.set_dither(16)

    self.draw_header()

    if self.status == STATUS_READY:
      self.draw_ready()

    self.draw_footer()
    self.draw_dialog()
    self.v.finished()

  def loop(self):
    self.v.callback(self.update)
    while self.running:
      if not self.v.callback_exists():
        break

      self.last_tick = self.current_tick
      self.current_tick = time.ticks_us()

      k = self.read_key()
      self.handle_key(k)

      if self.dialog_task and self.dialog_mode == DIALOG_MESSAGE and self.dialog_busy:
        self.process_dialog_task()

      if not self.v.active:
        pdeck.delay_tick(50)
      else:
        time.sleep_ms(40)

    self.v.callback(None)
    self.cleanup()


def main(vs, args):
  v = vs.v
  el = elib.esclib()

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  parser = argparse.ArgumentParser(
            description='flashcards')
  parser.add_argument('-r', '--reverse', action='store_true', help='start in reverse mode')
  parser.add_argument('-v', '--novoice', action='store_true', help='Turn off reading aloud the example sentence')
  parser.add_argument('-m', '--model', default=None, help='LLM for example sentences: a name from /config/gpt.json (default: registry default)')
  parser.add_argument('filename', nargs='?', help='flashcard file')
  pargs = parser.parse_args(args[1:])

  if not pargs.filename:
    print("Usage: flashcards [-r] [filename]", file=vs)
    v.print(el.display_mode(True))
    return

  app = FlashcardsApp(vs, pargs.filename, pargs.reverse, pargs.novoice, pargs.model)
  app.loop()

  v.print(el.display_mode(True))
  print("Finished.", file=vs)
