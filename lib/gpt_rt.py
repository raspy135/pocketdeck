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
    text += "\nUse command_with_return to look up information before answering (e.g. list files with 'ls /sd/Documents/word*', read a file with 'cat /path'). Pocket deck is not Linux: no redirects ('>'), no '&&' or ';', no subshells; simple pipes '|' work but only INTO grep/head/tail. Always call it when the user asks about files or device state.\nUse write_file to create or save files on the device filesystem before launching an app that needs them.\nWhen you get a logical question which can be solved by writing code, you can write Micropython code temporarily on /sd/py, filename starts temp_*, then delete after the creation (rm command). \n"
    text += "\nThe device keeps an activity log under /sd/elog/, one markdown file per day named YYYY-MM-DD.md, each line an event: app launches, file opens/saves, and shell commands the user ran. Read the current day's file (its name is today's date; 'ls /sd/elog' if unsure, then 'cat' it) to see what the user has recently been doing, resume their work, or answer questions about recent device activity.\n"
    text += "\nYou can see and drive other apps running on the device. Use list_running_apps to see which app is on which screen. Use switch_screen to bring a screen to the foreground. IMPORTANT: screen numbers in these tools are 0-based and match what list_running_apps reports (screen 0 is the Python REPL), but the device's GUI shows them 1-based, so the screen the user calls '2' is screen 1 here — always pass the 0-based number from list_running_apps, not the GUI number. Use capture_screen to take a screenshot of a screen and look at it (it is sent to you as an image) it take some time (about 0.3s), so requesting screenshot at high rate is not recommended. Use send_keys to type into the app currently in the foreground; include a newline or set enter=true to press Enter, and use escape sequences for special keys (Up=\\x1b[A, Down=\\x1b[B, Right=\\x1b[C, Left=\\x1b[D, Esc=\\x1b, Backspace=\\x08, Ctrl-X=\\x18). After acting, capture_screen again to confirm the result before continuing.\nTo read TEXT a command-line app printed (e.g. to diagnose an error the user asks about), prefer read_console_log over a screenshot — it returns the recent console text directly and cheaply.\n"
    text += "\nTo run a timed routine (a stretch or exercise sequence with holds), use wait_and_resume. In one single reply, ALWAYS speak the current move out loud FIRST, then in that same reply call wait_and_resume for how many seconds to hold it. Never call wait_and_resume without speaking the move first in the same reply, or the user just hears silence. When resumed, speak the next move and repeat.\n"
    text += "\nThe user keeps SKILLS at /sd/Documents/skills/ — one markdown file per skill: a named, reusable procedure you can perform (a routine with steps and timings, a recurring workflow, a document format). When the user asks for something by name ('do my morning ritual', 'coach me through the surf warm-up'), or asks what you can do, 'ls /sd/Documents/skills' and cat the matching file, then follow it step by step — for timed routines, pace the steps with wait_and_resume. When the user teaches you a repeatable procedure worth keeping, offer to save it there as a new skill file (the folder may not exist yet — 'mkdir /sd/Documents/skills' first if needed).\n"
    text += "\nThe device also ships read-only SYSTEM skills at /sd/lib/skills/. Before you write a graphical app (dashboard, chart, meter), cat /sd/lib/skills/dashboard_design.md and follow it; 'ls /sd/lib/skills' for the rest.\n"
    if app_list:
      text += "\nUse launch_app to open apps. Pass optional args (e.g. a file path) to open a specific file. Besides the registered apps listed below, any installed module can be launched by its module name (e.g. 'myapp' for /sd/lib/myapp.py). Available apps:\n"
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


# Base64 helpers that read/write caller-provided buffers. ubinascii allocates a
# fresh object per call, and the audio loop runs many times per second in both
# directions — that garbage was the main driver of the periodic gc pauses
# (audible as glitches). These keep the steady-state audio path allocation-free.
_B64_ALPHA = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
_B64_DEC = bytearray(256)
for _i in range(256):
  _B64_DEC[_i] = 255
for _i in range(64):
  _B64_DEC[_B64_ALPHA[_i]] = _i
_B64_DEC = bytes(_B64_DEC)


@micropython.viper
def _b64_encode(dst: ptr8, dst_off: int, src: ptr8, n: int) -> int:
  # Encode n bytes of src as base64 into dst[dst_off:], '='-padded like
  # ubinascii.b2a_base64 (minus the trailing newline). Returns chars written.
  t = ptr8(_B64_ALPHA)
  o = dst_off
  i = 0
  while i + 2 < n:
    b0 = src[i]
    b1 = src[i + 1]
    b2 = src[i + 2]
    dst[o] = t[b0 >> 2]
    dst[o + 1] = t[((b0 & 3) << 4) | (b1 >> 4)]
    dst[o + 2] = t[((b1 & 15) << 2) | (b2 >> 6)]
    dst[o + 3] = t[b2 & 63]
    i += 3
    o += 4
  rem = n - i
  if rem == 1:
    b0 = src[i]
    dst[o] = t[b0 >> 2]
    dst[o + 1] = t[(b0 & 3) << 4]
    dst[o + 2] = 61  # '='
    dst[o + 3] = 61
    o += 4
  elif rem == 2:
    b0 = src[i]
    b1 = src[i + 1]
    dst[o] = t[b0 >> 2]
    dst[o + 1] = t[((b0 & 3) << 4) | (b1 >> 4)]
    dst[o + 2] = t[(b1 & 15) << 2]
    dst[o + 3] = 61
    o += 4
  return o - dst_off


@micropython.viper
def _b64_decode(dst: ptr8, src: ptr8, src_off: int, n: int) -> int:
  # Decode n base64 chars from src[src_off:] into dst. Stops at '=' padding,
  # skips whitespace/invalid chars. Returns bytes written.
  t = ptr8(_B64_DEC)
  o = 0
  i = src_off
  end = src_off + n
  acc = 0
  bits = 0
  while i < end:
    c = src[i]
    i += 1
    if c == 61:  # '='
      break
    v = t[c]
    if v == 255:
      continue
    acc = (acc << 6) | v
    bits += 6
    if bits >= 8:
      bits -= 8
      dst[o] = (acc >> bits) & 0xff
      o += 1
  return o


@micropython.viper
def _mem_find(hay: ptr8, start: int, end: int, needle: ptr8, nlen: int) -> int:
  # First index of needle in hay[start:end], or -1. bytearray/memoryview have
  # no .find() in MicroPython, and this avoids materializing bytes() copies.
  if nlen <= 0:
    return start
  last = end - nlen
  i = start
  c0 = needle[0]
  while i <= last:
    if hay[i] == c0:
      j = 1
      while j < nlen:
        if hay[i + j] != needle[j]:
          break
        j += 1
      if j == nlen:
        return i
    i += 1
  return -1


# Prefer the C implementations in dsplib (same signatures, caller-provided
# buffers, allocation-free and faster than viper). The viper versions above
# stay as the fallback for firmware without them.
#
# IMPORTANT: keep the viper function objects referenced (_vp aliases) even when
# dsplib wins. Dropping the last reference to a FROZEN viper function lets gc
# collect it, and its finalizer then calls esp_native_code_free on flash-
# resident code — which corrupted the heap (StoreProhibited in gc) on firmware
# before the guard added to esp_native_code_free on 2026-07-15.
_b64_encode_vp = _b64_encode
_b64_decode_vp = _b64_decode
try:
  import dsplib
  _b64_encode = dsplib.b64_encode
  _b64_decode = dsplib.b64_decode
except (ImportError, AttributeError):
  pass

# Byte-level markers for the audio-delta fast path (see _try_audio_delta).
_DELTA_TYPE = b'"type":"response.output_audio.delta"'
_DELTA_B64_KEY = b'"delta":"'
_QUOTE = b'"'

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
    # Preallocated receive/send scratch. The realtime session receives several
    # audio-delta frames per second; allocating a header + payload bytearray
    # per frame was a large share of the garbage that drove periodic gc pauses
    # (audible glitches). Frames are assembled into the shared _rx buffer and
    # recv() hands out a memoryview into it (valid until the next recv call).
    self._hdr = bytearray(2)
    self._hdr_mv = memoryview(self._hdr)
    self._ext = bytearray(8)
    self._ext_mv = memoryview(self._ext)
    self._mask4 = bytearray(4)       # incoming frame mask (recv path)
    self._send_mask = bytearray(4)   # outgoing frame mask (send path)
    self._rx_size = 65536
    self._rx = bytearray(self._rx_size)
    self._rx_mv = memoryview(self._rx)
    self._send_hdr = bytearray(4)
    self.rx_grow = 0  # debug: count of _rx_ensure growths (big allocations)

  def _recv_exact_into(self, view):
    n = len(view)
    read = 0
    while read < n:
      try:
        r = self.sock.readinto(view[read:] if read else view)
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

  def _rx_ensure(self, need):
    # Grow the shared receive buffer (rare: only frames/messages over 64 KB,
    # e.g. a huge response.done). Preserves already-assembled fragment bytes.
    if need <= self._rx_size:
      return
    size = (need + 0xffff) & ~0xffff
    self.rx_grow += 1
    print("[dbg] ws rx buffer grew to %d (big frame/message)" % size)
    nb = bytearray(size)
    nb[:self._rx_size] = self._rx
    self._rx = nb
    self._rx_mv = memoryview(nb)
    self._rx_size = size

  def _recv_frame(self, block=False, off=0):
    # Reads a single WebSocket frame; the payload is written into self._rx at
    # offset off. Returns (fin, opcode, length), or None when no data is
    # available yet (only when block=False). When block is True we are
    # mid-message (waiting for continuation frames) and must wait for the next
    # frame rather than abandoning the partial message.
    while True:
      try:
        r = self.sock.readinto(self._hdr_mv)
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

      if not r:
        if block:
          time.sleep(0.005)
          continue
        return None
      break

    if r < 2:
      # Got a partial header; the rest is guaranteed to follow.
      self._recv_exact_into(self._hdr_mv[1:])

    b1, b2 = self._hdr[0], self._hdr[1]
    fin = b1 & 0x80
    opcode = b1 & 0x0f

    has_mask = b2 & 0x80
    length = b2 & 0x7f

    if length == 126:
      self._recv_exact_into(self._ext_mv[:2])
      length = (self._ext[0] << 8) | self._ext[1]
    elif length == 127:
      self._recv_exact_into(self._ext_mv)
      length = 0
      for i in range(8):
        length = (length << 8) | self._ext[i]

    if has_mask:
      self._recv_exact_into(memoryview(self._mask4))

    if length:
      self._rx_ensure(off + length)
      self._recv_exact_into(self._rx_mv[off:off + length])
      if has_mask:
        m = self._mask4
        buf = self._rx
        for i in range(length):
          buf[off + i] ^= m[i & 3]

    return fin, opcode, length

  def recv(self):
    # Reassembles fragmented messages: a logical message may span a leading
    # data frame (opcode 1/2, FIN=0) plus continuation frames (opcode 0) until
    # FIN is set. Control frames (ping/pong/close) may be interleaved between
    # fragments and are handled without disturbing the message being assembled.
    # Returns a memoryview into the shared receive buffer — valid only until
    # the next recv() call — or None when no complete message is ready.
    total = -1  # -1 = no message started yet
    while True:
      off = total if total > 0 else 0
      frame = self._recv_frame(block=total >= 0, off=off)
      if frame is None:
        return None
      fin, opcode, length = frame

      if opcode == 8:        # close
        self.sock.close()
        return None
      if opcode == 9:        # ping (payload sits at off; copy before replying)
        self.send(bytes(self._rx_mv[off:off + length]), opcode=10)
        continue
      if opcode == 10:       # pong
        continue

      if opcode == 0:        # continuation
        if total < 0:
          continue           # stray continuation; ignore
        total += length
      else:                  # 1 = text, 2 = binary: start of a message
        total = length

      if fin:
        return self._rx_mv[:total]

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
    # Accepts str, bytes, or any buffer (the mic path sends a memoryview of a
    # preallocated frame). Header and mask use preallocated scratch so the
    # per-send garbage is zero for buffer inputs.
    if isinstance(data, str):
      data = data.encode()
    length = len(data)

    hdr = self._send_hdr
    hdr[0] = 0x80 | opcode
    mask = self._send_mask
    mask[0] = urandom.getrandbits(8)
    mask[1] = urandom.getrandbits(8)
    mask[2] = urandom.getrandbits(8)
    mask[3] = urandom.getrandbits(8)

    if length < 126:
      hdr[1] = 0x80 | length
      self._send_exact(memoryview(hdr)[:2])
    elif length < 65536:
      hdr[1] = 0x80 | 126
      hdr[2] = (length >> 8) & 0xff
      hdr[3] = length & 0xff
      self._send_exact(memoryview(hdr))
    else:
      hdr[1] = 0x80 | 127
      self._send_exact(memoryview(hdr)[:2])
      ext = bytearray(8)
      for i in range(8):
        ext[7-i] = (length >> (i*8)) & 0xff
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
  def __init__(self, ws, vs, model, file_list, references, app_list=None, agent=False, language=None, headers=None, rt=None):
    self.ws = ws
    self.vs = vs
    self.model = model
    self.headers = headers or {}
    # Realtime backend (host/path/voice/provider) so the session config and any
    # reconnect target the right provider. Defaults keep OpenAI behavior.
    rt = rt or {}
    self.rt_host = rt.get("host", "api.openai.com")
    self.rt_path = rt.get("path", "/v1/realtime")
    self.rt_port = rt.get("port", 443)
    self.voice = rt.get("voice", "marin")
    self.provider = rt.get("provider", "openai")
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

    # Preallocated outgoing mic frame: JSON envelope + base64 payload, rebuilt
    # in place each tick (~5/s). The old path (b2a_base64 + strip + decode +
    # ujson.dumps + encode) allocated ~65 KB of garbage per tick and was a main
    # driver of the periodic gc pauses that glitch the audio.
    self._mic_prefix = b'{"type":"input_audio_buffer.append","audio":"'
    _b64_len = ((self.mic_buf_size + 2) // 3) * 4
    self._mic_frame = bytearray(len(self._mic_prefix) + _b64_len + 2)
    self._mic_frame[:len(self._mic_prefix)] = self._mic_prefix
    self._mic_frame_mv = memoryview(self._mic_frame)

    # Preallocated PCM scratch for the incoming audio-delta fast path: base64
    # is decoded straight from the websocket receive buffer into here, then
    # copied into the playback ring. Sized for the largest delta a 64 KB frame
    # can carry; larger (grown-buffer) frames fall back to the json path.
    self._pcm_buf = bytearray(49152)
    self._pcm_mv = memoryview(self._pcm_buf)

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

    # --- glitch-hunt debug instrumentation ----------------------------------
    # Per-second "[dbg]" stat line on the REPL (plain print, not the app
    # screen). With debug=True (-d) it prints every second audio is flowing;
    # otherwise only on anomaly windows (underrun / drop / late callback /
    # rx-buffer growth), so glitches leave a trace even without -d.
    #
    # The two glitch modes it separates:
    #  - ring underrun: ring drained -> silence + "underrun" print (ur=).
    #  - LATE CALLBACK: spk_callback not serviced in time (GIL held by a long
    #    ujson.loads or a gc pass) -> the I2S DMA replays stale buffer data,
    #    heard as REPEATED audio with NO underrun print. cbgap= catches this:
    #    the callback should fire every ~166 ms (8000 B / 2 / 24 kHz).
    self.debug = False
    self.cb_gap_max = 0       # max ms between speaker callbacks this window
    self._cb_last = 0
    self.fill_min = -1        # lowest ring fill seen while playing (not buffering)
    self.delta_fast = 0       # audio deltas via the zero-alloc fast path
    self.delta_slow = 0       # audio deltas via ujson.loads (dict-form: e.g. xAI)
    self.delta_bytes_max = 0  # largest decoded delta this window
    self.frame_max = 0        # largest websocket frame this window
    self.json_ms_max = 0      # slowest ujson.loads this window
    self.loop_gap_max = 0     # max ms between loop() entries (main-thread stall)
    self._loop_last = 0
    self._slow_warned = False

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

    # Reason string for a self-improve queued at response.done. It must not run
    # there: the ring buffer still holds seconds of the spoken answer, and
    # _run_improve's _mute_audio would reset the ring and cut the engine off
    # mid-sentence. loop() fires it once playback has fully drained.
    self.improve_pending = None
    # True from barge-in (speech_started) until the answering response is
    # created. A barge-in resets the ring to empty with response_active still
    # False, which would otherwise let a pending improve fire — blocking the
    # loop for a whole LLM call — right while the user is talking.
    self.user_speaking = False

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
    # Late-callback detector: this should fire every ~166 ms. A larger gap means
    # the DMA already looped stale data (heard as a repeat) before we refilled.
    now_ms = time.ticks_ms()
    if self._cb_last:
      gap = time.ticks_diff(now_ms, self._cb_last)
      if gap > self.cb_gap_max:
        self.cb_gap_max = gap
    self._cb_last = now_ms
    dest = self.spk_bufs[index]
    buf_size = len(dest)
    rpos = self._ring_rpos % self._ring_size
    fill = (self._ring_wpos - self._ring_rpos)  % self._ring_size

    # Integer math: the old float expression boxed a new float object on every
    # callback, adding steady garbage from inside the audio callback itself.
    pdeck.led(2, fill * 100 // self._ring_size)


    if self.buffering:
      if fill >= self.buffer_threshold and time.ticks_diff(time.ticks_ms(), self.mute_until) >= 0:
        self.buffering = False
      else:
        dest[:buf_size] = self.zero_buf[:buf_size]
        duration = time.ticks_diff(time.ticks_us(), t0)
        if duration > self.cb_time_max:
          self.cb_time_max = duration
        return

    if self.fill_min < 0 or fill < self.fill_min:
      self.fill_min = fill

    if fill < buf_size:
      self.buffering = True
      # Only a drain while a response is still streaming is a real underrun
      # (worth reporting and deepening the pre-roll cushion for). After
      # response.done all audio is already local, so running dry is just the
      # normal end of the utterance.
      if self.response_active:
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
    # Input transcription config differs by provider: OpenAI takes a Whisper
    # model + language; xAI takes a BCP-47 language_hint (no model field).
    if self.provider == "xai":
      transcription = {"language_hint": self.language} if self.language else {}
    else:
      transcription = {"model": "whisper-1", "language": self.language} if self.language else {"model": "whisper-1"}
    session = {
      "type": "realtime",
      "instructions": build_session_instructions(self.model, self.file_list, self.references, self.app_list, self.agent),
      "audio": {
        "input": {
          "format": {"type": "audio/pcm", "rate": self.sample_rate},
          "transcription": transcription,
          "turn_detection": {"type": "server_vad"}
        },
        "output": {
          "format": {"type": "audio/pcm", "rate": self.sample_rate},
          "voice": self.voice
        }
      }
    }
    if self.agent:
      session["tool_choice"] = "auto"
      # Realtime consumes the flat function format directly (same shape as the
      # Responses API), so build_tools drops in with no wrapping. web_search is
      # now a device-side function tool (not a hosted Realtime tool), so the
      # voice agent can search the web too.
      session["tools"] = gpt_tools.build_tools(self.app_list, agent=True, web_search=True, realtime=True)
    cfg = {"type": "session.update", "session": session}
    self.ws.send(ujson.dumps(cfg))

  def _ring_write(self, src, n):
    # Copy n bytes from src (a sliceable buffer) into the playback ring.
    # Returns False when the ring is full (caller counts the drop).
    wpos = self._ring_wpos % self._ring_size
    fill = (self._ring_wpos - self._ring_rpos + self._ring_size) % self._ring_size
    pdeck.led(2, fill * 100 // self._ring_size)
    if n > self._ring_size - fill:
      self.drop_count += 1
      print("Ring buffer full. Dropping")
      return False  # ring full; drop rather than corrupt
    end = wpos + n
    if end <= self._ring_size:
      self._ring_mv[wpos:end] = src[:n]
    else:
      tail = self._ring_size - wpos
      self._ring_mv[wpos:] = src[:tail]
      self._ring_mv[:n - tail] = src[tail:n]
    self._ring_wpos += n
    return True

  def _try_audio_delta(self, frame):
    # Zero-allocation fast path for response.output_audio.delta frames: detect
    # the type marker in the frame head, then base64-decode the delta straight
    # from the websocket receive buffer into _pcm_buf and copy it into the
    # ring. Skips ujson.loads, which would build a dict plus a multi-KB base64
    # string per delta — with the mic path, the main driver of gc pauses.
    # Returns True when the frame was consumed. Any frame it does not fully
    # recognize falls back to the json path (return False).
    n = len(frame)
    # The event's own "type" comes in the frame head; 80 bytes is enough and
    # avoids matching the same marker nested inside e.g. a response.done body.
    if _mem_find(frame, 0, n if n < 80 else 80, _DELTA_TYPE, len(_DELTA_TYPE)) < 0:
      return False
    p = _mem_find(frame, 0, n, _DELTA_B64_KEY, len(_DELTA_B64_KEY))
    if p < 0:
      return False  # dict-form delta (e.g. xAI): let handle_audio_delta parse it
    start = p + len(_DELTA_B64_KEY)
    end = _mem_find(frame, start, n, _QUOTE, 1)
    if end < 0:
      return False
    if end == start:
      return True   # empty delta; nothing to play
    self._bump_activity()  # the assistant is speaking: not idle
    pdeck.led(3, 0)
    # Grok packs 100 KB+ of PCM into a single delta (OpenAI sends small frequent
    # ones), far beyond _pcm_buf. Decode in _pcm_buf-sized chunks rather than
    # falling back to ujson.loads: parsing a 160 KB frame held the GIL for up to
    # ~1.2 s, starving the speaker callback so the DMA replayed stale audio
    # (heard as repeats, with no underrun since the ring never drained). The
    # chunk size is a multiple of 4 b64 chars (one 3-byte quantum) and the
    # payload is pure base64 — no whitespace/escapes — so splitting is safe.
    total = 0
    pos = start
    chunk = (len(self._pcm_buf) // 3) * 4
    while pos < end:
      span = end - pos
      if span > chunk:
        span = chunk
      m = _b64_decode(self._pcm_buf, frame, pos, span)
      if m > 0:
        self._ring_write(self._pcm_mv, m)
        total += m
      pos += span
    self.delta_fast += 1
    if total > self.delta_bytes_max:
      self.delta_bytes_max = total
    pdeck.led(3, 5)
    return True

  def handle_audio_delta(self, msg):
    delta = msg.get("delta")
    if not delta:
      return
    if isinstance(delta, dict):
      audio_b64 = delta.get("audio")
    else:
      audio_b64 = delta
    if audio_b64:
      pdeck.led(3,0)
      raw = ubinascii.a2b_base64(audio_b64)
      self._ring_write(memoryview(raw), len(raw))
      pdeck.led(3,5)
      self.delta_slow += 1
      if len(raw) > self.delta_bytes_max:
        self.delta_bytes_max = len(raw)
      if not self._slow_warned:
        self._slow_warned = True
        print("[dbg] audio deltas are taking the SLOW json path (dict-form "
              "delta, e.g. grok) - per-delta allocations will drive gc pauses")

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

  def handle_user_text_updated(self, text):
    # Cumulative transcript (xAI). Replace rather than append; printing is
    # deferred to print_user_text_if_ready when the model starts replying, by
    # which point this holds the full utterance.
    if text:
      self.user_text_partial = text
      self.user_text = text

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

    elif mtype == "conversation.item.input_audio_transcription.updated":
      # xAI sends the cumulative transcript (full text so far), not increments.
      self.handle_user_text_updated(msg.get("transcript", ""))

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
      self.user_speaking = True  # holds off a pending self-improve
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
      self.user_speaking = False  # response_active now gates the pending improve

    elif mtype == "response.done":
      self.response_active = False
      self.user_speaking = False  # safety net if response.created was never seen
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
          self.improve_pending = "periodic auto-improve"
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
      self.ws = SimpleWS(self.rt_host, "%s?model=%s" % (self.rt_path, self.model), port=self.rt_port, headers=self.headers)
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
    # Main-thread stall detector: a big gap between loop() entries means
    # something (gc, a long parse, a tool call) held the thread - and the GIL -
    # long enough to also delay the audio callback.
    now_ms = time.ticks_ms()
    if self._loop_last:
      g = time.ticks_diff(now_ms, self._loop_last)
      if g > self.loop_gap_max:
        self.loop_gap_max = g
    self._loop_last = now_ms
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

    # A queued self-improve runs only once the session is idle AND the spoken
    # answer has fully played out: ring drained, plus a grace period covering
    # the two DMA speaker buffers (~170 ms each) still sounding after the last
    # full ring read bumped last_play_time. Skipped while a timed program is
    # armed so the blocking improve call can't delay the resume nudge.
    if (self.improve_pending is not None and not self.response_active
        and not self.user_speaking and self.resume_at is None):
      fill = (self._ring_wpos - self._ring_rpos) % self._ring_size
      if fill == 0 and time.ticks_diff(time.ticks_ms(), self.last_play_time) >= 600:
        reason = self.improve_pending
        self.improve_pending = None
        self._run_improve(reason=reason)

    if self.mic_ready_idx != -1:
      idx = self.mic_ready_idx
      self.mic_ready_idx = -1

      if not self.mic_muted and active:
        if time.ticks_diff(time.ticks_ms(), self.last_play_time) < 400:
          pass
        else:
          # Build the input_audio_buffer.append frame in place: base64-encode
          # the mic buffer directly into the preallocated JSON envelope and
          # send a memoryview of it. Allocation-free (the base64 payload is
          # plain ASCII, so no JSON escaping is ever needed). Anything other
          # than a dropped link is logged instead of killing the app — losing
          # one mic buffer is inaudible, crashing is not.
          try:
            off = len(self._mic_prefix)
            nb64 = _b64_encode(self._mic_frame, off, self.mic_bufs[idx],
                               self.mic_buf_size)
            end = off + nb64
            self._mic_frame[end] = 0x22      # '"'
            self._mic_frame[end + 1] = 0x7d  # '}'
            self.ws.send(self._mic_frame_mv[:end + 2])
          except ConnectionLost:
            self.conn_lost = True
          except Exception as e:
            print("Mic send error:", e, file=self.vs)

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
      if len(frame) > self.frame_max:
        self.frame_max = len(frame)
      # Audio deltas take the zero-alloc fast path (decoded straight from the
      # receive buffer into the ring); everything else goes through json.
      try:
        handled = self._try_audio_delta(frame)
      except Exception:
        handled = False
      if handled:
        audio_frames += 1
        # Drain a few audio deltas per iteration so the ring refills quickly,
        # but cap it so the scheduler still runs the audio callback between
        # bursts (the main loop's sleep yields the GIL).
        if audio_frames >= 3:
          break
        continue
      try:
        t_json = time.ticks_us()
        msg = ujson.loads(frame)
        t_json = time.ticks_diff(time.ticks_us(), t_json) // 1000
        if t_json > self.json_ms_max:
          self.json_ms_max = t_json
        self.process_event(msg)
        if msg.get("type") == "response.output_audio.delta":
          audio_frames += 1
          if audio_frames >= 3:
            break
      except ConnectionLost:
        self.conn_lost = True
        break
      except Exception as e:
        print("Message Error:", e, "Frame:", bytes(frame[:80]), file=self.vs)

    if time.ticks_diff(time.ticks_ms(), self.last_stat_time) > 1000:
      fill = (self._ring_wpos - self._ring_rpos)
      # Glitch-hunt stat line. Always printed on an anomaly window (underrun,
      # drop, rx growth, or a speaker callback >250 ms late - i.e. a likely
      # DMA-repeat glitch even though no underrun fired); with -d it prints
      # every window that carried audio.
      rx_grow = self.ws.rx_grow
      self.ws.rx_grow = 0
      anomaly = (self.underrun_count or self.drop_count or rx_grow
                 or self.cb_gap_max > 250)
      if anomaly or (self.debug and (self.delta_fast or self.delta_slow or fill)):
        print("[dbg] ur=%d drop=%d fill=%d min=%d thr=%d cbgap=%dms cbmax=%dus "
              "fast=%d slow=%d dmax=%d fmax=%d json=%dms loopgap=%dms "
              "rxgrow=%d mem=%d" % (
          self.underrun_count, self.drop_count, fill, self.fill_min,
          self.buffer_threshold, self.cb_gap_max, self.cb_time_max,
          self.delta_fast, self.delta_slow, self.delta_bytes_max,
          self.frame_max, self.json_ms_max, self.loop_gap_max,
          rx_grow, gc.mem_free()))
      self.cb_gap_max = 0
      self.fill_min = -1
      self.delta_fast = 0
      self.delta_slow = 0
      self.delta_bytes_max = 0
      self.frame_max = 0
      self.json_ms_max = 0
      self.loop_gap_max = 0
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
  parser.add_argument('-m', '--model', action='store', default=None, help='Realtime backend: a name from /config/gpt.json (api:"realtime", e.g. grok-voice), or a raw OpenAI realtime model id. Default: OpenAI gpt-realtime-2.')
  parser.add_argument('-f', '--file', nargs='+', action='store', help='Attach file(s) as reference')
  parser.add_argument('-a', '--agent', action='store_true', help='Enable agent mode (function calling)')
  parser.add_argument('-l', '--language', action='store', default=None, help='Preferred speech-to-text language, e.g. ja for Japanese')
  parser.add_argument('-d', '--debug', action='store_true', help='Print a per-second [dbg] audio stat line on the REPL (anomaly windows print even without this)')
  args = parser.parse_args(args_in[1:])

  if not auto_connect.check(vs, silent = True):
    print("Network is not available", file=vs)
    return

  file_list = args.file or []
  agent = args.agent
  language = args.language
  if language == 'ja':
    setuni.main(vs, ['setuni'])

  # Resolve the realtime backend (-m names an api:"realtime" entry, or a raw
  # OpenAI model id). Key: the entry's own key wins; an OpenAI host with no entry
  # key falls back to /config/openai_api_key; a hosted provider like xAI must
  # carry its key on the entry; a local server may be keyless.
  rt = gpt.resolve_realtime(gpt.load_registry_ro(), args.model)
  model = rt["model"]
  is_openai = "openai.com" in rt["host"]
  api_key = rt["key"]
  if api_key is None and is_openai:
    api_key = gpt.read_api_key()
  if not api_key:
    if is_openai:
      print("No OpenAI API key. Put it in %s" % gpt.api_key_location(), file=vs)
      return
    if rt["provider"] == "xai" or "x.ai" in rt["host"]:
      print("No API key for %s. Add \"key\" to the api:\"realtime\" entry in /config/gpt.json." % rt["host"], file=vs)
      return
    api_key = ""   # local / OpenAI-compatible realtime server without auth

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

  print("Connecting to %s Realtime API (%s) using model %s..." % (rt["provider"], rt["host"], model), file=vs)
  headers = {"Authorization": "Bearer %s" % api_key} if api_key else {}

  try:
    ws = SimpleWS(rt["host"], "%s?model=%s" % (rt["path"], model), port=rt["port"], headers=headers)
    print("Connected!", file=vs)
  except Exception as e:
    print("Failed to connect: %s" % e, file=vs)
    return

  ra = RealtimeAgent(ws, vs, model, file_list, references, app_list, agent, language, headers, rt)
  ra.api_key = api_key   # for the memory summarizer's side request
  ra.debug = args.debug
  if rt["provider"] != "openai":
    # The self-evolving memory summarizer posts to OpenAI /chat/completions; it
    # isn't wired for other realtime providers yet, so don't auto-run it (it would
    # fail with a non-OpenAI key). The voice conversation itself is unaffected.
    ra.improve_every = 0
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

