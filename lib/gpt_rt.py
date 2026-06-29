import network, socket, ssl, ubinascii, ujson, urandom, time
import audio, codec_config, pdeck, pdeck_utils as pu
import os, sys, io
import argparse
import gpt_l as gpt
import gc
import esclib
import setuni
import auto_connect
import pngwriter

_el = esclib.esclib()

def load_app_list():
  result = []
  for path in ('/config/apps.json', '/config/agent_apps.json'):
    try:
      with open(path, 'r') as f:
        result += ujson.load(f)
    except:
      pass
  return result

class CaptureStream(io.IOBase):
  _MAX = 50000

  def __init__(self):
    self._parts = []
    self._total = 0

  def write(self, data):
    if isinstance(data, (bytes, bytearray)):
      data = data.decode('utf-8', 'replace')
    remaining = self._MAX - self._total
    if remaining <= 0:
      return
    if len(data) > remaining:
      data = data[:remaining]
    self._parts.append(data)
    self._total += len(data)

  def read(self, n=1):
    return ''

  def getvalue(self):
    return ''.join(self._parts)

def _parse_cmd_string(text):
  parts = []
  cur = ''
  in_quote = False
  quote = ''
  for ch in text:
    if in_quote:
      if ch == quote:
        in_quote = False
      else:
        cur += ch
    else:
      if ch in ('"', "'"):
        in_quote = True
        quote = ch
      elif ch == ' ':
        if cur:
          parts.append(cur)
          cur = ''
      else:
        cur += ch
  if cur:
    parts.append(cur)
  return parts

def load_references(file_list, vs):
  refs = []
  if not file_list:
    return refs
  for name in file_list:
    try:
      with open(name, "r") as f:
        refs.append("---- " + name + " ----\n" + f.read())
    except Exception as e:
      print("Failed to read reference %s: %s" % (name, e), file=vs)
  return refs

def build_session_instructions(model, file_list, references, app_list=None, agent=False):
  ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
  text = (
    "You are a helpful AI assistant. Keep your responses brief, conversational, and direct. "
    "You are chatting over a low latency voice link."
    f"[User current time: {ctime[0]:04d}-{ctime[1]:02d}-{ctime[2]:02d} {ctime[3]:02d}:{ctime[4]:02d}]\n"
  )

  if agent:
    text += "\nUse command_with_return to look up information before answering (e.g. list files with 'ls /sd/Documents/word*', read a file with 'cat /path'). Always call it when the user asks about files or device state.\nUse write_file to create or save files on the device filesystem before launching an app that needs them.\nWhen you get a logical question which can be solved by writing code, you can write Micropython code temporarily on /sd/py, filename starts temp_*, then delete after the creation (rm command). \n"
    text += "\nYou can see and drive other apps running on the device. Use list_running_apps to see which app is on which screen. Use switch_screen to bring a screen to the foreground. IMPORTANT: screen numbers in these tools are 0-based and match what list_running_apps reports (screen 0 is the Python REPL), but the device's GUI shows them 1-based, so the screen the user calls '2' is screen 1 here — always pass the 0-based number from list_running_apps, not the GUI number. Use capture_screen to take a screenshot of a screen and look at it (it is sent to you as an image) it take some time (about 0.3s), so requesting screenshot at high rate is not recommended. Use send_keys to type into the app currently in the foreground; include a newline or set enter=true to press Enter, and use escape sequences for special keys (Up=\\x1b[A, Down=\\x1b[B, Right=\\x1b[C, Left=\\x1b[D, Esc=\\x1b, Backspace=\\x08, Ctrl-X=\\x18). After acting, capture_screen again to confirm the result before continuing.\n"
    if app_list:
      text += "\nUse launch_app to open apps. Pass optional args (e.g. a file path) to open a specific file. Available apps:\n"
      for item in app_list:
        if isinstance(item, list) and len(item) == 2:
          name = item[0]
          info = item[1]
          desc = info.get('description', '') if isinstance(info, dict) else ''
          text += "  - %s: %s\n" % (name, desc)

  if file_list:
    text += "\n[Attached files: %s]\n" % ", ".join(file_list)

  if references:
    text += "\n\nThe user attached reference files. Use them when answering.\n"
    for i, item in enumerate(references):
      text += "\n----- reference %d -----\n%s\n" % (i, item)

  return text

@micropython.viper
def _ws_mask(dst: ptr8, src: ptr8, src_off: int, n: int, mask: ptr8):
  # XOR-mask n bytes of src (starting at src_off) into dst[0:n]. The WebSocket
  # mask repeats every 4 bytes keyed on the global byte position, so we index
  # the 4-byte mask with (src_off + i) & 3 to stay correct across chunks.
  i = 0
  while i < n:
    g = src_off + i
    dst[i] = src[g] ^ mask[g & 3]
    i += 1

class SimpleWS:
  def __init__(self, host, path, port=443, headers=None):
    self.sock = socket.socket()
    addr = socket.getaddrinfo(host, port)[0][-1]
    self.sock.connect(addr)

    try:
      self.sock = ssl.wrap_socket(self.sock, server_hostname=host)
    except TypeError:
      self.sock = ssl.wrap_socket(self.sock)
    except Exception:
      try:
        import ussl
        try:
          self.sock = ussl.wrap_socket(self.sock, server_hostname=host)
        except TypeError:
          self.sock = ussl.wrap_socket(self.sock)
      except Exception as e:
        raise Exception("TLS wrap failed: %s" % e)

    key = ubinascii.b2a_base64(bytes([urandom.getrandbits(8) for _ in range(16)])).strip()

    req = "GET %s HTTP/1.1\r\n" % path
    req += "Host: %s\r\n" % host
    req += "Connection: Upgrade\r\n"
    req += "Upgrade: websocket\r\n"
    req += "Sec-WebSocket-Version: 13\r\n"
    req += "Sec-WebSocket-Key: %s\r\n" % key.decode()
    if headers:
      for k in headers:
        req += "%s: %s\r\n" % (k, headers[k])
    req += "\r\n"

    self.sock.write(req.encode())

    l = self.sock.readline()
    if not l or b"101" not in l:
      raise Exception("WebSocket connection failed: " + str(l))
    while True:
      l = self.sock.readline()
      if not l or l == b"\r\n":
        break

    self.sock.setblocking(False)
    self.mask_buf = bytearray(1024)
    self.mask_mv = memoryview(self.mask_buf)

  def _recv_exact(self, n):
    res = bytearray(n)
    view = memoryview(res)
    read = 0
    while read < n:
      try:
        r = self.sock.readinto(view[read:])
        if r is None:
          time.sleep(0.005)
          continue
        if r == 0:
          raise Exception("Socket closed")
        read += r
      except OSError as e:
        if e.args[0] == 11:
          time.sleep(0.005)
          continue
        raise e
    return res

  def _recv_frame(self, block=False):
    # Reads a single WebSocket frame and returns (fin, opcode, payload), or
    # None when no data is available yet (only when block=False). When block
    # is True we are mid-message (waiting for continuation frames) and must
    # wait for the next frame rather than abandoning the partial message.
    while True:
      try:
        header = self.sock.read(2)
      except OSError as e:
        if e.args[0] == 11:
          if block:
            time.sleep(0.005)
            continue
          return None
        raise e
      except Exception as e:
        if "MBEDTLS_ERR_SSL_BAD_INPUT_DATA" in str(e):
          if block:
            time.sleep(0.005)
            continue
          return None
        raise e

      if not header:
        if block:
          time.sleep(0.005)
          continue
        return None
      break

    if len(header) < 2:
      # Got a partial header; the rest is guaranteed to follow.
      header = bytes(header) + bytes(self._recv_exact(2 - len(header)))

    b1, b2 = header[0], header[1]
    fin = b1 & 0x80
    opcode = b1 & 0x0f

    has_mask = b2 & 0x80
    length = b2 & 0x7f

    if length == 126:
      ext = self._recv_exact(2)
      length = (ext[0] << 8) | ext[1]
    elif length == 127:
      ext = self._recv_exact(8)
      length = 0
      for i in range(8):
        length = (length << 8) | ext[i]

    if has_mask:
      mask = self._recv_exact(4)

    payload = self._recv_exact(length) if length else bytearray()
    if has_mask:
      for i in range(length):
        payload[i] ^= mask[i % 4]

    return fin, opcode, payload

  def recv(self):
    # Reassembles fragmented messages: a logical message may span a leading
    # data frame (opcode 1/2, FIN=0) plus continuation frames (opcode 0) until
    # FIN is set. Control frames (ping/pong/close) may be interleaved between
    # fragments and are handled without disturbing the message being assembled.
    data = None
    while True:
      frame = self._recv_frame(block=data is not None)
      if frame is None:
        return None
      fin, opcode, payload = frame

      if opcode == 8:        # close
        self.sock.close()
        return None
      if opcode == 9:        # ping
        self.send(payload, opcode=10)
        continue
      if opcode == 10:       # pong
        continue

      if opcode == 0:        # continuation
        if data is None:
          continue           # stray continuation; ignore
        data += payload
      else:                  # 1 = text, 2 = binary: start of a message
        data = payload

      if fin:
        return data

  def _send_exact(self, data):
    view = memoryview(data)
    written = 0
    length = len(data)
    while written < length:
      try:
        w = self.sock.write(view[written:])
        if w is None:
          time.sleep(0.005)
          continue
        if w == 0:
          raise Exception("Socket closed during write")
        written += w
      except OSError as e:
        if e.args[0] == 11:
          time.sleep(0.005)
          continue
        raise e

  def send(self, data, opcode=1):
    if isinstance(data, str):
      data = data.encode()
    length = len(data)

    header = bytearray(2)
    header[0] = 0x80 | opcode
    mask = bytes([urandom.getrandbits(8) for _ in range(4)])

    if length < 126:
      header[1] = 0x80 | length
      self._send_exact(header)
    elif length < 65536:
      header[1] = 0x80 | 126
      ext = bytearray(2)
      ext[0] = (length >> 8) & 0xff
      ext[1] = length & 0xff
      self._send_exact(header)
      self._send_exact(ext)
    else:
      header[1] = 0x80 | 127
      ext = bytearray(8)
      for i in range(8):
        ext[7-i] = (length >> (i*8)) & 0xff
      self._send_exact(header)
      self._send_exact(ext)

    self._send_exact(mask)

    for offset in range(0, length, 1024):
      chunk_len = min(1024, length - offset)
      _ws_mask(self.mask_buf, data, offset, chunk_len, mask)
      self._send_exact(self.mask_mv[:chunk_len])

  def close(self):
    try:
      self.send(b"", opcode=8)
    except:
      pass
    self.sock.close()


class RealtimeAgent:
  def __init__(self, ws, vs, model, file_list, references, app_list=None, agent=False, language=None, headers=None):
    self.ws = ws
    self.vs = vs
    self.model = model
    self.headers = headers or {}
    self.file_list = file_list or []
    self.references = references
    self.app_list = app_list or []
    self.agent = agent
    self.language = language
    self.pending_fn_calls = {}
    self.sample_rate = 24000

    self.mic_buf_size = 10000
    self.mic_bufs = [memoryview(bytearray(self.mic_buf_size)), memoryview(bytearray(self.mic_buf_size))]
    self.mic_ready_idx = -1

    self.spk_buf_size = 8000
    self.spk_bufs = [memoryview(bytearray(self.spk_buf_size)), memoryview(bytearray(self.spk_buf_size))]
    self.zero_buf = memoryview(bytearray(self.spk_buf_size))

    # Lock-free single-producer/single-consumer ring buffer for audio playback.
    # Main thread writes; callback reads. No lock needed.
    self._ring_size = 262144*6  # 256 KB ≈ 5.3 s at 24 kHz PCM16 mono
    self._ring = bytearray(self._ring_size)
    self._ring_mv = memoryview(self._ring)
    self._ring_wpos = 0  # written only by main thread
    self._ring_rpos = 0  # written only by callback

    self.buffering = True
    # Pre-roll cushion before playback starts. Must be several spk buffers so a
    # late network burst doesn't drain the ring below one buffer (= underrun).
    # 4 buffers ≈ 0.83 s. Raise toward 6x if the link is jittery; lower for less
    # latency before the AI voice starts.
    self.buffer_threshold = self.spk_buf_size * 3
    self.mute_until = 0
    self.mic_muted = False
    self.vs_active = None
    self.last_play_time = 0

    # Idle auto-mute: when this screen is not the foreground one, the mic stops
    # transmitting anyway, but after auto_mute_ms of being inactive we also flip
    # the explicit mute state. auto_muted lets loop() undo it (and only it) when
    # the screen becomes active again, without clobbering a deliberate mute.
    self.auto_muted = False
    self.inactive_since = None     # ticks_ms when the screen went inactive, else None
    self.auto_mute_ms = 30000      # idle time before auto-muting while inactive

    self.cb_time_max = 0
    self.underrun_count = 0
    self.drop_count = 0
    self.last_stat_time = time.ticks_ms()

    self.ai_text = ""
    self.ai_text_printed = False
    self.user_text = ""
    self.user_text_partial = ""
    self.user_text_printed = False
    self.agent_executed_text = ""
    self.fn_calls_executed = 0

    # Reused across screen captures: 400x240 1-bit XBM = 50 bytes/row * 240.
    self.capture_buf = bytearray(12000)
    # base64 PNG waiting to be sent as a user image once the current response
    # closes (sending a user item mid-response is rejected by the server).
    self.pending_image = None

  @micropython.native
  def mic_callback(self, index):
    self.mic_ready_idx = index

  @micropython.native
  def spk_callback(self, index):
    t0 = time.ticks_us()
    dest = self.spk_bufs[index]
    buf_size = len(dest)
    rpos = self._ring_rpos % self._ring_size
    fill = (self._ring_wpos - self._ring_rpos)  % self._ring_size

    pdeck.led(2,int(fill * (100 / self._ring_size)))


    if self.buffering:
      if fill >= self.buffer_threshold and time.ticks_diff(time.ticks_ms(), self.mute_until) >= 0:
        self.buffering = False
      else:
        dest[:buf_size] = self.zero_buf[:buf_size]
        duration = time.ticks_diff(time.ticks_us(), t0)
        if duration > self.cb_time_max:
          self.cb_time_max = duration
        return

    if fill < buf_size:
      self.buffering = True
      self.underrun_count += 1
      print('underrun')
      if fill > 0:
        end = rpos + fill
        if end <= self._ring_size:
          dest[:fill] = self._ring_mv[rpos:end]
        else:
          tail = self._ring_size - rpos
          dest[:tail] = self._ring_mv[rpos:]
          dest[tail:fill] = self._ring_mv[:fill - tail]
        self._ring_rpos += fill #) % self._ring_size
      dest[fill:buf_size] = self.zero_buf[:buf_size - fill]
    else:
      end = rpos + buf_size
      if end <= self._ring_size:
        dest[:buf_size] = self._ring_mv[rpos:end]
      else:
        tail = self._ring_size - rpos
        dest[:tail] = self._ring_mv[rpos:]
        dest[tail:buf_size] = self._ring_mv[:buf_size - tail]
      self._ring_rpos += buf_size #end % self._ring_size
      self.last_play_time = time.ticks_ms()

    duration = time.ticks_diff(time.ticks_us(), t0)
    if duration > self.cb_time_max:
      self.cb_time_max = duration

  def start(self):
    cc = codec_config.codec_config()
    cc.toggle_li(False)
    cc.set_agc(True)
    cc.set_input_mixer(0x28)

    audio.sample_rate(self.sample_rate)

    num_samples = 0x7FFFFFFF

    audio.stream_setup(0, self.sample_rate, 1, num_samples, self.spk_callback)
    audio.stream_setdata(0, 0, self.spk_bufs[0])
    audio.stream_setdata(0, 1, self.spk_bufs[1])
    audio.stream_play(True)

    audio.stream_setup(1, self.sample_rate, 1, num_samples, self.mic_callback)
    audio.stream_setdata(1, 0, self.mic_bufs[0])
    audio.stream_setdata(1, 1, self.mic_bufs[1])
    audio.stream_record(True)

  def send_session_update(self):
    session = {
      "type": "realtime",
      "instructions": build_session_instructions(self.model, self.file_list, self.references, self.app_list, self.agent),
      "audio": {
        "input": {
          "format": {"type": "audio/pcm", "rate": self.sample_rate},
          "transcription": ({"model": "whisper-1", "language": self.language} if self.language else {"model": "whisper-1"}),
          "turn_detection": {"type": "server_vad"}
        },
        "output": {
          "format": {"type": "audio/pcm", "rate": self.sample_rate},
          "voice": "marin"
        }
      }
    }
    if self.agent:
      session["tool_choice"] = "auto"
      session["tools"] = [
        {
          "type": "function",
          "name": "command_with_return",
          "description": "Run a text command and return its output. Use to answer questions about files or content. Supported: ls (list files, supports glob patterns like 'word*'; 'ls -r path' lists recursively), cat (read file), head, tail, rm, mv, cp, mkdir, rmdir, grep (search in files), ping (check network reachability), dic (dictionary lookup), curl (get content from web), and 'analog_clock_set_timer <minutes>' (set a countdown timer). You can't use pipe '|', it's not Linux, do not use the undocumented options. Detailed usage are stated in README.md..",
          "parameters": {
            "type": "object",
            "properties": {
              "command": {
                "type": "string",
                "description": "Command with arguments, e.g. 'ls /sd/Documents' or 'ls /sd/Documents/word*' or 'cat /sd/notes.txt'"
              }
            },
            "required": ["command"]
          }
        },
        {
          "type": "function",
          "name": "launch_app",
          "description": "Launch a Pocket Deck application by its exact name, optionally passing arguments such as a file path to open",
          "parameters": {
            "type": "object",
            "properties": {
              "app_name": {
                "type": "string",
                "description": "The exact name of the app to launch as listed"
              },
              "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional extra arguments for the app, e.g. a file path like '/sd/test.txt'"
              }
            },
            "required": ["app_name"]
          }
        },
        {
          "type": "function",
          "name": "write_file",
          "description": "Write text content to a file on the device filesystem. Creates or overwrites the file.",
          "parameters": {
            "type": "object",
            "properties": {
              "path": {
                "type": "string",
                "description": "Absolute file path to write to, e.g. '/sd/data/puzzle.txt'"
              },
              "content": {
                "type": "string",
                "description": "Text content to write to the file"
              }
            },
            "required": ["path", "content"]
          }
        },
        {
          "type": "function",
          "name": "list_running_apps",
          "description": "List the apps currently running and which screen number each is on. Use this before switching, capturing, or driving an app.",
          "parameters": {
            "type": "object",
            "properties": {},
            "required": []
          }
        },
        {
          "type": "function",
          "name": "switch_screen",
          "description": "Bring a screen to the foreground so it becomes active. Required before capturing or sending keys to that screen. The screen number here is 0-based and matches what list_running_apps reports (screen 0 is the Python REPL), but the GUI shows screen numbers 1-based. So if the user wants to switch to screen 2, send 1 as the argument.",
          "parameters": {
            "type": "object",
            "properties": {
              "screen": {
                "type": "integer",
                "description": "Screen number to switch to (0-9)"
              }
            },
            "required": ["screen"]
          }
        },
        {
          "type": "function",
          "name": "capture_screen",
          "description": "Take a screenshot of a screen and send it to you as an image so you can read what is on it. If screen is given, switches to it first.",
          "parameters": {
            "type": "object",
            "properties": {
              "screen": {
                "type": "integer",
                "description": "Optional screen number to switch to and capture. If omitted, captures the current foreground screen."
              }
            },
            "required": []
          }
        },
        {
          "type": "function",
          "name": "send_keys",
          "description": "Type text / keystrokes into the foreground app. Use escape sequences for special keys (arrows \\x1b[A/B/C/D, Esc \\x1b, Backspace \\x08, Ctrl-X \\x18).",
          "parameters": {
            "type": "object",
            "properties": {
              "text": {
                "type": "string",
                "description": "Characters to inject as keyboard input"
              },
              "screen": {
                "type": "integer",
                "description": "Optional screen number to switch to before typing (input only reaches the foreground app)"
              },
              "enter": {
                "type": "boolean",
                "description": "If true, press Enter (carriage return) after the text"
              }
            },
            "required": ["text"]
          }
        }
      ]
    cfg = {"type": "session.update", "session": session}
    self.ws.send(ujson.dumps(cfg))

  def handle_audio_delta(self, msg):
    delta = msg.get("delta")
    if not delta:
      return
    if isinstance(delta, dict):
      audio_b64 = delta.get("audio")
    else:
      audio_b64 = delta
    if audio_b64:
      #pdeck.led(2,0)
      pdeck.led(3,0)
      raw = ubinascii.a2b_base64(audio_b64)
      #pdeck.led(2,40)
      n = len(raw)
      wpos = self._ring_wpos % self._ring_size
      rpos = self._ring_rpos % self._ring_size
      fill = (self._ring_wpos - self._ring_rpos + self._ring_size) % self._ring_size
      pdeck.led(2,int(fill * (100 / self._ring_size)))
      if n > self._ring_size - fill:
        self.drop_count += 1
        #pdeck.led(2,100)
        print("Ring buffer full. Dropping")
        return  # ring full; drop rather than corrupt
      end = wpos + n
      if end <= self._ring_size:
        self._ring_mv[wpos:end] = raw
      else:
        tail = self._ring_size - wpos
        raw_mv = memoryview(raw)
        self._ring_mv[wpos:] = raw_mv[:tail]
        self._ring_mv[:n - tail] = raw_mv[tail:]
      self._ring_wpos += n #% self._ring_size
      #pdeck.led(2,0)
      pdeck.led(3,5)

  def handle_text_delta(self, msg):
    delta = msg.get("delta")
    if isinstance(delta, str):
      if delta:
        if not self.ai_text_printed:
          print("\nAI: ", file=self.vs)
          self.ai_text_printed = True
        self.ai_text += delta
        self.vs.write(delta)
      return

    if isinstance(delta, dict):
      text = delta.get("text", "")
      if text:
        if not self.ai_text_printed:
          print("\nAI: ", file=self.vs)
          self.ai_text_printed = True
        self.ai_text += text
        self.vs.write(text)

  def handle_user_text_delta(self, text):
    if not text:
      return
    self.user_text_partial += text

  def handle_user_text_completed(self, text):
    if text:
      self.user_text = text
    elif self.user_text_partial:
      self.user_text = self.user_text_partial

  def print_user_text_if_ready(self):
    if self.user_text and not self.user_text_printed:
      print("\nYou: ", file=self.vs)
      self.vs.write(self.user_text)
      self.user_text_printed = True

  def reset_turn_text(self):
    self.ai_text = ""
    self.ai_text_printed = False
    self.user_text = ""
    self.user_text_partial = ""
    self.user_text_printed = False

  def _mute_audio(self, ms):
    self.buffering = True  # callback outputs silence; safe to reset ring now
    self._ring_wpos = 0
    self._ring_rpos = 0
    self.mute_until = time.ticks_add(time.ticks_ms(), ms)

  def _search_free_screen(self, launched, scnum=2):
    while True:
      if not pdeck.cmd_exists(scnum) and scnum not in launched:
        return scnum
      scnum += 1
      if scnum == 10:
        return -1

  def execute_command_with_return(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    command = args.get("command", "").strip()
    if not command:
      return "Error: no command specified"
    parts = _parse_cmd_string(command)
    if not parts:
      return "Error: empty command"
    modname = parts[0]
    cap = CaptureStream()
    try:
      exec("import %s" % modname, {})
      sys.modules[modname].main(cap, parts)
    except Exception as e:
      cap.write("Error: %s" % str(e))
    result = cap.getvalue()
    if not result:
      return "(no output)"
    if cap._total >= CaptureStream._MAX:
      result += "\n...(truncated)"
    return result

  def execute_write_file(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    path = args.get("path", "").strip()
    content = args.get("content", "")
    if not path:
      return "Error: no path specified"
    try:
      backup_msg = ""
      try:
        with open(path, "r") as f:
          existing = f.read()
        t = time.gmtime(time.time() + pu.timezone * 60 * 15)
        filename = path.split("/")[-1]
        backup_name = "%s_%02d%02d_%02d%02d" % (filename, t[1], t[2], t[3], t[4])
        try:
          os.mkdir("/sd/backup")
        except:
          pass
        with open("/sd/backup/" + backup_name, "w") as f:
          f.write(existing)
        backup_msg = " (backup: /sd/backup/%s)" % backup_name
      except OSError:
        pass
      with open(path, "w") as f:
        f.write(content)
      return "Written %d bytes to %s%s" % (len(content), path, backup_msg)
    except Exception as e:
      return "Error: %s" % str(e)

  def execute_list_running_apps(self, arguments):
    lines = [ "screen 0: Python REPL" ]
    try:
      apps_scnums = []
      for key in pu.app_list:
        app = pu.app_list[key]
        name = app.get('name', '?') if isinstance(app, dict) else str(app)
        lines.append("screen %s: %s" % (key, name))
        apps_scnums.append(key)
      for i in range(1, 10):
        if pdeck.cmd_exists(i) and i not in apps_scnums:
          lines.append(f"screen {i}: command line shell")
      lines.sort()
      print(lines)
    except Exception as e:
      return "Error: %s" % str(e)
    if not lines:
      return "(no running apps)"
    return "\n".join(lines)

  def execute_switch_screen(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
      scnum = int(args.get("screen"))
    except:
      return "Error: invalid arguments"
    pdeck.change_screen(scnum)
    pdeck.show_screen_num()
    return "Switched to screen %d" % scnum

  def execute_capture_screen(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    scnum = args.get("screen", None)
    if scnum is not None:
      try:
        scnum = int(scnum)
      except:
        return "Error: invalid screen"
      pdeck.change_screen(scnum)
      pdeck.show_screen_num()
      # Give the target one frame to render into the main buffer before capture.
      pdeck.delay_tick(40)
    target = "screen %d" % scnum if scnum is not None else "the current screen"
    self._mute_audio(800)
    try:
      v = pdeck.vscreen()
      # take_screenshot captures at the display loop's safe point (no tearing)
      # and blocks until the frame is ready. Must run off the display thread,
      # which it does here (gpt_rt's own thread).
      if not v.take_screenshot(0, 0, 400, 240, self.capture_buf):
        return "Error: screenshot timed out (display busy or screen not active)"
      png = pngwriter.encode_mono_xbm(self.capture_buf, 400, 240)
      b64 = ubinascii.b2a_base64(png).decode().strip()
    except Exception as e:
      return "Error capturing screen: %s" % str(e)
    # Defer the image send until response.done so we don't add a user item while
    # a response is still active (which the server rejects).
    self.pending_image = b64
    return "Captured %s. The screenshot is attached as an image; look at it and describe what you see." % target

  def execute_send_keys(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    text = args.get("text", "")
    if args.get("enter"):
      text += "\r"
    if not text:
      return "Error: no text specified"
    scnum = args.get("screen", None)
    if scnum is not None:
      try:
        pdeck.change_screen(int(scnum))
        pdeck.delay_tick(40)
      except:
        return "Error: invalid screen"
    try:
      v = pdeck.vscreen()
      v.send_char(text)
      print(text.encode('utf-8'))
    except Exception as e:
      return "Error sending keys: %s" % str(e)
    return "Sent %d key(s)" % len(text)

  def send_image_item(self, b64_png):
    evt = {
      "type": "conversation.item.create",
      "item": {
        "type": "message",
        "role": "user",
        "content": [
          {
            "type": "input_image",
            "image_url": "data:image/png;base64," + b64_png
          }
        ]
      }
    }
    self.ws.send(ujson.dumps(evt))

  def execute_function_call(self, call_id, name, arguments):
    if name == "command_with_return":
      return self.execute_command_with_return(arguments)
    if name == "write_file":
      return self.execute_write_file(arguments)
    if name == "list_running_apps":
      return self.execute_list_running_apps(arguments)
    if name == "switch_screen":
      return self.execute_switch_screen(arguments)
    if name == "capture_screen":
      return self.execute_capture_screen(arguments)
    if name == "send_keys":
      return self.execute_send_keys(arguments)
    if name != "launch_app":
      return "Unknown function: %s" % name
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    app_name = args.get("app_name", "")
    extra_args = args.get("args", [])
    for item in self.app_list:
      if not (isinstance(item, list) and len(item) == 2 and item[0] == app_name):
        continue
      info = item[1]
      if not (isinstance(info, dict) and info.get('type') == 'program'):
        continue
      command = [list(c) for c in info.get('command', [])]
      if extra_args and command:
        command[0] = [command[0][0]] + extra_args
      pref_scnum = info.get('screen_number', None)
      self._mute_audio(3000)
      launched = []
      first = True
      for one in command:
        scnum = self._search_free_screen(launched, pref_scnum if pref_scnum else 2)
        if scnum == -1:
          break
        launched.append(scnum)
        if first:
          pdeck.change_screen(scnum)
          first = False
        pu.launch(one, scnum)
      pdeck.show_screen_num()
      return "Launched %s" % app_name
    return "App not found: %s" % app_name

  def send_function_result(self, call_id, output):
    evt = {
      "type": "conversation.item.create",
      "item": {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output
      }
    }
    self.ws.send(ujson.dumps(evt))

  def process_event(self, msg):
    mtype = msg.get("type", "")
    #print(mtype, file=self.vs)
    if mtype == "response.audio.delta":
      self.handle_text_delta(msg)
    elif mtype == "response.output_audio_transcript.delta":
      #pass
      self.handle_text_delta(msg)
      #print(msg, file=self.vs)
    elif mtype == "response.output_audio_transcript.done":
      pass
      #print(msg, file=self.vs)

    elif mtype == "response.output_audio.delta":
      self.handle_audio_delta(msg)

    elif mtype == "response.text.delta":
      self.handle_text_delta(msg)

    elif mtype == "response.output_text.delta":
      self.handle_text_delta(msg)

    elif mtype == "conversation.item.input_audio_transcription.delta":
      self.handle_user_text_delta(msg.get("delta", ""))

    elif mtype == "conversation.item.input_audio_transcription.completed":
      self.handle_user_text_completed(msg.get("transcript", ""))

    elif mtype == "response.output_item.added":
      item = msg.get("item", {})
      if item.get("type") == "function_call":
        call_id = item.get("call_id", "")
        self.pending_fn_calls[call_id] = {"name": item.get("name", ""), "args": ""}

    elif mtype == "response.function_call_arguments.delta":
      call_id = msg.get("call_id", "")
      if call_id in self.pending_fn_calls:
        self.pending_fn_calls[call_id]["args"] += msg.get("delta", "")

    elif mtype == "response.output_item.done":
      item = msg.get("item", {})
      if item.get("type") == "function_call":
        call_id = item.get("call_id", "")
        fn_name = item.get("name", "")
        arguments = item.get("arguments", "")
        if not arguments and call_id in self.pending_fn_calls:
          arguments = self.pending_fn_calls[call_id].get("args", "")
        print("\n%s[Call]%s %s %s" % (_el.bold(), _el.bold_off(), fn_name, arguments), file=self.vs)
        # Always send a function result, even on failure — otherwise the call
        # never closes and the session hangs waiting for its output.
        try:
          result = self.execute_function_call(call_id, fn_name, arguments)
        except Exception as e:
          result = "Error: %s" % str(e)
        print("%s[Result]%s %s" % (_el.bold(), _el.bold_off(), result[:200]), file=self.vs)
        self.send_function_result(call_id, result)
        self.fn_calls_executed += 1
        self.pending_fn_calls.pop(call_id, None)

    elif mtype == "input_audio_buffer.speech_started":
      print("\n%s[User speaking... barge in detected]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
      self.buffering = True  # callback outputs silence; safe to reset ring
      self._ring_wpos = 0
      self._ring_rpos = 0

    elif mtype == "session.updated":
      pass  # print("\n[Session updated]", file=self.vs)

    elif mtype == "response.done":
      resp = msg.get("response", {})
      status = resp.get("status", "")
      if status and status != "completed":
        sd = resp.get("status_details", {})
        print("\n%s[Response %s]%s %s" % (_el.bold(), status, _el.bold_off(), ujson.dumps(sd)), file=self.vs)
      # Now that no response is active, attach a pending screenshot (if any) and
      # ask the model to respond to it.
      if self.pending_image is not None:
        self.send_image_item(self.pending_image)
        self.pending_image = None
      if self.fn_calls_executed > 0:
        self.ws.send(ujson.dumps({"type": "response.create"}))
        self.fn_calls_executed = 0
      self.reset_turn_text()

    elif mtype == "error":
      print("\n%s[Error from server]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
      print(ujson.dumps(msg), file=self.vs)

  def _send_create_response(self, enabled):
    cfg = {
      "type": "session.update",
      "session": {
        "type": "realtime",
        "audio": {
          "input": {
            "turn_detection": {
              "type": "server_vad",
              "create_response": enabled
            }
          }
        }
      }
    }
    self.ws.send(ujson.dumps(cfg))
    pdeck.led(1, 25 if enabled else 0)

  def toggle_mic_mute(self):
    self.mic_muted = not self.mic_muted
    self.auto_muted = False  # a manual toggle takes ownership of the mute state
    self._send_create_response(not self.mic_muted)
    print("\n%s[Mic %s]%s" % (_el.bold(), "MUTED" if self.mic_muted else "ON", _el.bold_off()), file=self.vs)

  def _auto_mute(self):
    # Mute the mic after the screen has been idle (inactive) long enough. Marks
    # auto_muted so loop() can auto-unmute when the screen becomes active again.
    self.mic_muted = True
    self.auto_muted = True
    self._send_create_response(False)
    print("\n%s[Mic auto-muted (idle)]%s" % (_el.bold(), _el.bold_off()), file=self.vs)

  def _render_menu(self, options, sel, redraw):
    # Draw (or redraw in place) the option list. On redraw we step the cursor
    # back up over the lines drawn last time, then rewrite each one.
    if redraw:
      self.vs.write(_el.cur_up(len(options)))
    for i, item in enumerate(options):
      if i == sel:
        self.vs.write("\r%s%s> %s%s\n" % (
          _el.erase_to_end_of_current_line(), _el.bold(), item[1], _el.bold_off()))
      else:
        self.vs.write("\r%s  %s\n" % (_el.erase_to_end_of_current_line(), item[1]))

  def pause_menu(self):
    # Opened when the user presses B / Backspace. Arrow-key navigable: Up/Down
    # move the selection, Enter confirms, Esc/B resumes. The realtime loop keeps
    # running so audio stays live while the menu is open. Returns 'reset',
    # 'quit', or 'resume'.
    options = (('reset', 'Reset session'), ('quit', 'Quit'))
    sel = 0
    print("\n%s[Menu]%s Up/Down to move, Enter to select, Esc/B to resume" % (
      _el.bold(), _el.bold_off()), file=self.vs)
    self._render_menu(options, sel, False)
    while True:
      self.loop()
      ret = self.vs.v.read_nb_bytes(8)
      if ret and ret[0] > 0:
        k = ret[1]
        # A non-blocking read can occasionally land mid escape-sequence; if we
        # only got a bare ESC (or ESC prefix), let the rest of it arrive.
        if k in (b'\x1b', b'\x1b[', b'\x1bO'):
          time.sleep(0.01)
          r2 = self.vs.v.read_nb_bytes(8)
          if r2 and r2[0] > 0:
            k += r2[1]
        if k in (b'\x1b[A', b'\x1bOA'):       # Up
          sel = (sel - 1) % len(options)
          self._render_menu(options, sel, True)
        elif k in (b'\x1b[B', b'\x1bOB'):     # Down
          sel = (sel + 1) % len(options)
          self._render_menu(options, sel, True)
        elif k in (b'\r', b'\n'):             # Enter: confirm
          return options[sel][0]
        elif k in (b'\x1b', b'\b'):           # Esc / B button: resume
          print("%s[Resumed]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
          return 'resume'
      time.sleep(0.005)

  def reset_session(self):
    # Tear down the realtime connection and open a fresh one, dropping all
    # conversation context. The audio streams keep running, so we only reset
    # the ring buffer and per-turn state. Returns False if reconnect fails.
    print("\n%s[Resetting session...]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
    try:
      self.ws.close()
    except:
      pass
    self._mute_audio(500)
    self.pending_fn_calls = {}
    self.pending_image = None
    self.fn_calls_executed = 0
    self.reset_turn_text()
    gc.collect()
    try:
      self.ws = SimpleWS("api.openai.com", "/v1/realtime?model=%s" % self.model, headers=self.headers)
    except Exception as e:
      print("Failed to reconnect: %s" % e, file=self.vs)
      return False
    self.send_session_update()
    # Force loop() to re-sync the mic create_response flag on the new session.
    self.vs_active = None
    print("%s[Session reset. Ready.]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
    return True

  def loop(self):
    # In agent mode gpt_rt is a background helper that drives other screens, so
    # it keeps listening even when its own screen is not the foreground. Plain
    # voice mode still gates on the active screen.
    active = True if self.agent else self.vs.v.active
    if active != self.vs_active:
      # Screen just became active from inactive: undo an idle auto-mute so the
      # mic is live again. A deliberate (manual) mute is left untouched.
      if active and self.vs_active is not None and self.auto_muted:
        self.mic_muted = False
        self.auto_muted = False
        print("\n%s[Mic auto-unmuted]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
      # Remember when we went inactive so the idle timer below can fire.
      self.inactive_since = None if active else time.ticks_ms()
      self.vs_active = active
      self._send_create_response(active and not self.mic_muted)

    # While inactive, auto-mute the mic once it has been idle long enough.
    # (inactive_since is only set when not active, which never happens in agent
    # mode, so this stays a no-op there.)
    if self.inactive_since is not None and not self.mic_muted:
      if time.ticks_diff(time.ticks_ms(), self.inactive_since) >= self.auto_mute_ms:
        self._auto_mute()

    if self.mic_ready_idx != -1:
      idx = self.mic_ready_idx
      self.mic_ready_idx = -1

      if not self.mic_muted and active:
        if time.ticks_diff(time.ticks_ms(), self.last_play_time) < 400:
          pass
        else:
          mic_data = self.mic_bufs[idx]
          b64 = ubinascii.b2a_base64(mic_data).strip()
          evt = {
            "type": "input_audio_buffer.append",
            "audio": b64.decode()
          }
          self.ws.send(ujson.dumps(evt))

    # Limit audio-delta frames per iteration so the scheduler can run the audio
    # callback between bursts. Control events (barge-in, transcript…) are not
    # counted and drain immediately.
    audio_frames = 0
    while True:
      frame = self.ws.recv()
      if not frame:
        break
      try:
        msg = ujson.loads(frame)
        self.process_event(msg)
        if msg.get("type") == "response.output_audio.delta":
          audio_frames += 1
          # Drain a few audio deltas per iteration so the ring refills quickly,
          # but cap it so the scheduler still runs the audio callback between
          # bursts (the main loop's sleep yields the GIL).
          if audio_frames >= 3:
            break
      except Exception as e:
        print("Message Error:", e, "Frame:", frame[:80], file=self.vs)

    if time.ticks_diff(time.ticks_ms(), self.last_stat_time) > 2000:
      fill = (self._ring_wpos - self._ring_rpos)
      #print("[spk] underruns=%d drops=%d cb_max=%d us fill=%d buf=%s" % (
      #  self.underrun_count, self.drop_count, self.cb_time_max,
      #  fill, "Y" if self.buffering else "N"))
      self.cb_time_max = 0
      self.underrun_count = 0
      self.drop_count = 0
      self.last_stat_time = time.ticks_ms()

    return True

  def terminate(self):
    pdeck.led(1, 0)
    audio.stream_play(False)
    audio.stream_record(False)
    audio.stream_setup(0, 0, 0, 0)
    audio.stream_setup(1, 0, 0, 0)
    self.ws.close()

def main(vs, args_in):
  parser = argparse.ArgumentParser(description='OpenAI Realtime Voice Agent PoC')
  parser.add_argument('-m', '--model', action='store', default='gpt-realtime-2', help='Model to use')
  parser.add_argument('-f', '--file', nargs='+', action='store', help='Attach file(s) as reference')
  parser.add_argument('-a', '--agent', action='store_true', help='Enable agent mode (function calling)')
  parser.add_argument('-l', '--language', action='store', default=None, help='Preferred speech-to-text language, e.g. ja for Japanese')
  args = parser.parse_args(args_in[1:])

  if not auto_connect.check(vs, silent = True):
    print("Network is not available", file=vs)
    return

  model = args.model
  file_list = args.file or []
  agent = args.agent
  language = args.language
  if language == 'ja':
    setuni.main(vs, ['setuni'])

  api_key = gpt.read_api_key()
  if not api_key:
    return

  references = []
  if file_list:
    references = load_references(file_list, vs)
    if len(references) > 0:
      print("Loaded %d reference file(s)." % len(references), file=vs)

  app_list = []
  if agent:
    app_list = load_app_list()
    if app_list:
      print("Agent mode: loaded %d app(s)." % len(app_list), file=vs)

  print("Connecting to OpenAI Realtime API using model %s..." % model, file=vs)
  headers = {
    "Authorization": "Bearer %s" % api_key
  }

  try:
    ws = SimpleWS("api.openai.com", "/v1/realtime?model=%s" % model, headers=headers)
    print("Connected!", file=vs)
  except Exception as e:
    print("Failed to connect: %s" % e, file=vs)
    return

  ra = RealtimeAgent(ws, vs, model, file_list, references, app_list, agent, language, headers)
  print("Starting voice agent%s... Press B for menu (reset/quit), 'q' to quit, Enter to mute/unmute mic." % (" (agent mode)" if agent else ""), file=vs)

  # We don't want gc run for a while
  gc.collect()

  ra.send_session_update()
  ra.start()

  try:
    while True:
      ra.loop()

      ret = vs.v.read_nb(1)
      if ret and ret[0] > 0:
        keys = ret[1].encode('ascii')
        if keys == b'q':
          print("\nExiting...", file=vs)
          break
        elif keys == b'\b':
          choice = ra.pause_menu()
          if choice == 'quit':
            print("\nExiting...", file=vs)
            break
          elif choice == 'reset':
            if not ra.reset_session():
              break
        elif keys == b'\r':
          ra.toggle_mic_mute()

      time.sleep(0.005)
      #pdeck.delay_tick(12)
  finally:
    ra.terminate()
    pdeck.led(2,0)
    pdeck.led(3,0)

