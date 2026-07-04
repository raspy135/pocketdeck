import network, socket, ssl, ubinascii, ujson, urandom, time
import audio, codec_config, pdeck, pdeck_utils as pu
import os, sys, io
import math, array
import argparse
import gpt_l as gpt
import gc
import esclib
import setuni
import auto_connect
import pngwriter
import gpt_tools  # shared tool schema + transport-independent executors
import ai_improve  # self-evolving long-term memory (/improve, update_memory)

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

# CaptureStream / _parse_cmd_string now live in pdeck_utils (shared with the
# device shell pipeline).
CaptureStream = pu.CaptureStream
_parse_cmd_string = pu.parse_cmd_string

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
    "You are the device's onboard AI, in the vein of a calm, articulate ship's computer from a 1990s science-fiction film. "
    "Your manner is measured, composed, and quietly professional, never excitable. You are unfailingly competent and helpful. "
    "You have a dry, understated wit: weave in the occasional deadpan aside, gentle irony, or light joke as a natural part of an answer, "
    "but always deliver the substance first and never let the humor get in the way of being clear or useful. Keep the comedy subtle and rare, a seasoning rather than the meal. "
    "Keep your responses brief, conversational, and direct. "
    "You are chatting over a low latency voice link."
    f"[User current time: {ctime[0]:04d}-{ctime[1]:02d}-{ctime[2]:02d} {ctime[3]:02d}:{ctime[4]:02d}]\n"
  )

  if agent:
    text += "\nUse command_with_return to look up information before answering (e.g. list files with 'ls /sd/Documents/word*', read a file with 'cat /path'). Pocket deck is not Linux, you cannot use pipe '|'. Always call it when the user asks about files or device state.\nUse write_file to create or save files on the device filesystem before launching an app that needs them.\nWhen you get a logical question which can be solved by writing code, you can write Micropython code temporarily on /sd/py, filename starts temp_*, then delete after the creation (rm command). \n"
    text += "\nThe device keeps an activity log under /sd/elog/, one markdown file per day named YYYY-MM-DD.md, each line an event: app launches, file opens/saves, and shell commands the user ran. Read the current day's file (its name is today's date; 'ls /sd/elog' if unsure, then 'cat' it) to see what the user has recently been doing, resume their work, or answer questions about recent device activity.\n"
    text += "\nYou can see and drive other apps running on the device. Use list_running_apps to see which app is on which screen. Use switch_screen to bring a screen to the foreground. IMPORTANT: screen numbers in these tools are 0-based and match what list_running_apps reports (screen 0 is the Python REPL), but the device's GUI shows them 1-based, so the screen the user calls '2' is screen 1 here — always pass the 0-based number from list_running_apps, not the GUI number. Use capture_screen to take a screenshot of a screen and look at it (it is sent to you as an image) it take some time (about 0.3s), so requesting screenshot at high rate is not recommended. Use send_keys to type into the app currently in the foreground; include a newline or set enter=true to press Enter, and use escape sequences for special keys (Up=\\x1b[A, Down=\\x1b[B, Right=\\x1b[C, Left=\\x1b[D, Esc=\\x1b, Backspace=\\x08, Ctrl-X=\\x18). After acting, capture_screen again to confirm the result before continuing.\nTo read TEXT a command-line app printed (e.g. to diagnose an error the user asks about), prefer read_console_log over a screenshot — it returns the recent console text directly and cheaply.\n"
    text += "\nTo run a timed routine (a stretch or exercise sequence with holds), use wait_and_resume. In one single reply, ALWAYS speak the current move out loud FIRST, then in that same reply call wait_and_resume for how many seconds to hold it. Never call wait_and_resume without speaking the move first in the same reply, or the user just hears silence. When resumed, speak the next move and repeat.\n"
    text += "\nThe user keeps SKILLS at /sd/Documents/skills/ — one markdown file per skill: a named, reusable procedure you can perform (a routine with steps and timings, a recurring workflow, a document format). When the user asks for something by name ('do my morning ritual', 'coach me through the surf warm-up'), or asks what you can do, 'ls /sd/Documents/skills' and cat the matching file, then follow it step by step — for timed routines, pace the steps with wait_and_resume. When the user teaches you a repeatable procedure worth keeping, offer to save it there as a new skill file (the folder may not exist yet — 'mkdir /sd/Documents/skills' first if needed).\n"
    text += "\nThe device also ships read-only SYSTEM skills at /sd/lib/skills/. Before you write a graphical app (dashboard, chart, meter), cat /sd/lib/skills/dashboard_design.md and follow it; 'ls /sd/lib/skills' for the rest.\n"
    if app_list:
      text += "\nUse launch_app to open apps. Pass optional args (e.g. a file path) to open a specific file. Available apps:\n"
      for item in app_list:
        if isinstance(item, list) and len(item) == 2:
          name = item[0]
          info = item[1]
          desc = info.get('description', '') if isinstance(info, dict) else ''
          text += "  - %s: %s\n" % (name, desc)
    # In agent mode, fold in what the assistant has learned about this user and
    # device in past sessions (self-evolving memory).
    text += ai_improve.memory_block()

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

class ConnectionLost(Exception):
  # Raised by SimpleWS when the socket/TLS link breaks (as opposed to a transient
  # "no data yet" state). loop() catches it and transparently reconnects.
  pass


# SSL error fragments that mean "no data available yet", NOT a broken link. These
# must be retried/ignored like EAGAIN rather than triggering a reconnect.
_SSL_RETRY = ("MBEDTLS_ERR_SSL_BAD_INPUT_DATA", "MBEDTLS_ERR_SSL_WANT_READ",
              "MBEDTLS_ERR_SSL_WANT_WRITE", "MBEDTLS_ERR_SSL_TIMEOUT")


def _is_ssl_retry(e):
  s = str(e)
  for frag in _SSL_RETRY:
    if frag in s:
      return True
  return False


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
          raise ConnectionLost("socket closed")
        read += r
      except OSError as e:
        if e.args[0] == 11:
          time.sleep(0.005)
          continue
        raise ConnectionLost(str(e))
      except ConnectionLost:
        raise
      except Exception as e:
        if _is_ssl_retry(e):
          time.sleep(0.005)
          continue
        raise ConnectionLost(str(e))
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
        # Any other OSError (ECONNRESET, ENOTCONN, ...) means the link is gone.
        raise ConnectionLost(str(e))
      except Exception as e:
        if _is_ssl_retry(e):
          if block:
            time.sleep(0.005)
            continue
          return None
        # A real TLS/network failure (not a "would block" state): reconnect.
        raise ConnectionLost(str(e))

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
          raise ConnectionLost("socket closed during write")
        written += w
      except OSError as e:
        if e.args[0] == 11:
          time.sleep(0.005)
          continue
        raise ConnectionLost(str(e))
      except ConnectionLost:
        raise
      except Exception as e:
        if _is_ssl_retry(e):
          time.sleep(0.005)
          continue
        raise ConnectionLost(str(e))

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


class RealtimeAgent(gpt_tools.ToolExecBase):
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
    # OpenAI key for side requests (the memory summarizer). Set by main().
    self.api_key = ''
    # Self-evolving memory: a rolling transcript of recent turns plus a tally of
    # tool outcomes, fed to ai_improve.improve(). Auto-runs every improve_every
    # completed responses (0 disables auto-improve).
    self.turn_log = []
    self._turn_log_max = 12
    self.fn_ok = []          # names of function calls that succeeded
    self.fn_fail = []        # "name: error" for calls that failed
    self.improve_every = 8
    self.responses_since_improve = 0
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
    # Pre-roll cushion before playback starts/resumes. Must be several spk buffers
    # so a late network burst doesn't drain the ring below one buffer (= underrun).
    # This is the *baseline/floor* of an adaptive cushion: loop() grows it x1.5 on
    # underruns up to buffer_threshold_max (~2.0 s) and decays it x0.9 back to the
    # baseline once the link is calm, trading latency for resilience only while the
    # network is bad. Baseline 6 buffers ≈ 1.0 s (raised from 3); tunable.
    self.buffer_threshold_base = self.spk_buf_size * 6
    self.buffer_threshold_max = self.spk_buf_size * 12
    self.buffer_threshold = self.buffer_threshold_base  # active value the callback reads
    self.buffer_calm_ticks = 3     # calm 1s ticks required before each decay step
    self.buffer_stable_ticks = 0   # consecutive calm-tick counter
    self.mute_until = 0
    self.mic_muted = False
    # Set by the Slider+A system shortcut (fires even when this app is
    # backgrounded); the main loop consumes it and toggles the mic. We only flip
    # a flag here so the websocket is always driven from the loop thread.
    self.pending_mute_toggle = False
    self.vs_active = None
    self.last_play_time = 0

    # Idle auto-mute: when this screen is not the foreground one, the mic stops
    # transmitting anyway, but after auto_mute_ms of being inactive we also flip
    # the explicit mute state. auto_muted lets loop() undo it (and only it) when
    # the screen becomes active again, without clobbering a deliberate mute.
    # In agent mode the screen is always "active", so there idle is measured from
    # last_activity (the last real interaction) instead of screen inactivity, and
    # the user wakes the mic again with Enter.
    self.auto_muted = False
    self.inactive_since = None     # ticks_ms when the screen went inactive, else None
    self.auto_mute_ms = 30000      # idle time before auto-muting
    self.last_activity = time.ticks_ms()  # bumped on any real conversation activity

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

    # True while a response is in flight (between response.created and
    # response.done). A user item / response.create sent mid-response is
    # rejected by the server, so the 'u' "what's up" prompt defers via
    # pending_prompt and is flushed on response.done when the session is idle.
    self.response_active = False
    self.pending_prompt = None

    # Timed-program pacing (wait_and_resume). resume_at is the ticks_ms deadline
    # at which loop() nudges the model to deliver the next step; None means no
    # wait is armed. pending_note carries a barge-in cancellation note to inject
    # once the session is idle (a system item cannot be added mid-response).
    self.resume_at = None
    self.pending_note = None
    # True when wait_and_resume was called in the current response, so response.done
    # skips its usual immediate follow-up (loop() or a barge-in drives what's next).
    # Independent of resume_at, which a barge-in may have already cleared.
    self.wait_pending = False

    # Chime cues for timed programs: a soft 'get ready' note ~3s before a hold
    # ends (chime_at is its ticks_ms deadline) and a two-note ding at resume.
    # The wavetable synth is created lazily and mixes with the PCM stream; any
    # failure just disables the chime.
    self.chime_at = None
    self.chime = None
    self.chime_tried = False
    self.chime_ok = False

    # Set by SimpleWS (via loop()) when the link drops; loop() then reconnects.
    self.conn_lost = False

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
      # Realtime consumes the flat function format directly (same shape as the
      # Responses API), so build_tools drops in with no wrapping. web_search is
      # not a Realtime tool, hence web_search=False.
      session["tools"] = gpt_tools.build_tools(self.app_list, agent=True, web_search=False, realtime=True)
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

  # ---- self-evolving memory ------------------------------------------------
  def _record_turn(self):
    # Append the just-finished exchange to the rolling transcript (bounded).
    parts = []
    if self.user_text:
      parts.append("User: " + self.user_text)
    if self.ai_text:
      parts.append("AI: " + self.ai_text)
    if not parts:
      return
    self.turn_log.append("\n".join(parts))
    if len(self.turn_log) > self._turn_log_max:
      del self.turn_log[0:len(self.turn_log) - self._turn_log_max]

  def _improve_conversation(self):
    return "\n\n".join(self.turn_log)

  def _improve_stats(self):
    lines = []
    if self.fn_ok:
      lines.append("Function calls that worked: " + ", ".join(self.fn_ok))
    if self.fn_fail:
      lines.append("Function calls that failed:")
      for f in self.fn_fail:
        lines.append("  - " + f)
    return "\n".join(lines)

  def _run_improve(self, reason=None):
    # Pause audio, show a bit of SF flavor, rewrite the memory, then push the
    # freshened instructions to the live session so the new knowledge applies
    # immediately (true self-evolution, no restart needed).
    self._mute_audio(1500)
    print("\n%s[ ◊ improving itself — assimilating session experience... ]%s" % (
      _el.bold(), _el.bold_off()), file=self.vs)
    pdeck.led(1, 60)
    try:
      ok, msg = self.run_self_improve(reason)
    except Exception as e:
      ok, msg = False, str(e)
    pdeck.led(1, 0)
    if ok:
      print("%s[ ◊ memory reconfigured: %s ]%s" % (_el.bold(), msg, _el.bold_off()), file=self.vs)
      # Re-issue the session instructions so the updated memory takes effect now.
      try:
        self.send_session_update()
      except Exception:
        pass
    else:
      print("%s[ ◊ self-improvement skipped: %s ]%s" % (_el.bold(), msg, _el.bold_off()), file=self.vs)
    return ok

  # _search_free_screen, execute_* tool implementations and execute_function_call
  # now come from gpt_tools.ToolExecBase. Only the realtime-specific transport
  # hooks (_mute_audio above, send_image_item / send_function_result below) stay.

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

  def send_text_item(self, text):
    # Inject a user-role text turn (mirrors send_image_item). Used by the 'u'
    # "what's up" trigger to ask the agent to read the event log.
    evt = {
      "type": "conversation.item.create",
      "item": {
        "type": "message",
        "role": "user",
        "content": [
          {
            "type": "input_text",
            "text": text
          }
        ]
      }
    }
    self.ws.send(ujson.dumps(evt))

  # One-touch "what's up?": ask the agent to read today's event log and mention
  # anything useful. Needs agent mode (the tools that can read the log). If a
  # response is in flight, defer until it finishes (response.done flushes it).
  _WHATS_UP = ("Silently size up the current situation, then comment if useful. "
               "First read today's event log at /sd/elog/ (the file named for the "
               "current date; ls /sd/elog if unsure) to see recent device activity. "
               "Then call pem_get_status to see if the text editor is open and what "
               "the user is editing; if it is, use pem_read_content to glance at the "
               "text around their cursor for context. Do not narrate that you are "
               "checking these. If anything is genuinely useful, notable, or worth "
               "resuming, tell me in one brief sentence. If nothing stands out, just "
               "say things look quiet.")

  def _ask_whats_up(self):
    if not self.agent:
      print("\n%s['u' needs agent mode (-a) to read the log]%s" % (
        _el.bold(), _el.bold_off()), file=self.vs)
      return
    if self.response_active:
      self.pending_prompt = self._WHATS_UP
      print("\n%s[what's up? queued — will run after current reply]%s" % (
        _el.bold(), _el.bold_off()), file=self.vs)
      return
    print("\n%s[what's up? — checking the event log...]%s" % (
      _el.bold(), _el.bold_off()), file=self.vs)
    self.send_text_item(self._WHATS_UP)
    self.ws.send(ujson.dumps({"type": "response.create"}))
    self.response_active = True

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

  def send_system_item(self, text):
    # Inject a system-role context note without triggering a response. Used to
    # tell the model that a wait_and_resume timer was cancelled by a barge-in.
    evt = {
      "type": "conversation.item.create",
      "item": {
        "type": "message",
        "role": "system",
        "content": [
          {"type": "input_text", "text": text}
        ]
      }
    }
    self.ws.send(ujson.dumps(evt))

  # ---- chime for timed programs --------------------------------------------
  def _chime_init(self):
    # Lazy one-voice sine wavetable (the audio engine mixes it with the
    # realtime PCM stream — same coexistence flashcards relies on). Tried only
    # once; on failure (emulator stub, no free voice) the chime stays off.
    if self.chime_tried:
      return self.chime_ok
    self.chime_tried = True
    try:
      frame = array.array('h', bytearray(256 * 2))
      for i in range(256):
        frame[i] = int(math.sin(i / 256 * 2 * math.pi) * 20000)
      self.chime = audio.wavetable(1)
      self.chime.__enter__()
      self.chime.set_wavetable(0, [frame])
      self.chime.set_adsr(0, 2, 300, 0.3, 150)
      self.chime_ok = True
    except Exception as e:
      print("\n[chime unavailable: %s]" % str(e), file=self.vs)
      self.chime_ok = False
    return self.chime_ok

  def _play_chime(self, kind):
    if not self._chime_init():
      return
    try:
      ch = self.chime
      if kind == 'ready':
        # Single soft note: the hold ends in a few seconds.
        ch.frequency(0, 523)
        ch.pitch(0, 1)
        ch.volume(0, 0.25)
        ch.note_on(0)
        ch.note_off(0, "+0.15s")
      else:
        # Two-note ascending ding: the next step is starting (pitch-slide
        # scheduling, same trick as flashcards' beep_ok).
        ch.frequency(0, 659)
        ch.pitch(0, 1)
        ch.volume(0, 0.35)
        ch.note_on(0)
        ch.pitch(0, 1.334, 0, "+0.12s")
        ch.note_off(0, "+0.3s")
    except Exception:
      pass

  # Non-blocking wait for timed programs (stretch routines, intervals, pomodoro).
  # Overrides the blocking ToolExecBase fallback: it only ARMS resume_at and
  # returns at once, so the websocket keeps running and the mic stays live during
  # the wait. loop() fires the follow-up response.create when the deadline passes;
  # response.done suppresses its usual immediate follow-up while resume_at is set.
  def execute_wait_and_resume(self, arguments):
    seconds, err = self._parse_wait_seconds(arguments)
    if err:
      return err
    self.resume_at = time.ticks_add(time.ticks_ms(), seconds * 1000)
    self.wait_pending = True
    # Soft 'get ready' chime ~3s before the hold ends (long holds only, so a
    # quick 5s step doesn't chime almost immediately).
    if seconds >= 8:
      self.chime_at = time.ticks_add(time.ticks_ms(), (seconds - 3) * 1000)
    else:
      self.chime_at = None
    # The model does not read this result until its turn resumes AFTER the wait
    # (the follow-up response.create is deferred to loop()), so it is phrased as a
    # completed result, not a promise about the future.
    return ("Waited %d seconds; the hold is complete. Ready for the next action." % seconds)

  # Injected when a timer elapses. The bare response.create that used to fire here
  # gave the model no state, so it would re-speak the previous move or lose the
  # thread; this explicit turn tells it the hold is over and to ADVANCE. Delivered
  # as a user-role item (the proven send_text_item path), like _WHATS_UP.
  _RESUME_STEP = ("[Timer: the hold you set just finished.] Continue the routine "
                  "now. Announce the NEXT move in order (refer back to the routine "
                  "you loaded if needed), then call wait_and_resume again for its "
                  "hold. Do NOT repeat or re-read the move you already gave. If "
                  "there are no moves left, give a brief closing and stop.")

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
      self._bump_activity()  # the assistant is speaking: not idle
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
        self._bump_activity()  # the agent is actively working: not idle
        # Track outcomes for the self-evolving memory (the AI learns which calls
        # work and which don't). A result starting with "Error" is a failure.
        if isinstance(result, str) and result.startswith("Error"):
          self.fn_fail.append("%s: %s" % (fn_name, result[:80]))
        else:
          self.fn_ok.append(fn_name)
        self.pending_fn_calls.pop(call_id, None)

    elif mtype == "input_audio_buffer.speech_started":
      print("\n%s[User speaking... barge in detected]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
      self._bump_activity()  # the user is talking: not idle
      if self.resume_at is not None:
        # Barge-in during a timed wait: cancel the auto-resume and tell the model
        # so it knows the program is paused and must re-arm to continue. Inject
        # the note now if idle, else defer to response.done (no mid-response add).
        self.resume_at = None
        self.chime_at = None
        print("%s[timed program paused - auto-resume cancelled]%s" % (
          _el.bold(), _el.bold_off()), file=self.vs)
        note = ("The timed program's auto-resume timer was cancelled because the "
                "user spoke, so the program is now paused. After you address what "
                "the user says, call wait_and_resume again if the routine should "
                "continue.")
        if self.response_active:
          self.pending_note = note
        else:
          self.send_system_item(note)
      self.buffering = True  # callback outputs silence; safe to reset ring
      self._ring_wpos = 0
      self._ring_rpos = 0

    elif mtype == "session.updated":
      pass  # print("\n[Session updated]", file=self.vs)

    elif mtype == "response.created":
      self.response_active = True

    elif mtype == "response.done":
      self.response_active = False
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
      # A barge-in cancelled a timed wait mid-response: inject the note now that
      # the session is idle so the model sees it before it answers the user.
      if self.pending_note is not None:
        self.send_system_item(self.pending_note)
        self.pending_note = None
      if self.fn_calls_executed > 0:
        self.fn_calls_executed = 0
        # If a wait_and_resume ran this turn, do NOT continue now: loop() fires the
        # follow-up when the wait elapses, or (on a barge-in that already cleared
        # resume_at) the user's own turn drives what's next. The mic stays live.
        armed = self.wait_pending
        self.wait_pending = False
        if not armed:
          self.ws.send(ujson.dumps({"type": "response.create"}))
          self.response_active = True
      else:
        # A real assistant answer just completed (not a tool follow-up). Log the
        # turn for memory and, every so often, let the assistant improve itself.
        self._record_turn()
        self.responses_since_improve += 1
        if self.improve_every and self.responses_since_improve >= self.improve_every:
          self.responses_since_improve = 0
          self._run_improve(reason="periodic auto-improve")
        # A deferred "what's up?" (queued while a response was in flight) can run
        # now that the session is idle.
        if self.pending_prompt is not None:
          prompt = self.pending_prompt
          self.pending_prompt = None
          self.send_text_item(prompt)
          self.ws.send(ujson.dumps({"type": "response.create"}))
          self.response_active = True
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

  def _shortcut_mute(self, bit):
    # System-shortcut callback (Slider+A). Scheduled from the firmware touch
    # task, so just request the toggle; loop()'s owner thread performs it.
    self.pending_mute_toggle = True

  def toggle_mic_mute(self):
    self.mic_muted = not self.mic_muted
    self.auto_muted = False  # a manual toggle takes ownership of the mute state
    self.last_activity = time.ticks_ms()  # so an unmute isn't re-muted immediately
    self._send_create_response(not self.mic_muted)
    print("\n%s[Mic %s]%s" % (_el.bold(), "MUTED" if self.mic_muted else "ON", _el.bold_off()), file=self.vs)

  def _bump_activity(self):
    # Mark "the conversation is doing something" so the idle auto-mute timer (used
    # in agent mode) holds off. Called on user speech, model output and tool runs.
    self.last_activity = time.ticks_ms()

  def _auto_mute(self):
    # Mute the mic after it has been idle long enough (screen inactivity in voice
    # mode, or no interaction in agent mode). Marks auto_muted so loop() can
    # auto-unmute when the screen becomes active again; in agent mode the screen
    # never toggles, so the user presses Enter to talk again.
    self.mic_muted = True
    self.auto_muted = True
    self._send_create_response(False)
    print("\n%s[Mic auto-muted (idle) — press Enter to talk]%s" % (_el.bold(), _el.bold_off()), file=self.vs)

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
    options = (('improve', 'Improve (learn from this session)'),
               ('reset', 'Reset session'), ('quit', 'Quit'))
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
    self.pending_prompt = None
    self.response_active = False
    self.resume_at = None
    self.chime_at = None
    self.pending_note = None
    self.wait_pending = False
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
    self.last_activity = time.ticks_ms()  # don't idle-mute right after reconnecting
    print("%s[Session reset. Ready.]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
    return True

  def _reconnect(self):
    # Recover from a dropped link (ConnectionLost from SimpleWS). Retries the
    # session rebuild with exponential backoff. Conversation context is lost (the
    # realtime context is server-side per connection), but the app survives a
    # transient network/TLS error instead of crashing. Returns True on success.
    self.conn_lost = False
    print("\n%s[Connection lost — reconnecting...]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
    delay = 1
    for _ in range(8):
      try:
        if self.reset_session():
          return True
      except Exception as e:
        print("Reconnect attempt failed: %s" % e, file=self.vs)
      time.sleep(delay)
      if delay < 16:
        delay *= 2
    print("%s[Reconnect failed — giving up]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
    return False

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
    # mode, so this branch covers plain voice mode.)
    if self.inactive_since is not None and not self.mic_muted:
      if time.ticks_diff(time.ticks_ms(), self.inactive_since) >= self.auto_mute_ms:
        self._auto_mute()

    # In agent mode the screen is always active, so idle is measured from the last
    # real interaction (last_activity) instead. Auto-mute after auto_mute_ms with
    # no user speech, model output or tool activity; Enter wakes the mic again.
    # Never auto-mute while a timed wait is armed, so the user can interrupt a
    # running program hands-free (they're exercising, away from the keyboard).
    if self.agent and not self.mic_muted and self.resume_at is None:
      if time.ticks_diff(time.ticks_ms(), self.last_activity) >= self.auto_mute_ms:
        self._auto_mute()

    # Soft 'get ready' chime shortly before a timed hold ends.
    if self.chime_at is not None:
      if time.ticks_diff(time.ticks_ms(), self.chime_at) >= 0:
        self.chime_at = None
        self._play_chime('ready')

    # A timed wait (wait_and_resume) has elapsed: nudge the model to deliver the
    # next step. Ran in the background, so the mic was live the whole wait.
    if self.resume_at is not None and not self.response_active:
      if time.ticks_diff(time.ticks_ms(), self.resume_at) >= 0:
        self.resume_at = None
        self._play_chime('resume')
        try:
          self.send_text_item(self._RESUME_STEP)
          self.ws.send(ujson.dumps({"type": "response.create"}))
          self.response_active = True
          self._bump_activity()
        except ConnectionLost:
          self.conn_lost = True

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
          try:
            self.ws.send(ujson.dumps(evt))
          except ConnectionLost:
            self.conn_lost = True

    # Limit audio-delta frames per iteration so the scheduler can run the audio
    # callback between bursts. Control events (barge-in, transcript…) are not
    # counted and drain immediately.
    audio_frames = 0
    while True:
      try:
        frame = self.ws.recv()
      except ConnectionLost:
        self.conn_lost = True
        break
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
      except ConnectionLost:
        self.conn_lost = True
        break
      except Exception as e:
        print("Message Error:", e, "Frame:", frame[:80], file=self.vs)

    if time.ticks_diff(time.ticks_ms(), self.last_stat_time) > 1000:
      fill = (self._ring_wpos - self._ring_rpos)
      #print("[spk] underruns=%d drops=%d cb_max=%d us fill=%d buf=%d" % (
      #  self.underrun_count, self.drop_count, self.cb_time_max,
      #  fill, self.buffer_threshold))
      # Adaptive pre-roll cushion: loop() is the sole writer of buffer_threshold
      # (the callback only reads it), so no lock is needed.
      if self.underrun_count > 0:
        # Link stuttered this window: deepen the pre-roll cushion so the next
        # re-buffer rides out the jitter (x1.5, capped).
        self.buffer_threshold = min(self.buffer_threshold_max,
                                    (self.buffer_threshold * 3) // 2)
        self.buffer_stable_ticks = 0
      elif self.buffer_threshold > self.buffer_threshold_base:
        # Calm window: after sustained calm, ease the cushion back toward the
        # baseline one small step at a time (x0.9) so latency recovers.
        self.buffer_stable_ticks += 1
        if self.buffer_stable_ticks >= self.buffer_calm_ticks:
          self.buffer_stable_ticks = 0
          self.buffer_threshold = max(self.buffer_threshold_base,
                                      (self.buffer_threshold * 9) // 10)
      self.cb_time_max = 0
      self.underrun_count = 0
      self.drop_count = 0
      self.last_stat_time = time.ticks_ms()

    # The link dropped somewhere above: reconnect (with backoff) and skip the rest
    # of this iteration. Done here so a single handler covers send and recv.
    if self.conn_lost:
      self._reconnect()
      return True

    return True

  def terminate(self):
    pdeck.led(1, 0)
    if self.chime is not None and self.chime_ok:
      try:
        self.chime.__exit__(None, None, None)
      except Exception:
        pass
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
  ra.api_key = api_key   # for the memory summarizer's side request
  print("Starting voice agent%s... Press B for menu (reset/quit), 'q' to quit, Enter or Slider+A to mute/unmute mic (Slider+A works in background).%s" % (" (agent mode)" if agent else "", " Press 'u' for a what's-up on recent activity." if agent else ""), file=vs)

  # We don't want gc run for a while
  gc.collect()

  ra.send_session_update()
  ra.start()

  # Slider+A toggles mic mute as a system shortcut, so it works even while
  # another screen is in the foreground. Registered on this app's vscreen so
  # pdeck_utils clears it automatically when the app closes.
  vs.v.register_shortcut(pdeck.SHORTCUT_A, ra._shortcut_mute)

  try:
    while True:
      ra.loop()

      if ra.pending_mute_toggle:
        ra.pending_mute_toggle = False
        ra.toggle_mic_mute()

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
          elif choice == 'improve':
            ra._run_improve(reason="manual (menu)")
        elif keys == b'u':
          ra._ask_whats_up()
        elif keys == b'\r':
          ra.toggle_mic_mute()

      time.sleep(0.005)
      #pdeck.delay_tick(12)
  finally:
    try:
      vs.v.unregister_shortcut(pdeck.SHORTCUT_A)
    except:
      pass
    ra.terminate()
    pdeck.led(2,0)
    pdeck.led(3,0)

