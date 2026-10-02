import time
import math
import random
import array
import os
import re
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


SCORE_RE = re.compile(r'^(.+?)\s*\((\d+)\s*/\s*(\d+)\)$')


def parse_score(text):
  """Split a card word that may carry a score suffix, e.g. 'critique (3/6)',
  into (word, success, failed). Missing score gives (word, 0, 0). The second
  number is the number of failures, not the number of attempts."""
  m = SCORE_RE.match(text.strip())
  if m:
    return m.group(1).strip(), int(m.group(2)), int(m.group(3))
  return text.strip(), 0, 0


def split_card_line(s):
  """Parse one '- word [(s/f)] : meaning' line. Returns
  (prefix, word, meaning, succ, fail) or None when it is not a card line.
  prefix is the original indentation plus the '- ' bullet, so the line can
  be written back exactly as it was (marker included)."""
  stripped = s.lstrip()
  if not stripped.startswith('- '):
    return None
  prefix = s[:len(s) - len(stripped)] + '- '
  body = stripped[2:]
  pos = body.find(':')
  if pos <= 0:
    return None
  word, succ, fail = parse_score(body[:pos])
  meaning = body[pos + 1:].strip()
  if not word or not meaning:
    return None
  return prefix, word, meaning, succ, fail


def parse_flashcards(filename):
  # Each card is [word, meaning, success_count, fail_count].
  cards = []
  with open(filename, 'r') as f:
    for line in f:
      parsed = split_card_line(line)
      if parsed:
        prefix, word, meaning, succ, fail = parsed
        cards.append([word, meaning, succ, fail])
  return cards


def format_card_line(prefix, word, succ, fail, meaning, newline):
  if succ > 0 or fail > 0:
    text = "{}{} ({}/{})".format(prefix, word, succ, fail)
  else:
    text = "{}{}".format(prefix, word)
  return "{} : {}{}".format(text, meaning, newline)


def save_flashcard_scores(filename, log):
  """Rewrite the card lines of filename, applying the score updates recorded
  in log (list of [word, success_delta, fail_delta]). A card's '- word (s/f) :'
  line becomes '- word (new_s/new_f) :' with the totals accumulated. Only card
  lines are touched; every other line (headings, blanks, notes) is written
  back unchanged. Missing scores on disk are added from the totals.

  The whole new content is built in memory first and only then swapped in
  via a temp file, so an error can never leave the word file truncated.

  Returns the number of card lines updated, or None on failure."""
  if not log:
    return 0
  try:
    with open(filename, 'r') as f:
      lines = f.readlines()
  except Exception as e:
    print("flashcards score read error:", e)
    return None

  out = []
  updated = 0
  for line in lines:
    parsed = split_card_line(line)
    if not parsed:
      out.append(line)
      continue
    prefix, word, meaning, succ, fail = parsed
    i = 0
    while i < len(log):
      if log[i][0] == word:
        succ += log[i][1]
        fail += log[i][2]
        updated += 1
        break
      i += 1
    newline = "\n" if line.endswith("\n") else ""
    out.append(format_card_line(prefix, word, succ, fail, meaning, newline))

  tmp = filename + ".tmp"
  try:
    with open(tmp, 'w') as f:
      for line in out:
        f.write(line)
  except Exception as e:
    print("flashcards score write error:", e)
    try:
      os.remove(tmp)
    except OSError:
      pass
    return None

  # Keep the previous version around in case the user wants it back.
  try:
    with open(filename + ".bak", 'w') as f:
      for line in lines:
        f.write(line)
  except Exception as e:
    print("flashcards score backup error:", e)

  try:
    try:
      os.remove(filename)
    except OSError:
      pass
    os.rename(tmp, filename)
  except Exception as e:
    print("flashcards score replace error:", e)
    try:
      os.remove(tmp)
    except OSError:
      pass
    return None
  return updated


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
  def __init__(self, vs, filename, reverse_mode=True, novoice = False, model_name = None):
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

    # Score bookkeeping. score_log holds the [word, success, fail] deltas
    # earned during the current round, so a round can be written back to the
    # word file in one pass. attempt_recorded guards against counting the same
    # card twice (e.g. checking an example and then also submitting an answer).
    self.score_log = []
    self.round_succ = 0
    self.round_fail = 0
    self.saved_cards = 0
    self.attempt_recorded = False
    self.score_saved = True

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
    self.score_log = []
    self.round_succ = 0
    self.round_fail = 0
    self.saved_cards = 0
    self.attempt_recorded = False
    self.score_saved = True
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

  def card_word(self, card):
    if not card:
      return ""
    return card[0]

  def card_meaning(self, card):
    if not card:
      return ""
    return card[1]

  def card_score(self, card):
    """(success, fail) for a card, counting this round's pending deltas."""
    if not card:
      return 0, 0
    succ = card[2]
    fail = card[3]
    i = 0
    while i < len(self.score_log):
      if self.score_log[i][0] == card[0]:
        succ += self.score_log[i][1]
        fail += self.score_log[i][2]
        break
      i += 1
    return succ, fail

  def record_attempt(self, success):
    """Count the current card as one attempt: a success or a failure. An
    example / read-aloud counts as a failure (the user did not remember it);
    a plain reveal counts as success."""
    if self.attempt_recorded:
      return
    card = self.get_card()
    if not card:
      return
    self.attempt_recorded = True
    if success:
      self.round_succ += 1
    else:
      self.round_fail += 1
    self.score_log.append([card[0], 1 if success else 0, 0 if success else 1])
    self.score_saved = False

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
    self.attempt_recorded = False
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
      # One full round is over: persist the success/try scores to the word file.
      self.save_round_scores()
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
    self.attempt_recorded = False
    self.anim_mode = 'idle'
    self.card_x = self.card_to_x
    if 'card' in self.anim_seq.anms:
      self.anim_seq.unregister('card')
    self.card_anim = None

  def normalize_word(self, s):
    return s.strip().lower()

  def toggle_reverse_mode(self):
    was_recorded = self.attempt_recorded
    self.reverse_mode = not self.reverse_mode
    if self.status == STATUS_READY:
      self.start_question_anim()
      self.attempt_recorded = was_recorded

  def submit_answer(self):
    card = self.get_card()
    if not card:
      return

    if self.reverse_mode:
      # Reverse mode: hitting Enter only reveals the meaning. It counts as
      # a success only if the user did not ask for an example / read-aloud
      # first (those mean the word was not remembered).
      self.record_attempt(True)
      self.state = STATE_REVEAL
      self.submitted_correct = False
      self.show_answer = True
      return

    word = card[0]
    if self.normalize_word(self.answer) == self.normalize_word(word):
      self.submitted_correct = True
      self.correct += 1
      self.record_attempt(True)
      self.beep_ok()
    else:
      self.submitted_correct = False
      self.wrong += 1
      self.record_attempt(False)
      self.show_answer = True
    self.state = STATE_REVEAL

  def next_after_reveal(self):
    self.start_transition()

  def save_round_scores(self):
    """Write this round's success/fail counts back into the word file."""
    if self.score_saved or not self.score_log:
      self.score_saved = True
      return True
    n = save_flashcard_scores(self.filename, self.score_log)
    if n is None:
      return False
    self.score_saved = True
    self.saved_cards = n
    # Re-read the file so the in-memory cards carry the accumulated totals
    # (not just this round's deltas) on the next round.
    try:
      totals = {}
      for c in parse_flashcards(self.filename):
        totals[c[0]] = (c[2], c[3])
      i = 0
      while i < len(self.cards):
        t = totals.get(self.cards[i][0])
        if t:
          self.cards[i][2] = t[0]
          self.cards[i][3] = t[1]
        i += 1
    except Exception as e:
      print("flashcards score refresh error:", e)
    # The deltas are baked into the file and into self.cards now.
    self.score_log = []
    return True

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
    # Checking an example or hearing the word read aloud means the user did
    # not remember it, so the card counts as a failed try.
    self.record_attempt(False)
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

    if reveal_answer and self.state == STATE_REVEAL:
      # Definition is showing: report the card's score (this round included)
      # instead of the help line.
      succ, fail = self.card_score(card)
      self.v.set_draw_color(1)
      self.draw_centered_text(222, "score  {}/{}".format(succ, fail), "u8g2_font_profont22_mf")

    self.v.set_draw_color(1)

  def draw_header(self):
    self.v.set_draw_color(1)
    self.v.draw_box(0, 0, 400, 20)
    self.v.set_draw_color(0)
    self.v.set_font("u8g2_font_profont15_mf")
    if self.status == STATUS_READY:
      if self.reverse_mode:
        txt = " Flashcards [Reverse]  {}/{}  OK:{}  NG:{}".format(self.index + 1, self.total, self.round_succ, self.round_fail)
      else:
        txt = " Flashcards  {}/{}  OK:{}  NG:{}".format(self.index + 1, self.total, self.correct, self.wrong)
    elif self.status == STATUS_DONE:
      if self.score_saved and self.saved_cards > 0:
        extra = "  saved:{}".format(self.saved_cards)
      else:
        extra = ""
      if self.reverse_mode:
        txt = " Flashcards [Reverse] finished  OK:{}  NG:{}{}".format(self.round_succ, self.round_fail, extra)
      else:
        txt = " Flashcards finished  OK:{}  NG:{}{}".format(self.correct, self.wrong, extra)
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
      if self.state == STATE_REVEAL:
        # The score line under the card replaces the help message here.
        pass
      elif self.reverse_mode:
        self.draw_centered_text(220, "Enter reveal meaning, Up toggle, Down menu, Esc/L quit", "u8g2_font_profont15_mf")
      else:
        self.draw_centered_text(220, "Enter submit, Up reverse, Down menu, Esc/L quit", "u8g2_font_profont15_mf")
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
        self.draw_card(old_x, self.transition_old, "", True, STATE_REVEAL)
      if self.transition_new:
        self.draw_card(new_x, self.transition_new, "", False, STATE_QUESTION)
      return

    reveal = self.state == STATE_REVEAL
    self.draw_card(self.card_x, card, self.answer, reveal, self.state)

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

  # Parse arguments BEFORE touching the display: --help and argument errors
  # print plain text and call sys.exit(), so we must not be in graphics mode yet.
  parser = argparse.ArgumentParser(
            description='flashcards', vs=vs)
  parser.add_argument('-r', '--reverse', action='store_true', help='start in reverse mode (default)')
  parser.add_argument('-f', '--forward', action='store_true', help='start in forward mode (word shown, type the meaning)')
  parser.add_argument('-v', '--novoice', action='store_true', help='Turn off reading aloud the example sentence')
  parser.add_argument('-m', '--model', default=None, help='LLM for example sentences: a name from /config/gpt.json (default: registry default)')
  parser.add_argument('filename', nargs='?', help='flashcard file')
  try:
    pargs = parser.parse_args(args[1:])
  except SystemExit:
    # argparse already printed --help / the usage error to vs.
    # Nothing to draw, and the display must stay in text mode.
    return

  if not pargs.filename:
    print("Usage: flashcards [-f] [filename]", file=vs)
    return

  # Reverse mode (meaning -> word) is the default now.
  reverse = True
  if pargs.forward:
    reverse = False

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  try:
    app = FlashcardsApp(vs, pargs.filename, reverse, pargs.novoice, pargs.model)
    app.loop()
  finally:
    # Always restore text drawing, even if the app exits with an error.
    v.print(el.display_mode(True))

  print("Finished.", file=vs)
