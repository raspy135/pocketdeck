import sys
# On a PC (CPython) install stand-ins for the device-only modules below before
# they are imported. On the device this branch is skipped entirely.
_IS_PC = sys.implementation.name != 'micropython'
if _IS_PC:
  import pc_compat
  pc_compat.install()

import network
import auto_connect
import codec_config
import ujson
import time
import math
import urequests as requests
import pdeck
import pdeck_utils as pu
import esclib as elib
import argparse
import audio
import wav_play
import recorder
import os
import gc

# Per-socket timeout for every model request. Without one, urequests never
# calls settimeout() and a stalled TLS socket blocks the app forever - the
# retry loop in post() only ever sees OSError, so a hang can't trigger it.
# This is per socket operation, not a deadline for the whole turn: a reasoning
# model sends nothing until it's done thinking, so keep it generous.
REQUEST_TIMEOUT = 300

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

def user_dir(device_dir, pc_sub=""):
  """Where config/logs live for the current platform: `device_dir` as-is on the
  device, ~/.config/gpt[/pc_sub] (created on demand) on a PC."""
  if not _IS_PC:
    return device_dir
  d = os.path.expanduser("~/.config/gpt")
  if pc_sub:
    d += "/" + pc_sub
  try:
    os.makedirs(d, exist_ok=True)
  except Exception:
    pass
  return d

# Options accepted inside a [[...]] block, by argparse dest. Anything else the
# block names is reported and ignored (-f included: an attachment can't be added
# after the message has been built).
_INLINE_DESTS = ('model', 'effort', 'jp', 'clipboard', 'no_format', 'nosave',
                 'voice', 'voice_type')
_inline_p = None

def inline_parser():
  """Parser for a [[...]] option block. Every default is None so the caller can
  tell "set inline" from "left alone"; built once (ArgumentParser opens a screen
  stream) and reused."""
  global _inline_p
  if _inline_p is None:
    p = argparse.ArgumentParser(description='inline options')
    p.add_argument('-m', '--model', default=None)
    p.add_argument('-e', '--effort', default=None)
    p.add_argument('-j', '--jp', action='store_true', default=None)
    p.add_argument('-c', '--clipboard', action='store_true', default=None)
    p.add_argument('-nf', '--no-format', action='store_true', default=None)
    p.add_argument('-n', '--nosave', action='store_true', default=None)
    p.add_argument('-v', '--voice', action='store_true', default=None)
    p.add_argument('-vt', '--voice-type', default=None)
    p.add_argument('-i', '--image', nargs='+', default=None)
    _inline_p = p
  return _inline_p

def load_images(paths, images, vs):
  """Append each path (or http/https url) to `images` as raw bytes (or the url).
  Returns False if a file could not be read."""
  ok = True
  for path in paths or []:
    if path.startswith("http://") or path.startswith("https://"):
      images.append(path)
      continue
    try:
      with open(path, 'rb') as f:
        images.append(f.read())
    except Exception:
      print("Error when opening image %s" % path, file=vs)
      ok = False
  return ok

def parse_inline_directives(message, references, images, vs):
  """Strip [[...]] directives out of `message`. A block starting with '-' is a
  set of options for this message only; any other block is a file path attached
  as a reference. Returns (cleaned_message, margs), margs holding just the
  options that were actually set inline."""
  idx = 0
  result = ""
  margs = {}

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
    handled = True

    if block[:1] == '-':
      try:
        ns, unknown = inline_parser().parse_known_args(block.split())
      except BaseException:
        # argparse reports a missing value itself, then exits; keep the turn.
        print("Inline option error in [[%s]]; ignored." % block, file=vs)
        ns, unknown = None, []
      if unknown:
        print("Inline option note: unsupported %s" % " ".join(unknown), file=vs)
      if ns is not None:
        load_images(getattr(ns, 'image', None), images, vs)
        for dest in _INLINE_DESTS:
          val = getattr(ns, dest, None)
          if val is not None:
            margs[dest] = val

    elif file_exists(block):
      try:
        with open(block, 'r') as f:
          references.append("---- " + block + " ----\n" + f.read())
      except Exception as e:
        print("Error reading inline reference %s: %s" % (block, e), file=vs)

    else:
      print("Inline reference file not found: %s" % block, file=vs)
      handled = False

    if not handled:
      result += message[start:end+2]

    idx = end + 2

  return result, margs

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

# ----------------------------------------------------------------------------
# Audio (STT/TTS) backend resolution. Lives here (the shared lib) so both the
# gpt frontend and standalone tools like tts.py can select an api:"audio" entry
# from /config/gpt.json without importing the heavy gpt module.
# ----------------------------------------------------------------------------
OPENAI_BASE = "https://api.openai.com/v1"

def registry_path():
  """The model registry file (/config/gpt.json on the device)."""
  return user_dir("/config") + "/gpt.json"

DEFAULT_AUDIO = {
  "base_url": OPENAI_BASE,
  "key": None,                          # None + OpenAI base -> shared openai_api_key
  "tts_model": "tts-1-hd",
  "stt_model": "gpt-4o-mini-transcribe",
  "voice": "coral",
  "format": "wav",
}


def load_registry_ro():
  """Read /config/gpt.json without creating or rewriting it (unlike the gpt
  frontend's load_registry). Returns the parsed dict, or {} if missing/bad."""
  try:
    with open(registry_path(), "r") as f:
      data = ujson.load(f)
    return data if isinstance(data, dict) else {}
  except Exception:
    return {}


def _normalize_audio(entry):
  """Fill an audio entry with defaults so every field is present."""
  e = entry or {}
  return {"base_url": e.get("base_url") or OPENAI_BASE,
          "key": e.get("key"),          # None distinguishes 'unset' from '' (keyless)
          "tts_model": e.get("tts_model") or DEFAULT_AUDIO["tts_model"],
          "stt_model": e.get("stt_model") or DEFAULT_AUDIO["stt_model"],
          "voice": e.get("voice") or DEFAULT_AUDIO["voice"],
          "format": e.get("format") or DEFAULT_AUDIO["format"]}


def resolve_audio(registry, name=None):
  """Resolve an STT/TTS backend from a registry dict. `name` may be an api:"audio"
  entry (used directly), or a model entry whose "audio" link is followed; None
  uses the registry's top-level "audio" default. Falls back to the OpenAI backend
  when nothing matches. Returns a normalized audio dict."""
  registry = registry or {}
  models = registry.get("models") or []

  def find_audio(n):
    if not n:
      return None
    for m in models:
      if (isinstance(m, dict) and m.get("name") == n
          and (m.get("api") or "").lower() == "audio"):
        return m
    return None

  a = find_audio(name)                          # 1) name is a direct audio entry
  if a is None and name:                        # 2) name is a model -> follow its link
    for m in models:
      if isinstance(m, dict) and m.get("name") == name:
        a = find_audio(m.get("audio"))
        break
  if a is None:                                 # 3) registry-wide default
    a = find_audio(registry.get("audio"))
  return _normalize_audio(a)


def apply_audio_config(obj, audio):
  """Point a client's STT/TTS at the resolved audio backend."""
  base = audio["base_url"].rstrip("/")
  obj.stt_url = base + "/audio/transcriptions"
  obj.tts_url = base + "/audio/speech"
  obj.tts_model = audio["tts_model"]
  obj.stt_model = audio["stt_model"]
  obj.voice = audio["voice"]
  obj.audio_format = audio["format"]
  key = audio["key"]
  if key is None and base == OPENAI_BASE:
    # OpenAI audio with no explicit key: reuse the shared OpenAI key file, even
    # when the LLM endpoint is a keyless local server.
    k = read_api_key()
    key = k if k else ""
  obj.audio_key = key if key is not None else ""


# ----------------------------------------------------------------------------
# Realtime (voice-agent) backend resolution. The Realtime WebSocket protocol is
# shared by OpenAI and OpenAI-compatible providers (e.g. xAI's Grok Voice Agent
# at wss://api.x.ai/v1/realtime), so gpt_rt can target either from an
# api:"realtime" entry in /config/gpt.json. Defaults to OpenAI.
# ----------------------------------------------------------------------------
DEFAULT_REALTIME_MODEL = "gpt-realtime-2"


def _ws_host_path(url):
  """From a base_url like wss://api.x.ai/v1 or https://api.openai.com/v1 return
  (host, port, path_prefix). The scheme is informational only — the Realtime link
  is always TLS WebSocket."""
  for pre in ("wss://", "ws://", "https://", "http://"):
    if url.startswith(pre):
      url = url[len(pre):]
      break
  slash = url.find("/")
  if slash == -1:
    hostport, prefix = url, ""
  else:
    hostport, prefix = url[:slash], url[slash:]
  if ":" in hostport:
    host, p = hostport.split(":", 1); port = int(p)
  else:
    host, port = hostport, 443
  return host, port, prefix


def _normalize_realtime(entry, raw_name):
  """Fill a realtime backend from an api:"realtime" entry (or None). `raw_name`
  is the -m value when it isn't a registered entry — treated as a bare model id
  on OpenAI, preserving the old `gpt_rt -m <model>` behavior."""
  e = entry or {}
  host, port, prefix = _ws_host_path(e.get("base_url") or "https://api.openai.com/v1")
  path = prefix.rstrip("/") + "/realtime"
  provider = (e.get("provider") or "").lower()
  if not provider:
    if "x.ai" in host:
      provider = "xai"
    else:
      provider = "openai"        # OpenAI or an OpenAI-compatible server
  model = e.get("model") or raw_name or DEFAULT_REALTIME_MODEL
  voice = e.get("voice") or ("eve" if provider == "xai" else "marin")
  return {"host": host, "port": port, "path": path, "key": e.get("key"),
          "model": model, "voice": voice, "provider": provider}


def resolve_realtime(registry, name=None):
  """Resolve the realtime backend for gpt_rt. `name` selects an api:"realtime"
  entry; a name that isn't one is treated as a raw OpenAI model id; None uses the
  registry's top-level "realtime" default, else OpenAI. Returns a dict with host,
  port, path, key, model, voice, provider."""
  registry = registry or {}
  models = registry.get("models") or []

  def find_rt(n):
    if not n:
      return None
    for m in models:
      if (isinstance(m, dict) and m.get("name") == n
          and (m.get("api") or "").lower() == "realtime"):
        return m
    return None

  entry = find_rt(name)
  if entry is None and not name:
    entry = find_rt(registry.get("realtime"))
  # If `name` was given but isn't a realtime entry, keep it as a raw model id.
  raw = name if (entry is None and name) else None
  return _normalize_realtime(entry, raw)


def make_log_filename():
  ctime = time.gmtime(time.time()+pu.timezone*60*15)
  name = f"gptlog{ctime[1]:02}{ctime[2]:02}_{ctime[3]:02}{ctime[4]:02}.md"
  return user_dir("/sd/log", "log") + "/" + name

# ----------------------------------------------------------------------------
# Conversation session list (for --resume / --resume-id)
# ----------------------------------------------------------------------------
# A small rolling log of recent conversations so a separate gpt invocation can
# continue one server-side (Responses API previous_response_id). Each line is:
#   response_id, YYYY-MM-DD HH:MM, trimmed initial prompt
# Only the response id and datetime are parsed back; the prompt is a human hint.

SESSION_MAX = 10

def session_list_path():
  return user_dir("/sd/log") + "/gpt_session_list"

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

def split_url(url):
  """Split a URL into (host, port, path, use_tls). Accepts http:// (plain) and
  https:// (TLS); a bare host defaults to https. Used by the raw-socket STT
  upload so it can target a local server, not just api.openai.com."""
  if url.startswith("https://"):
    use_tls = True; rest = url[8:]; default_port = 443
  elif url.startswith("http://"):
    use_tls = False; rest = url[7:]; default_port = 80
  else:
    use_tls = True; rest = url; default_port = 443
  slash = rest.find("/")
  if slash == -1:
    hostport, path = rest, "/"
  else:
    hostport, path = rest[:slash], rest[slash:]
  if ":" in hostport:
    host, p = hostport.split(":", 1); port = int(p)
  else:
    host, port = hostport, default_port
  return host, port, path, use_tls


class ChunkedReader:
  """De-chunks an HTTP/1.1 `Transfer-Encoding: chunked` body, presenting the raw
  payload through read()/readinto() so wav_play sees only audio bytes. Chunked is
  the natural transport for streaming TTS (length unknown up front), so we consume
  it rather than avoid it."""
  def __init__(self, sock):
    self.s = sock
    self.rem = 0          # bytes left in the current chunk
    self.done = False

  def _discard(self, n):
    while n > 0:
      d = self.s.read(n)
      if not d:
        break
      n -= len(d)

  def _next_chunk(self):
    line = self.s.readline()
    if not line:
      self.done = True
      return
    size = line.split(b';', 1)[0].strip()   # ignore any chunk extensions
    try:
      self.rem = int(size, 16)
    except ValueError:
      self.done = True
      return
    if self.rem == 0:                        # terminating 0-length chunk
      self.done = True

  def read(self, n=-1):
    if self.rem == 0 and not self.done:
      self._next_chunk()
    if self.rem == 0:
      return b''
    want = self.rem if (n is None or n < 0 or n > self.rem) else n
    data = self.s.read(want)
    if not data:
      self.done = True
      return b''
    self.rem -= len(data)
    if self.rem == 0:
      self._discard(2)                       # trailing CRLF after chunk data
    return data

  def readinto(self, buf):
    # Fill the whole buffer (looping across chunk boundaries) so callers that
    # treat a short read as end-of-stream (wav_play) don't stop early.
    mv = memoryview(buf)
    total = 0
    while total < len(buf):
      data = self.read(len(buf) - total)
      if not data:
        break
      mv[total:total + len(data)] = data
      total += len(data)
    return total

  def close(self):
    try:
      self.s.close()
    except Exception:
      pass


class AudioResponse:
  """Minimal response for the raw-socket audio POST, matching the parts callers
  use: .status_code, .raw (a readable stream), .content, .close()."""
  def __init__(self, status_code, sock, stream):
    self.status_code = status_code
    self.s = sock
    self.raw = stream

  @property
  def content(self):
    chunks = []
    while True:
      d = self.raw.read(1024)
      if not d:
        break
      chunks.append(d)
    return b''.join(chunks)

  def close(self):
    try:
      if self.raw is not self.s:
        self.raw.close()
    except Exception:
      pass
    try:
      self.s.close()
    except Exception:
      pass


def sse_events(resp):
  """Yield the JSON payload of each `data:` line of an SSE body as a dict.

  Reads in blocks rather than byte-at-a-time: ChunkedReader.read() never asks
  the socket for more than the current chunk holds, so a block read returns as
  soon as the server has flushed an event instead of waiting for a full buffer.
  Malformed/keepalive lines are skipped; `[DONE]` ends the stream."""
  raw = resp.raw
  buf = b''
  while True:
    nl = buf.find(b'\n')
    if nl < 0:
      try:
        d = raw.read(512)
      except Exception:
        return
      if not d:
        return
      buf += d
      continue
    line = buf[:nl].rstrip(b'\r')
    buf = buf[nl + 1:]
    if not line.startswith(b'data:'):
      continue                       # event:/id:/comment lines carry nothing new
    body = line[5:].strip()
    if body == b'[DONE]':
      return
    try:
      yield ujson.loads(body)
    except Exception:
      continue


class chatgpt_util:
  def __init__(self,vs):
    self.vs = vs
    self.url = "https://api.openai.com/v1/responses"
    self.stt_url = "https://api.openai.com/v1/audio/transcriptions"
    self.tts_url = "https://api.openai.com/v1/audio/speech"
    self.api_key = ""
    # Audio (STT/TTS) backend, configurable independently of the LLM endpoint.
    # audio_key is None until set: the methods then fall back to api_key, so a
    # plain OpenAI setup keeps working unchanged.
    self.audio_key = None
    self.tts_model = "tts-1-hd"
    self.stt_model = "gpt-4o-mini-transcribe"
    self.voice = "coral"
    self.audio_format = "wav"

  def _audio_auth(self):
    """Bearer token for audio calls: the audio_key if configured, else the LLM
    key (backward-compatible OpenAI behavior)."""
    return self.audio_key if self.audio_key is not None else self.api_key

  def _net_diag(self):
    """One-line health snapshot for a failed request: link state plus internal
    (DMA-capable) heap, which is what the Wi-Fi driver allocates TX buffers
    from. OSError(-1) is lwip ERR_IF - the Wi-Fi netif refused a packet -
    which in practice means the station lost the AP or the driver could not
    get an internal buffer (heap pressure after a long session)."""
    parts = []
    try:
      sta = network.WLAN(network.STA_IF)
      parts.append("wifi=%s" % ("up" if sta.isconnected() else "DOWN"))
    except Exception:
      pass
    try:
      import esp32
      free = 0
      largest = 0
      for region in esp32.idf_heap_info(esp32.HEAP_DATA):
        free += region[1]
        if region[2] > largest:
          largest = region[2]
      parts.append("idf free=%dK largest=%dK" % (free // 1024, largest // 1024))
    except Exception:
      pass
    return " ".join(parts)

  def post(self, url, json=None):
    headers = {
      'Content-Type' : 'application/json',
      'Accept': 'application/json',
      'Authorization' : 'Bearer ' + self.api_key
      }
    # Each request is its own connection, and on a busy device the send side
    # fails transiently: OSError(-1) is lwip ERR_IF (Wi-Fi driver refused the
    # packet - dropped link or no internal TX buffer), and resets/timeouts
    # appear under the same conditions. Retry after freeing memory and
    # re-checking the link. A failure while reading the reply re-issues the
    # request, which at worst duplicates one model call - better than losing
    # the turn.
    attempts = 3
    for attempt in range(attempts):
      try:
        return requests.post(url, headers=headers, data=json,
                             timeout=REQUEST_TIMEOUT)
      except OSError as e:
        print("\nRequest failed: %r  [%s]" % (e, self._net_diag()), file=self.vs)
        if attempt == attempts - 1:
          raise
        gc.collect()
        time.sleep(1 + attempt)
        try:
          auto_connect.check(self.vs, silent=True)
        except Exception:
          pass
        print("Retrying (%d/%d)..." % (attempt + 2, attempts), file=self.vs)

  def read_api_key(self):
    self.api_key = read_api_key()
    if self.api_key == False:
      print("No API key found. Put your key in %s" % api_key_location(), file=self.vs)
      return False
    return True
    

  def complete(self, prompt, model=None, instructions=None):
    """One-shot text completion: send `prompt`, return the reply text (or None).
    No tool loop, no history, no printing — for lightweight callers like
    flashcards. gpt_c.chatgpt_chat overrides this for the Chat Completions API,
    so a caller can stay agnostic to which endpoint the model uses."""
    payload = {
      "model": model or "gpt-5.4-mini",
      "reasoning": {"effort": "medium"},
      "input": [{"type": "message", "role": "user",
                 "content": [{"type": "input_text", "text": prompt}]}],
    }
    if instructions:
      payload['instructions'] = instructions
    return self.ask(ujson.dumps(payload))

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
        'Content-Disposition: form-data; name="model"\r\n\r\n' + self.stt_model + '\r\n'
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

    host, port, path, use_tls = split_url(self.stt_url)
    addr = usocket.getaddrinfo(host, port)[0][-1]
    s = usocket.socket()
    try:
      s.connect(addr)
      if use_tls:
        try:
          s = ssl.wrap_socket(s, server_hostname=host)
        except TypeError:
          s = ssl.wrap_socket(s)

      auth = self._audio_auth()
      auth_line = ("Authorization: Bearer %s\r\n" % auth) if auth else ""
      req_head = (
          "POST %s HTTP/1.0\r\n"
          "Host: %s\r\n"
          "Connection: close\r\n"
          "Content-Type: multipart/form-data; boundary=%s\r\n"
          "Content-Length: %d\r\n"
          "%s\r\n"
          % (path, host, boundary, content_length, auth_line)
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

  def tts_stream(self, text, voice=None):
    """Converts text to speech and returns a response object with a raw stream.
    Model / voice / format come from the configured audio backend; `voice` (when
    given) overrides the backend default for this call."""
    payload = ujson.dumps({
        "model": self.tts_model,
        "input": text,
        "voice": voice or self.voice,
        #"speed" : 1.1,
        "response_format": self.audio_format
    }).encode('utf-8')

    if _IS_PC:
      # The PC shim buffers the whole (already de-chunked) body; keep using it.
      headers = {'Content-Type': 'application/json'}
      auth = self._audio_auth()
      if auth:
        headers['Authorization'] = 'Bearer ' + auth
      return requests.post(self.tts_url, headers=headers, data=payload)
    return self._audio_post(self.tts_url, payload)

  def _audio_post(self, url, payload):
    """Raw-socket POST for the audio endpoints (like stt()), returning an
    AudioResponse whose .raw streams the body. urequests doesn't de-chunk when
    you read .raw, and streaming TTS servers (uvicorn/Qwen etc.) reply with
    Transfer-Encoding: chunked — so we parse the response ourselves and unwrap
    the chunking, letting the WAV player see clean audio bytes."""
    return self._raw_post(url, payload, "audio/wav", self._audio_auth())

  def _raw_post(self, url, payload, accept, auth, timeout=REQUEST_TIMEOUT):
    """The socket half of _audio_post, shared with the SSE stream: connect,
    send the request, parse the status line and headers, and hand back a
    de-chunked readable body."""
    host, port, path, use_tls = split_url(url)
    import usocket
    try:
      import ussl as ssl
    except ImportError:
      import ssl
    addr = usocket.getaddrinfo(host, port)[0][-1]
    s = usocket.socket()
    s.connect(addr)
    s.settimeout(timeout)   # a stalled stream must not hang the device forever
    if use_tls:
      try:
        s = ssl.wrap_socket(s, server_hostname=host)
      except TypeError:
        s = ssl.wrap_socket(s)

    req = ("POST %s HTTP/1.1\r\n"
           "Host: %s\r\n"
           "Connection: close\r\n"
           "Content-Type: application/json\r\n"
           "Accept: %s\r\n"
           "Content-Length: %d\r\n" % (path, host, accept, len(payload)))
    if auth:
      req += "Authorization: Bearer %s\r\n" % auth
    req += "\r\n"
    s.write(req.encode('utf-8'))
    s.write(payload)

    line = s.readline()
    try:
      status = int(line.split(None, 2)[1])
    except Exception:
      status = 0
    chunked = False
    sse = False
    while True:                                  # consume + inspect headers
      h = s.readline()
      if not h or h == b'\r\n':
        break
      hl = h.lower()
      if hl.startswith(b'transfer-encoding:') and b'chunked' in hl:
        chunked = True
      elif hl.startswith(b'content-type:') and b'event-stream' in hl:
        sse = True
    raw = ChunkedReader(s) if chunked else s
    r = AudioResponse(status, s, raw)
    r.sse = sse
    return r

  def stream_post(self, url, payload):
    """POST expecting a Server-Sent Events reply. Returns the response (check
    .sse: False means the endpoint answered with a plain body instead, so the
    caller should fall back to the blocking path)."""
    return self._raw_post(url, payload, "text/event-stream", self.api_key)

el = elib.esclib()

class KeyWatch:
  """Non-blocking ESC watch for the long request paths. Anything typed that
  isn't ESC is stashed and handed back to the keyboard in release(), so
  type-ahead while the model works isn't swallowed."""
  def __init__(self, v):
    self.v = v
    self.pressed = False
    self._typed = b''

  def poll(self):
    try:
      r = self.v.read_nb_bytes(8)
    except Exception:
      return self.pressed
    if r and r[0]:
      d = r[1]
      if b'\x1b' in d:
        self.pressed = True
        d = d.replace(b'\x1b', b'')
      if d:
        self._typed += d
    return self.pressed

  def release(self):
    if self._typed:
      try:
        self.v.send_char(self._typed)
      except Exception:
        pass
      self._typed = b''


class ThinkingAnimation:
  _SPIN = '▌▄▐▀'
  _CHARS = '▁▂▃▄▅▆▇█'
  _COLS = [36, 92, 33, 92]  # cyan → lightgreen → yellow → lightgreen

  def __init__(self, vs, label='Asking GPT..', interrupt_label=None):
    self.vs = vs
    self.label = label
    # Shown instead of `label` once ESC is seen. None = this caller ignores
    # interrupts (e.g. TTS), so the label never changes.
    self.interrupt_label = interrupt_label
    self.tick = 0
    self.running = True
    # Set when the user hits ESC while the request is in flight; the caller
    # reads it after stop().
    self.interrupted = False
    self.keys = None
    self._el = elib.esclib()
    if _IS_PC:
      # No frame callback on a PC: just print the label once.
      print(label, file=vs)
      return
    if hasattr(self.vs, 'v'):
      self.v = vs.v
      self.keys = KeyWatch(self.v)
      self.v.callback(self.update)
    vs.write('\r\n\r\n')

  def update(self, e):
    if not self.running:
      self.v.finished()
      return

    self._poll_keys()
    self.tick += 1
    if self.tick % 32:
      self.v.finished()
      return
    t = self.tick // 32
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

  def _poll_keys(self):
    """Look for ESC while the request blocks on the socket. This callback is
    scheduled by the display task but runs on the main thread from
    mp_handle_pending() inside the socket read retry loop, so it is the only
    place a keypress is seen during a blocking request."""
    if self.keys.poll() and not self.interrupted:
      self.interrupted = True
      if self.interrupt_label:
        self.label = self.interrupt_label

  def stop(self):
    self.running = False
    if _IS_PC:
      return
    if hasattr(self.vs, 'v'):
      self.v.callback(None)
      self.keys.release()   # give back what wasn't ESC
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
