import time as _time
import sys

# System-shortcut second-key ids: get_tp_keys() bit = byte_index*8 + bit.
# Used with vscreen.register_shortcut(). Slider is the implicit modifier.
SHORTCUT_BL = 24
SHORTCUT_BR = 25
SHORTCUT_UP = 40
SHORTCUT_UPRIGHT = 41
SHORTCUT_RIGHT = 42
SHORTCUT_DOWNRIGHT = 43
SHORTCUT_DOWN = 44
SHORTCUT_DOWNLEFT = 45
SHORTCUT_LEFT = 46
SHORTCUT_UPLEFT = 47
SHORTCUT_A = 48
SHORTCUT_B = 49

def vscreen(screen_num=None):
  from vscreen import VscreenStream
  return VscreenStream()

def get_screen_size():
  return (400, 240)

def get_utf8_width(ch):
  # Display width in terminal cells: East-Asian wide/fullwidth chars take 2.
  # Used by jp_input to position the kana/kanji pre-edit buffer.
  import unicodedata
  if isinstance(ch, int):
    ch = chr(ch)
  elif isinstance(ch, (bytes, bytearray)):
    try:
      ch = ch.decode('utf-8')
    except Exception:
      return 1
  if not ch:
    return 1
  return 2 if unicodedata.east_asian_width(ch[0]) in ('W', 'F') else 1

def get_screen_num():
  return 2

def change_screen(screen):
  pass

def show_screen_num():
  pass

_inverted = False

def screen_invert(value=None):
  global _inverted
  if value is None:
    return _inverted
  _inverted = bool(value)
  import json
  from js import emulator_post_raw
  emulator_post_raw(json.dumps({'type': 'invert', 'value': _inverted}))
  return _inverted

def wifi_connected():
  return True   # the browser host is online; lets auto_connect short-circuit

def led(led_index, brightness=0):
  pass

def rtc(t=None):
  import time
  lt = _time.localtime()
  return (lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_wday, lt.tm_hour, lt.tm_min, lt.tm_sec)

def shutdown():
  pass

def delay_tick(tick):
  _time.sleep(tick / 1000)

def change_priority(p=False):
  pass

def clipboard_copy(s):
  if isinstance(s, (bytes, bytearray)):
    s = s.decode('utf-8', 'replace')
  from js import emulator_clip_set
  emulator_clip_set(str(s))

def clipboard_paste():
  # Device returns bytes (mp_obj_new_bytes); match that so callers like PEM's
  # insert_str (which does bytearray.extend) get bytes, not str.
  from js import emulator_clip_get
  return str(emulator_clip_get()).encode('utf-8')

def cmd_exists(screen_num):
  return False

def cmd_execute(command, screen_cmdshell, screen_dest=None):
  pass

def set_default_terminal_font_size(size):
  pass

def get_default_terminal_font_size():
  return 1

def update_app_list(screen_num, value):
  pass

def init():
  pass

def shared_filelist(filename=None):
  return []

def completion():
  return ('', 0)

def run_completion(timeout_ms=None):
  return None

def callback_completion(fn=None):
  pass
