import sys
# On a PC (CPython) install stand-ins for the device-only modules below before
# they are imported. On the device this branch is skipped entirely.
_IS_PC = sys.implementation.name != 'micropython'
if _IS_PC:
  import pc_compat
  pc_compat.install()

import network, socket
import auto_connect
import codec_config
import ujson
import wifi
import time
import math
import urequests as requests
import pdeck
import pdeck_utils as pu
import esclib as elib
import argparse
import ubinascii
import audio
import wav_play
import recorder
import setuni
import os
import re
import gc

API_KEY_FILENAME = "/config/openai_api_key"
# On a PC the key lives under ~/.config/gpt/ (with $OPENAI_API_KEY as fallback).
PC_API_KEY_FILENAME = "~/.config/gpt/openai_api_key"

def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

def parse_inline_directives(message, references, images, args, vs):
  idx = 0
  result = ""
  mod_args = {}
  changed = False

  while True:
    start = message.find('[[', idx)
    if start == -1:
      result += message[idx:]
      break

    end = message.find(']]', start)
    if end == -1:
      result += message[idx:]
      break

    result += message[idx:start]
    block = message[start+2:end].strip()
    handled = False

    if len(block) > 0 and block[0] == '-':
      try:
        opt_args = block.split()
      except Exception:
        opt_args = []

      i = 0
      ok = True
      while i < len(opt_args):
        opt = opt_args[i]

        if opt == '-m' or opt == '--model':
          if i + 1 < len(opt_args):
            mod_args['model'] = opt_args[i + 1]
            i += 2
            handled = True
          else:
            print("Inline option error: -m requires a value", file=vs)
            ok = False
            break

        elif opt == '-e' or opt == '--effort':
          if i + 1 < len(opt_args):
            mod_args['effort'] = opt_args[i + 1]
            i += 2
            handled = True
          else:
            print("Inline option error: -e requires a value", file=vs)
            ok = False
            break

        elif opt == '-j' or opt == '--jp':
          mod_args['jp'] = True
          i += 1
          handled = True

        elif opt == '-c' or opt == '--clipboard':
          mod_args['clipboard'] = True
          i += 1
          handled = True

        elif opt == '-nf' or opt == '--no-format':
          mod_args['no_format'] = True
          i += 1
          handled = True

        elif opt == '-n' or opt == '--nosave':
          mod_args['nosave'] = True
          i += 1
          handled = True

        elif opt == '-v' or opt == '--voice':
          mod_args['voice'] = True
          i += 1
          handled = True

        elif opt == '-vt' or opt == '--voice-type':
          if i + 1 < len(opt_args):
            mod_args['voice_type'] = opt_args[i + 1]
            i += 2
            handled = True
          else:
            print("Inline option error: -vt requires a value", file=vs)
            ok = False
            break

        elif opt == '-i' or opt == '--image':
          i += 1
          handled = True
          while i < len(opt_args) and not opt_args[i].startswith('-'):
            img_path = opt_args[i]
            if img_path.startswith("http://") or img_path.startswith("https://"):
              images.append(img_path)
            else:
              try:
                with open(img_path, 'rb') as f:
                  images.append(f.read())
              except Exception:
                print(f'Inline option error when opening image {img_path}', file=vs)
            i += 1

        elif opt == '-f' or opt == '--file':
          print("Inline option note: -f is not supported in [[...]] blocks", file=vs)
          i += 1
          while i < len(opt_args) and not opt_args[i].startswith('-'):
            i += 1
          handled = True

        else:
          print(f"Inline option note: unsupported option {opt}", file=vs)
          i += 1
          handled = True

      if ok:
        changed = True

    else:
      if file_exists(block):
        try:
          with open(block, 'r') as f:
            references.append("---- " + block + " ----\n" + f.read())
          handled = True
          changed = True
        except Exception as e:
          print(f"Error reading inline reference {block}: {e}", file=vs)
      else:
        print(f"Inline reference file not found: {block}", file=vs)

    if not handled:
      result += message[start:end+2]

    idx = end + 2

  return result, changed, mod_args

def api_key_location():
  """Human-readable hint of where the key is expected, for error messages."""
  if _IS_PC:
    return PC_API_KEY_FILENAME + " (or set $OPENAI_API_KEY)"
  return API_KEY_FILENAME

def read_api_key():
  """Return the OpenAI API key, or False if none is configured. On the device it
  comes from /config/openai_api_key; on a PC from ~/.config/gpt/openai_api_key
  and, failing that, the $OPENAI_API_KEY environment variable."""
  paths = [API_KEY_FILENAME]
  if _IS_PC:
    paths = [os.path.expanduser(PC_API_KEY_FILENAME)]
  for path in paths:
    try:
      with open(path, "r") as f:
        key = f.read().strip()
      if key:
        return key
    except OSError:
      pass
  if _IS_PC:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
      return key.strip()
  return False

def make_log_filename():
  ctime = time.gmtime(time.time()+pu.timezone*60*15)
  name = f"gptlog{ctime[1]:02}{ctime[2]:02}_{ctime[3]:02}{ctime[4]:02}.md"
  if _IS_PC:
    log_dir = os.path.expanduser("~/.config/gpt/log")
    try:
      os.makedirs(log_dir, exist_ok=True)
    except Exception:
      pass
    return log_dir + "/" + name
  return "/sd/log/" + name

# ----------------------------------------------------------------------------
# Conversation session list (for --resume / --resume-id)
# ----------------------------------------------------------------------------
# A small rolling log of recent conversations so a separate gpt invocation can
# continue one server-side (Responses API previous_response_id). Each line is:
#   response_id, YYYY-MM-DD HH:MM, trimmed initial prompt
# Only the response id and datetime are parsed back; the prompt is a human hint.

SESSION_LIST_FILENAME = "/sd/log/gpt_session_list"
PC_SESSION_LIST_FILENAME = "~/.config/gpt/gpt_session_list"
SESSION_MAX = 10

def session_list_path():
  if _IS_PC:
    p = os.path.expanduser(PC_SESSION_LIST_FILENAME)
    try:
      os.makedirs(os.path.dirname(p), exist_ok=True)
    except Exception:
      pass
    return p
  return SESSION_LIST_FILENAME

def read_sessions():
  """Return [(response_id, datetime_str, prompt), ...], oldest first."""
  out = []
  try:
    with open(session_list_path(), "r") as f:
      for line in f:
        line = line.rstrip("\n")
        if not line:
          continue
        parts = line.split(",", 2)   # prompt (last field) may contain commas
        if len(parts) == 3:
          out.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
  except OSError:
    pass
  return out

def last_session_id():
  sessions = read_sessions()
  return sessions[-1][0] if sessions else None

def save_session(new_id, prompt, replace_id=None):
  """Record `new_id` as the latest session. If `replace_id` matches an existing
  entry (the same conversation continuing), move that entry to the end with the
  new id and keep its original prompt; otherwise append a new entry. Keeps only
  the most recent SESSION_MAX entries."""
  if not new_id:
    return
  sessions = read_sessions()
  t = time.gmtime(time.time() + pu.timezone * 60 * 15)
  now = "%04d-%02d-%02d %02d:%02d" % (t[0], t[1], t[2], t[3], t[4])
  trimmed = " ".join((prompt or "").split())[:60]   # collapse whitespace, cap
  moved = False
  if replace_id:
    for i in range(len(sessions)):
      if sessions[i][0] == replace_id:
        keep_prompt = sessions[i][2]
        del sessions[i]
        sessions.append((new_id, now, keep_prompt))
        moved = True
        break
  if not moved:
    sessions.append((new_id, now, trimmed))
  sessions = sessions[-SESSION_MAX:]
  try:
    with open(session_list_path(), "w") as f:
      for rid, dt, pr in sessions:
        f.write("%s, %s, %s\n" % (rid, dt, pr))
  except OSError:
    pass

def append_log(filename, text):
  try:
    with open(filename, "a") as f:
      f.write(text)
    return True
  except Exception:
    return False

def save_log(message, raw_response, log_filename=None):
  if log_filename == None:
    log_filename = make_log_filename()

  is_new = not file_exists(log_filename)
  mode = "w" if is_new else "a"

  with open(log_filename, mode) as f:
    if not is_new:
      f.write("\n\n----- iteration -----\n")
    f.write(message)
    f.write('\n')
    f.write(raw_response)

  try:
    pdeck.shared_filelist(log_filename)
  except Exception:
    pass
  try:
    pdeck.clipboard_copy(log_filename)
  except Exception:
    pass

  return log_filename

class chatgpt_util:
  def __init__(self,vs):
    self.vs = vs
    self.url = "https://api.openai.com/v1/responses"
    self.stt_url = "https://api.openai.com/v1/audio/transcriptions"
    self.tts_url = "https://api.openai.com/v1/audio/speech"
    self.api_key = ""

  def post(self, url, json=None):
    headers = {
      'Content-Type' : 'application/json',
      'Accept': 'application/json',
      'Authorization' : 'Bearer ' + self.api_key
      }
    return requests.post(url, headers=headers, data=json)

  def read_api_key(self):
    self.api_key = read_api_key()
    if self.api_key == False:
      print("No API key found. Put your key in %s" % api_key_location(), file=self.vs)
      return False
    return True
    

  def make_json(self, message, references, images=None, model="gpt-5.5", instructions = None, effort="medium"):
    content_items = []
    
    # Add text message
    if len(references) > 0:
      ref_text = "I put some attached text files as reference. Then answer the question by using attached information. You are not limited to reference the attached text, you can use all your knowledge. \n"
      for i, item in enumerate(references):
        ref_text += f"----- reference {i} -----\n{item}\n"
      ref_text += "----- Question -----\n"
      message = ref_text + message

    content_items.append({"type": "input_text", "text": message})

    # Add images
    if images:
      for img in images:
        if type(img) == str:
          img_url = img
        else:
          b64 = ubinascii.b2a_base64(img).decode('utf-8').strip()
          img_url = f"data:image/jpeg;base64,{b64}"
          
        content_items.append({
          "type": "input_image",
          "image_url": img_url
        })

    payload_dic = {
        "model" : model,
        "reasoning" : {
          "effort" : effort
        },
        "tools" : [
          { "type" : "web_search" }
          ],
        "input" : [
          {
            "type": "message",
            "role": "user",
            "content": content_items
          }
        ]
    }
    if instructions:
      payload_dic['instructions'] = instructions
      
    payload = ujson.dumps(payload_dic)
    #print(payload)
    return payload
    
  def ask(self,json):
    response = self.post(self.url,json.encode('utf-8'))
    #print(f"res{response.text}")
    try:
      response_data = response.json()
    except:
      print(f"Error: Non-JSON response ({response.status_code})", file=self.vs)
      print(response.text[:200], file=self.vs)
      response.close()
      return None
    response.close()

    if "error" in response_data and response_data['error'] != None:
      print(f"API Error: {response_data['error'].get('message', 'Unknown error')}", file=self.vs)
      return None

    try:
      # Responses API structure: output -> items
      # Each item can be a message with content
      # print(response_data)
      for item in response_data.get("output", []):
        if item.get("type") == "message":
          for content in item.get("content", []):
            if content.get("type") == "output_text" or content.get("type") =="text":
              return content.get("text")
    except Exception as e:
      print(f"Error parsing response: {e}", file=self.vs)
    
    return None

  def stt(self, filename, language = None):
    """Transcribes audio using Whisper (Stream Upload)"""
    boundary = "----MicroPythonPdeckBoundary"
    try:
      file_size = os.stat(filename)[6]
    except Exception as e:
      print(f"STT Error reading file stat: {e}", file=self.vs)
      return None
    
    header_bytes = (
        '--' + boundary + '\r\n' +
        'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n' +
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    
        #'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n' +
    # Build multipart fields after the audio file.
    # OpenAI transcription API accepts optional "language" as an ISO-639-1 code
    # such as "en", "ja", "fr".  When provided, it improves accuracy and latency.
    footer = (
        '\r\n--' + boundary + '\r\n' +
        'Content-Disposition: form-data; name="model"\r\n\r\ngpt-4o-mini-transcribe\r\n'
    )

    if language:
      footer += (
        '--' + boundary + '\r\n' +
        'Content-Disposition: form-data; name="language"\r\n\r\n' +
        str(language) + '\r\n'
      )

    footer += '--' + boundary + '--\r\n'
    footer_bytes = footer.encode('utf-8')
    
    content_length = len(header_bytes) + file_size + len(footer_bytes)
    print("Uploading audio to STT (streaming)...", file=self.vs)

    import usocket
    try:
      import ussl as ssl
    except ImportError:
      import ssl

    addr = usocket.getaddrinfo("api.openai.com", 443)[0][-1]
    s = usocket.socket()
    try:
      s.connect(addr)
      try:
        s = ssl.wrap_socket(s, server_hostname="api.openai.com")
      except TypeError:
        s = ssl.wrap_socket(s)
        
      req_head = (
          "POST /v1/audio/transcriptions HTTP/1.0\r\n"
          "Host: api.openai.com\r\n"
          "Connection: close\r\n"
          f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
          f"Content-Length: {content_length}\r\n"
          f"Authorization: Bearer {self.api_key}\r\n\r\n"
      ).encode('utf-8')

      s.write(req_head)
      s.write(header_bytes)

      buf = bytearray(16384)
      with open(filename, 'rb') as f:
        while True:
          sz = f.readinto(buf)
          if not sz:
            break
          s.write(memoryview(buf)[:sz])
          
      s.write(footer_bytes)

      l = s.readline()
      if not l:
        print("STT Error: Empty response", file=self.vs)
        return None
        
      status_code = int(l.split(None, 2)[1])
      
      while True:
        line = s.readline()
        if not line or line == b"\r\n":
          break
          
      body_chunks = []
      while True:
        sz = s.readinto(buf)
        if not sz:
          break
        body_chunks.append(bytes(memoryview(buf)[:sz]))
      body = b"".join(body_chunks)

      if status_code == 200:
        return ujson.loads(body).get('text')
      else:
        print(f"STT Error: {status_code} {body.decode('utf-8')}", file=self.vs)
        return None

    except Exception as e:
      print(f"STT Socket Error: {e}", file=self.vs)
      return None
    finally:
      s.close()

  def tts(self, text, filename, voice='alloy'):
    """Converts text to speech"""
    res = self.tts_stream(text, voice)
    if res and res.status_code == 200:
      with open(filename, 'wb') as f:
        f.write(res.content)
      res.close()
      return True
    return False

  def tts_stream(self, text, voice='alloy'):
    """Converts text to speech and returns a response object with a raw stream"""
    payload = ujson.dumps({
        "model": "tts-1-hd",
        #"model": "gpt-4o-mini-tts",
        "input": text,
        "voice": voice,
        #"speed" : 1.1,
        "response_format": "wav"
    }).encode('utf-8')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + self.api_key
    }
    
    # In MicroPython urequests, the response object itself can sometimes be treated as a stream
    return requests.post(self.tts_url, headers=headers, data=payload)

el = elib.esclib()

class ThinkingAnimation:
  _SPIN = '▌▄▐▀'
  _CHARS = '▁▂▃▄▅▆▇█'
  _COLS = [36, 92, 33, 92]  # cyan → lightgreen → yellow → lightgreen

  def __init__(self, vs, label='Asking GPT..'):
    self.vs = vs
    self.label = label
    self.tick = 0
    self.running = True
    self._el = elib.esclib()
    if _IS_PC:
      # No frame callback on a PC: just print the label once.
      print(label, file=vs)
      return
    if hasattr(self.vs, 'v'):
      self.v = vs.v
      self.v.callback(self.update)
    vs.write('\r\n\r\n')

  def update(self, e):
    if not self.running:
      self.v.finished()
      return

    self.tick += 1
    if self.tick % 15:
      self.v.finished()
      return
    t = self.tick // 15
    el = self._el
    nc = len(self._CHARS)

    self.v.set_draw_color(1)

    bar = ''.join(
      self._CHARS[int((math.sin((i - t * 0.5) * math.pi / 4) + 1) * (nc - 1) * 0.5 + 0.5)]
      for i in range(20)
    )
    spin = self._SPIN[t % len(self._SPIN)]
    col = self._COLS[(t // 8) % len(self._COLS)]
    self.vs.write(
      el.cur_up(2) +
      spin +
      ' ' + self.label + el.erase_to_end_of_current_line() + '\r\n' +
      bar +
      el.erase_to_end_of_current_line() + '\r\n' 
    )
    self.v.finished()
    return

  def stop(self):
    self.running = False
    if _IS_PC:
      return
    if hasattr(self.vs, 'v'):
      self.v.callback(None)
    el = self._el
    self.vs.write(
      el.cur_up(2) +
      el.erase_to_end_of_current_line() + '\r\n' +
      el.erase_to_end_of_current_line() + '\r\n' +
      el.cur_up(2) +
      el.cursor_mode(True)
    )

def record_audio(vs, filename, duration_sec=15, silent = False):
  """Records 16kHz mono audio"""
  sample_rate = 16000
  cc = codec_config.codec_config()
  cc.toggle_li(False)
  cc.set_agc(True)
  
  audio.sample_rate(sample_rate)
  if not silent:
    print(f"Recording... (press any key to stop)", file=vs)
  rec = recorder.stream_record('dummy', vs, 20000)
  # Use num_channels=1 for bandwidth savings as requested
  rec.record(filename, sample_rate * duration_sec, num_channels=1)
  
  # Wait for recording or keypress
  start = time.time()
  while audio.stream_record() and (time.time() - start) < duration_sec:
    pdeck.delay_tick(10)
    if vs.poll():
      ret = vs.read(1)
      break
    #if rec.time_silent == 2:
    #  break
  rec.stop()
  return filename

def play_audio(vs, filename):
  """Plays audio from file using wav_play"""
  wp = wav_play.wav_play()
  wp.open(filename)
  wp.play()
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break
  wp.stop()
  wp.close()

def play_audio_stream(vs, stream):
  """Plays audio from a stream using wav_play"""
  wp = wav_play.wav_play()
  wp.open_stream(stream)
  wp.play()
  print("Playing..", file=vs)
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break
  wp.stop()
  wp.close()

def get_message(vs):
  if _IS_PC:
    # Cooked-mode stdin already echoes and edits, so read a whole line.
    try:
      return input()
    except EOFError:
      return ""
  message=""
  while True:
    ch = vs.read(1)
    if ch == "\r":
      vs.write("\n")
      break
    if ch == chr(8):
      message = message[:-1]
      vs.write(ch)
      vs.write(el.erase_to_end_of_current_line())
    else:
      message += ch
      vs.write(ch)
  vs.write("\n\n")
  return message

def format(message):
  result = ""
  numfound = 0
  i = 0
  while len(message) > 0:
    pos = message.find("**")
    if pos == -1:
      result += message
      break
    result += message[:pos]
    numfound += 1
    if numfound&1:
      result += el.set_font_color(1)
    else:
      result += el.bold_off()
    message = message[pos+2:]
  if numfound & 1:
    result += el.bold_off()
  return result

def main(vs, args_in):
  #vs = pu.vscreen_stream()
  parser = argparse.ArgumentParser(
            description='ChatGPT query' )
  parser.add_argument('-a', '--agent', action='store_true', help='Enable Agent Mode')
  parser.add_argument('-n', '--nosave',action='store_true',help='do not save the result')
  parser.add_argument('-s', '--silent', action='store_true', help='Suppress progress output')
  parser.add_argument('-nf', '--no-format',action='store_true',help='do not format text (No bold)')
  parser.add_argument('-c', '--clipboard', action='store_true', help='use clipboard as reference text')
  parser.add_argument('-j', '--jp',action='store_true',help='Answer in Japanese')
  parser.add_argument('-f', '--file',nargs='+',action='store',help='Attach file(s) as reference. file1 file2...')
  parser.add_argument('-i', '--image', nargs='+', action='store',help='Attach image file(s) or image url(s). img1 img2...')
  parser.add_argument('-m', '--model',action='store',default='gpt-5.4',help='Model to use (e.g. gpt-5-mini)')
  parser.add_argument('-e', '--effort',action='store',default='medium',help='Reasoning effort (low, medium, high)')
  parser.add_argument('-v', '--voice',action='store_true',help='Use voice mode (STT and TTS)')
  parser.add_argument('-vt', '--voice-type',action='store',default='coral',help='Voice type for TTS (alloy, coral, echo, fable, onyx, nova, shimmer)')
  parser.add_argument('--log-file', action='store', default=None, help='Internal: reuse the same log filename across iterations')
  parser.add_argument('content', nargs='*',help='Content to ask')
  parser.add_argument('-q', nargs='+',help='Content to ask, use this when you want to specify content explicitly. If you specify a filename, it uses file content as a main content.')

  args = parser.parse_args(args_in[1:])

  if not auto_connect.check(vs, silent = True):
    print("Network is not available", file=vs)
    return

  gpt = chatgpt_util(vs)
  if not gpt.read_api_key():
    return

  message = ""
  instructions = None

  if args.voice and not args.q and not args.content:
    rec_file = "/sd/work/voice_rec.wav"
    record_audio(vs, rec_file)
    print("Transcribing...", file=vs)
    message = gpt.stt(rec_file)
    if not message:
      print("Failed to transcribe audio", file=vs)
      return
    print(f"You (STT): {message}", file=vs)
    instructions = "Response will be fed to OpenAI TTS engine. Optimize your responce for Text to speech. Basically keep it short, suitable input for your text to speech engine."
    
  elif not args.content and not args.q:
    message = get_message(vs)
  else:
    if args.content:
      message += ' '.join(args.content)
    if args.q:
      if len(args.q) == 1 and file_exists(args.q[0]):
        with open( args.q[0],"r") as f:
          message = f.read()
      else:
        message += ' '.join(args.q)
  if len(message) == 0:
    return

  references = []
  images = []

  message, _ , margs = parse_inline_directives(message, references, images, args, vs)

  jp = margs['jp'] if 'jp' in margs else args.jp
  
  ex1 = " and answer in Japanese" if jp else  ""
  message = message + ex1
  if jp:
    setuni.main(vs, ['setuni'])
    
  ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
  time_str = f"[User current time: {ctime[0]:04d}-{ctime[1]:02d}-{ctime[2]:02d} {ctime[3]:02d}:{ctime[4]:02d}]\n"
  message = time_str + message

  log_filename = args.log_file
  if log_filename == None:
    log_filename = make_log_filename()

  if args.agent:
    idx = 0
    while True:
        start = message.find('[[', idx)
        if start == -1:
            break
        end = message.find(']]', start)
        if end == -1:
            break
        match = message[start+2:end]
        idx = end + 2
        if file_exists(match):
            try:
                with open(match, 'r') as f:
                    references.append("---- " + match + " ----\n" + f.read())
            except Exception as e:
                print(f"Agent Mode: Error reading {match}: {e}", file=vs)
        else:
            print(f"Agent Mode: File {match} not found", file=vs)
            
    for auto_file in ["/sd/lib/data/agent_mode.md", "/sd/Documents/pd/README.md"]:
        if file_exists(auto_file):
            try:
                with open(auto_file, 'r') as f:
                    references.append("---- " + auto_file + " ----\n" + f.read())
            except Exception:
                pass
                
    agent_instruction = (
        "CRITICAL INSTRUCTION: You are an autonomous agent operating on a MicroPython device. "
        "You MUST execute commands by strictly using the markdown code blocks defined in agent_mode.md."
        "(`[type]:filename`, `python:execute`, `iterate`). "
    )
    
    if instructions:
        instructions += "\n\n" + agent_instruction
    else:
        instructions = agent_instruction
        
    message += "\n\n[SYSTEM NOTE: Follow the critical rules in agent_mode.md to perform actions.]"

  if args.file:
    files = args.file
    for file in files:
      if file.startswith("http://") or file.startswith("https://"):
        references.append(file)
        continue
        
      try:
        with open(file,'r') as f:
          references.append("---- " + file + " ----\n" + f.read())
      except Exception as e:
        print(f'Error when opening {file}', file=vs)
        return
  clipboard = margs['clipboard'] if 'clipboard' in margs else args.clipboard    
  if clipboard:
    references.append(pdeck.clipboard_paste().decode("utf-8"))
  
  if args.image:
    image_paths = args.image
    for img_path in image_paths:
      if img_path.startswith("http://") or img_path.startswith("https://"):
        images.append(img_path)
      else:
        try:
          with open(img_path, 'rb') as f:
            images.append(f.read())
        except Exception as e:
          print(f'Error when opening image {img_path}', file=vs)
          return
  model = margs['model'] if 'model' in margs else args.model
  if model in ('m','medium'):
    model = 'ngpt-5.4'
  elif model in ('h','high'):
    model = 'gpt-5.5'
  elif model in ('f','fast'):
    model = 'gpt-5.4-mini'

  effort = margs['effort'] if 'effort' in margs else args.effort
  if effort not in ('low', 'medium', 'high'):
    print(f"Invalid effort: {effort}. Using medium.", file=vs)
    effort = 'medium'

  if not args.silent:
    _anim = ThinkingAnimation(vs, "Asking GPT..")
    
  raw_response = gpt.ask(gpt.make_json(message, references, images, model, instructions = instructions, effort=effort))
  if not args.silent:
    _anim.stop()

  if not raw_response:
    return
  
  no_format = margs['no_format'] if 'no_format' in margs else args.no_format
  if no_format:
    response = raw_response
  else:
    response = format(raw_response)
  if response:
    print(response, file=vs)
    voice = margs['voice'] if 'voice' in margs else args.voice
    if voice:
      raw_response_sub = re.sub('\]\(ht.+?\)',']',raw_response)
      
      gc.collect()
      if args.silent:
        print("TTS processing..", file=vs)
      else:
        _anim = ThinkingAnimation(vs, "TTS..")
      res = gpt.tts_stream(raw_response_sub, voice=args.voice_type)
      if not args.silent:
        _anim.stop()
      print("TTS processing done", file=vs)
      if res and res.status_code == 200:
        # In MicroPython urequests, the raw socket is often .raw or .s
        # If none exist, we try the object itself as a backup
        stream = getattr(res, "raw", getattr(res, "s", res))
        #print(f"Connecting stream... {type(stream)}", file=vs)
        try:
          play_audio_stream(vs, stream)
        except Exception as e:
          print(f"Streaming failed: {e}. Falling back to file mode.", file=vs)
          # Re-save to file if possible or just report error
          # For now, we've already consumed part of the stream, so fallback is tricky
        res.close()

    nosave = margs['nosave'] if 'nosave' in margs else args.nosave
    if not nosave:
      try:
        saved_filename = save_log(message, raw_response, log_filename)
        print(el.bold_off(), file=vs)
        print(f"Saved to {saved_filename} and the filename copied to clipboard", file = vs)
      except Exception as e:
        print(f"Failed to save log: {e}", file=vs)
      
  if args.agent:
    idx = 0
    while True:
      start = raw_response.find("```", idx)
      while start != -1 and start != 0 and raw_response[start-1] != '\n':
        start = raw_response.find("```", start + 1)
        
      if start == -1:
        break
        
      end = raw_response.find("```", start + 3)
      while end != -1 and raw_response[end-1] != '\n':
        end = raw_response.find("```", end + 1)
        
      if end == -1:
        break
        
      block = raw_response[start+3:end]
      idx = end + 3
      
      first_nl = block.find('\n')
      if first_nl == -1:
        continue
        
      lang_tag = block[:first_nl].strip()
      code = block[first_nl+1:]
      
      if ":" in lang_tag and lang_tag != "python:execute":
        out_filename = lang_tag.split(":", 1)[1].strip()
        print(f"{el.set_font_color(1)}Agent: Saving to {out_filename}{el.bold_off()}", file=vs)
        
        if file_exists(out_filename):
          try:
            os.stat("/sd/backup")
          except OSError:
            try:
              os.mkdir("/sd/backup")
            except:
              pass
          base = out_filename.split("/")[-1]
          ctime = time.gmtime(time.time()+pu.timezone*60*15)
          backup_name = f"/sd/backup/{base}_{ctime[1]:02}{ctime[2]:02}_{ctime[3]:02}{ctime[4]:02}"
          try:
            os.rename(out_filename, backup_name)
            print(f"{el.set_font_color(1)}Agent: Backing up original file to {backup_name}{el.reset_font_color()}", file=vs)
          except:
            pass
            
        try:
          with open(out_filename, "w") as f:
            f.write(code)
        except Exception as e:
          print(f"{el.set_font_color(1)}Agent: Failed to write {out_filename}: {e}{el.reset_font_color()}", file=vs)
          
      elif lang_tag == "python:execute":
        print(f"{el.set_font_color(1)}Agent: Executing python block...{el.reset_font_color()}", file=vs)
        try:
          exec_locals = {'vs': vs, 'pdeck': pdeck}
          exec(code, globals(), exec_locals)
        except Exception as e:
          print(f"{el.set_font_color(1)}Agent: Execution Error: {e}{el.reset_font_color()}", file=vs)
          
      elif lang_tag == "iterate":
        print(  f"{el.set_font_color(1)}Agent: Iterating...{el.reset_font_color()}", file=vs)

        # Skipping the model and effort if AI put them
        iter_args_in = code.split()
        iter_args = []
        skip = False
        for item in iter_args:
          if skip:
            skip = False
            continue
          if item in  ('-m', '-e'):
            skip = True
            continue
          iter_args.args.append(item)
       
        iter_args = ['gpt', '-m', args.model, '-e', args.effort ] + code.split()
        has_log_file = False
        for item in iter_args:
          if item == '--log-file':
            has_log_file = True
            break
        if not has_log_file:
          iter_args.extend(['--log-file', log_filename])
        for i, item in enumerate(iter_args):
          if item == '-q':
            iter_args = iter_args[0:i+1] + [" ".join(iter_args[i+2:])]
            break
        print(f"{el.set_font_color(1)}Agent: Calling main with {iter_args}{el.reset_font_color()}", file=vs)
        main(vs, iter_args)
        print(el.bold_off(), file=vs)
