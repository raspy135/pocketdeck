# gpt_c.py - ChatGPT client built on the Chat Completions API instead of the
# OpenAI-proprietary Responses API used by gpt.py.
#
# Why a separate frontend: the Responses API keeps conversation state on the
# server (previous_response_id), uses a flat tool schema and a built-in
# web_search tool, and ships input/output item shapes unique to OpenAI. The Chat
# Completions API (/v1/chat/completions) is the portable lingua franca that every
# provider and local server speaks: client-side `messages` history, a nested tool
# schema, and `tool`-role results. Talking Chat Completions means you can swap
# models/endpoints just by changing -m and the base URL. No reasoning_effort is
# sent, so plain (non-reasoning) models on any provider work unchanged.
#
# This reuses gpt.py (imported as `gpt`) and gpt_l.py (as `gptl`) for all the
# shared plumbing: the function tools and their implementations, the read_line
# editor, present_response, role/instruction assembly, STT/TTS, logging and the
# thinking animation. Only the API-specific seams are overridden here:
#   - build_tools_c(): wrap gpt.build_tools' flat function dicts into the nested
#     Chat Completions format (so the tool descriptions live in one place).
#   - chatgpt_chat: a chatgpt_agent subclass whose ask_agent drives a client-side
#     `messages` list (replacing previous_response_id) over /v1/chat/completions.
#   - conversation persistence to local JSON for --resume / --resume-id (Chat
#     Completions has no server-side state to resume).
#
# Differences from gpt.py (by design):
#   - No built-in web_search. The agent can still fetch pages with `curl` via
#     command_with_return.
#   - Full history is sent each round (Chat Completions is stateless), so long
#     agent turns cost more tokens; _prune_old_images() bounds memory by dropping
#     stale screenshots from history.

import sys
# On a PC (CPython) install stand-ins for the device-only modules before any are
# imported. Importing gpt below already does this, but be explicit/idempotent.
_IS_PC = sys.implementation.name != 'micropython'
if _IS_PC:
  import pc_compat
  pc_compat.install()

import ujson
import ubinascii
import time
import os
import gc
import argparse
import pdeck
import pdeck_utils as pu
import auto_connect
import setuni
import gpt          # the Responses-API frontend; we reuse its helpers/tools
import gpt_l as gptl

el = gptl.el


# ----------------------------------------------------------------------------
# Config file (device: /config/gpt_c.json, PC: ~/.config/gpt/gpt_c.json).
# Holds the API base URL and the default model so you can swap providers/models
# by editing one file. It is created with OpenAI defaults the first time gpt_c
# runs if it doesn't exist. The API key stays separate in /config/openai_api_key.
# ----------------------------------------------------------------------------

DEFAULT_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.4"


def config_path():
  if _IS_PC:
    d = os.path.expanduser("~/.config/gpt")
    try:
      os.makedirs(d, exist_ok=True)
    except Exception:
      pass
    return d + "/gpt_c.json"
  return "/config/gpt_c.json"


def _write_default_config(path):
  # Written by hand (not ujson.dump) so the on-device file is laid out one
  # setting per line and is easy to read and edit.
  content = ('{\n'
             '  "base_url": "%s",\n'
             '  "model": "%s"\n'
             '}\n') % (DEFAULT_BASE, DEFAULT_MODEL)
  with open(path, "w") as f:
    f.write(content)


def load_config(vs=None):
  """Return {'base_url', 'model'}, filling in OpenAI defaults for anything
  missing. If the file doesn't exist it is created with the defaults (graceful
  first run); a malformed file is left untouched and the defaults are used. A
  failure to create the file is non-fatal."""
  cfg = {"base_url": DEFAULT_BASE, "model": DEFAULT_MODEL}
  path = config_path()
  try:
    with open(path, "r") as f:
      data = ujson.load(f)
    if isinstance(data, dict):
      for k in ("base_url", "model"):
        if data.get(k):
          cfg[k] = data[k]
    return cfg
  except OSError:
    pass  # missing -> create below with defaults
  except Exception:
    return cfg  # malformed -> use defaults without clobbering the user's file
  try:
    _write_default_config(path)
    if vs is not None:
      print("Created config %s (edit base_url / model to swap providers)." % path, file=vs)
  except Exception:
    pass
  return cfg


def chat_url(base_url=None):
  return (base_url or DEFAULT_BASE).rstrip("/") + "/chat/completions"


# ----------------------------------------------------------------------------
# Conversation persistence (Chat Completions has no server-side state, so to
# continue a conversation across invocations we save the messages list locally
# and reuse gpt_l's rolling session-id list to remember which file is latest).
# ----------------------------------------------------------------------------

def conv_dir():
  if _IS_PC:
    d = os.path.expanduser("~/.config/gpt")
    try:
      os.makedirs(d, exist_ok=True)
    except Exception:
      pass
    return d
  return "/sd/log"


def conv_path(cid):
  return conv_dir() + "/gptconv_" + cid + ".json"


def make_conv_id():
  t = time.gmtime(time.time() + pu.timezone * 60 * 15)
  return "%02d%02d_%02d%02d%02d" % (t[1], t[2], t[3], t[4], t[5])


def save_conversation(messages, cid):
  try:
    with open(conv_path(cid), "w") as f:
      ujson.dump(messages, f)
    return True
  except Exception:
    return False


def load_conversation(cid):
  """Return the saved messages list for `cid`, or None if missing/unreadable."""
  try:
    with open(conv_path(cid), "r") as f:
      data = ujson.load(f)
    if isinstance(data, list):
      return data
  except Exception:
    pass
  return None


# ----------------------------------------------------------------------------
# Tool schema: reuse gpt.build_tools (flat function format) and wrap each into
# the nested Chat Completions shape. web_search is intentionally not included.
# ----------------------------------------------------------------------------

def build_tools_c(app_list, agent=False):
  flat = gpt.build_tools(app_list, agent=agent, web_search=False)
  tools = []
  for t in flat:
    if t.get("type") != "function":
      continue
    tools.append({
      "type": "function",
      "function": {
        "name": t.get("name", ""),
        "description": t.get("description", ""),
        "parameters": t.get("parameters", {"type": "object", "properties": {}}),
      },
    })
  return tools


# ----------------------------------------------------------------------------
# Chat Completions agent client
# ----------------------------------------------------------------------------

class chatgpt_chat(gpt.chatgpt_agent):
  def __init__(self, vs, base_url=None):
    super().__init__(vs)
    # /v1/chat/completions on the configured base (default OpenAI).
    self.url = chat_url(base_url)
    # Client-side conversation state. messages[0] is the system prompt; user /
    # assistant / tool turns accumulate here (replaces prev_response_id).
    self.messages = []

  # --- request payload -------------------------------------------------------

  def _build_user_content(self, message, references, images):
    """Chat Completions user content: a plain string when text-only, otherwise a
    content list mixing text and image_url parts."""
    if references:
      ref_text = ("I put some attached text files as reference. Then answer the "
                  "question by using attached information. You are not limited to "
                  "reference the attached text, you can use all your knowledge. \n")
      for i, item in enumerate(references):
        ref_text += "----- reference %d -----\n%s\n" % (i, item)
      ref_text += "----- Question -----\n"
      message = ref_text + message
    if not images:
      return message
    content = [{"type": "text", "text": message}]
    for img in images:
      if type(img) == str:
        url = img
      else:
        b64 = ubinascii.b2a_base64(img).decode('utf-8').strip()
        url = "data:image/jpeg;base64," + b64
      content.append({"type": "image_url", "image_url": {"url": url}})
    return content

  def _prune_old_images(self):
    """Drop image_url parts from prior messages so a long conversation full of
    screenshots doesn't exhaust the heap (Chat Completions resends everything
    each round). Images only need to live for the turn they're used in."""
    for m in self.messages:
      c = m.get("content")
      if not isinstance(c, list):
        continue
      kept = []
      dropped = False
      for it in c:
        if isinstance(it, dict) and it.get("type") == "image_url":
          dropped = True
          continue
        kept.append(it)
      if not dropped:
        continue
      if not kept:
        m["content"] = "[image omitted to save memory]"
      elif len(kept) == 1 and isinstance(kept[0], dict) and kept[0].get("type") == "text":
        m["content"] = kept[0].get("text", "")
      else:
        m["content"] = kept

  def _ensure_system(self, instructions):
    """Keep messages[0] as the current system prompt so role/tool/instruction
    changes mid-conversation take effect on the next turn."""
    if not instructions:
      return
    if self.messages and self.messages[0].get("role") == "system":
      self.messages[0]["content"] = instructions
    else:
      self.messages.insert(0, {"role": "system", "content": instructions})

  @staticmethod
  def _content_text(content):
    """Assistant content is usually a string; some providers return a list of
    parts. Reduce either to plain text."""
    if isinstance(content, str):
      return content
    if isinstance(content, list):
      out = ""
      for it in content:
        if isinstance(it, dict) and it.get("type") in ("text", "output_text"):
          out += it.get("text", "")
      return out
    return ""

  @staticmethod
  def _slim_tool_calls(tool_calls):
    """Reconstruct only the fields Chat Completions needs when the assistant's
    tool_calls are echoed back on the next request (drops index/extra fields)."""
    out = []
    for tc in tool_calls:
      fn = tc.get("function", {}) or {}
      out.append({
        "id": tc.get("id", ""),
        "type": "function",
        "function": {
          "name": fn.get("name", ""),
          "arguments": fn.get("arguments", "") or "",
        },
      })
    return out

  def ask_agent(self, message, references, images, model, instructions,
                tools, silent=False, max_iters=25):
    """Run one user turn over Chat Completions: append the user message, resolve
    any tool calls, and return the model's final text. self.messages carries the
    whole conversation so the next turn (conversation mode) continues it."""
    self._prune_old_images()
    self._ensure_system(instructions)
    pre_len = len(self.messages)   # rollback point if the turn fails outright
    self.messages.append({"role": "user",
                          "content": self._build_user_content(message, references, images)})

    final_text = None
    got_assistant = False
    pdeck.led(2, 0)  # clear the "result ready" indicator at the start of a turn

    for i in range(max_iters + 1):
      force_final = (i == max_iters)
      gc.collect()  # large JSON/base64 each round-trip fragments the small heap
      payload = {
        "model": model,
        "messages": self.messages,
      }
      if tools:
        payload["tools"] = tools
        if force_final:
          payload["tool_choice"] = "none"

      pdeck.led(1, 40)  # working: waiting for the model's response
      if not silent:
        _anim = gptl.ThinkingAnimation(self.vs, "Asking GPT..")
      response = self.post(self.url, ujson.dumps(payload).encode('utf-8'))
      try:
        data = response.json()
      except:
        if not silent:
          _anim.stop()
        print("Error: Non-JSON response (%s)" % response.status_code, file=self.vs)
        print(response.text[:200], file=self.vs)
        response.close()
        pdeck.led(1, 0)
        break
      response.close()
      if not silent:
        _anim.stop()
      pdeck.led(1, 0)  # got the response

      if data.get("error"):
        err = data["error"]
        msg = err.get("message", "Unknown error") if isinstance(err, dict) else str(err)
        print("API Error: %s" % msg, file=self.vs)
        break

      choices = data.get("choices") or []
      if not choices:
        print("API Error: no choices returned", file=self.vs)
        break
      msg = choices[0].get("message", {}) or {}
      content = msg.get("content")
      tool_calls = msg.get("tool_calls") or []

      # Record the assistant turn. The tool_calls must be echoed verbatim on the
      # next request so the following tool results can reference their ids.
      assistant_msg = {"role": "assistant", "content": self._content_text(content)}
      if tool_calls:
        assistant_msg["tool_calls"] = self._slim_tool_calls(tool_calls)
      self.messages.append(assistant_msg)
      got_assistant = True
      text_out = self._content_text(content)
      if text_out:
        final_text = text_out

      if not tool_calls:
        break

      if force_final:
        # Model ignored tool_choice="none" and still asked for calls. Answer them
        # with stubs so the history stays valid (an assistant message with
        # tool_calls must be followed by a tool result for every call).
        for tc in tool_calls:
          self.messages.append({
            "type": "tool", "role": "tool",
            "tool_call_id": tc.get("id", ""),
            "content": "[Reached tool-call limit; not executed.]",
          })
        print("\n[Reached tool-call limit; stopping here.]", file=self.vs)
        break

      # Execute the requested calls; each appends a tool-role result message.
      self.pending_image = None
      for tc in tool_calls:
        fn = tc.get("function", {}) or {}
        name = fn.get("name", "")
        call_id = tc.get("id", "")
        arguments = fn.get("arguments", "") or ""
        print("\n%s[Call]%s %s" % (el.bold(), el.bold_off(), self._call_display(name, arguments)), file=self.vs)
        # Plan mode: the two effectful tools must be confirmed before they run.
        if self.mode == 'plan' and name in ('command_with_return', 'write_file'):
          approved, feedback = self.confirm_tool(name, arguments)
          if not approved:
            result = "User declined to run %s (Plan mode)." % name
            if feedback:
              result += " User feedback: " + feedback
            print("%s[Skipped]%s %s" % (el.bold(), el.bold_off(), result[:200]), file=self.vs)
            self.messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
            continue
        try:
          result = self.execute_function_call(call_id, name, arguments)
        except BaseException as e:
          # Never let a tool (e.g. a module raising SystemExit) kill the session.
          result = "Error: %r" % (e,)
        print("%s[Result]%s %s" % (el.bold(), el.bold_off(), result[:200]), file=self.vs)
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": result})

      # A capture_screen call leaves a base64 PNG to feed back as a user image.
      # It must come AFTER every tool result (each tool_call needs its answer
      # first), as a fresh user turn.
      if self.pending_image is not None:
        self.messages.append({
          "role": "user",
          "content": [{
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + self.pending_image},
          }],
        })
        self.pending_image = None

    # A turn that produced nothing (hard failure) is rolled back so it doesn't
    # leave an orphan user message that would confuse the next turn.
    if final_text is None and not got_assistant:
      del self.messages[pre_len:]
    return final_text

  # --- tool guard ------------------------------------------------------------

  def execute_command_with_return(self, arguments):
    # Refuse to launch this assistant recursively (mirrors gpt.py's refusal of
    # gpt/gpt_l/gptn): a nested session would re-enter the whole loop on the
    # already-deep command stack and overflow.
    try:
      args = ujson.loads(arguments) if arguments else {}
      cmd = args.get("command", "").strip()
    except:
      cmd = ""
    parts = cmd.split()
    first = ""
    if parts:
      first = parts[1] if parts[0] == 'r' and len(parts) > 1 else parts[0]
    if first == 'gpt_c':
      return "Error: refusing to run 'gpt_c' recursively from inside the assistant."
    return super().execute_command_with_return(arguments)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main(vs, args_in):
  parser = argparse.ArgumentParser(description='ChatGPT query over the Chat Completions API (model-swappable)')
  parser.add_argument('-a', '--agent', action='store_true', help='Enable function-calling tools')
  parser.add_argument('-C', '--chat', action='store_true', help='Conversation mode (keep context across turns)')
  parser.add_argument('-P', '--plan', action='store_true', help='Start in Plan mode (confirm before running command_with_return / write_file). Default is Auto.')
  parser.add_argument('-n', '--nosave', action='store_true', help='do not save the result')
  parser.add_argument('-s', '--silent', action='store_true', help='Suppress progress output')
  parser.add_argument('-nf', '--no-format', action='store_true', help='do not format text (No bold)')
  parser.add_argument('-c', '--clipboard', action='store_true', help='use clipboard as reference text')
  parser.add_argument('-j', '--jp', action='store_true', help='Answer in Japanese')
  parser.add_argument('-f', '--file', nargs='+', action='store', help='Attach file(s) as reference. file1 file2...')
  parser.add_argument('-i', '--image', nargs='+', action='store', help='Attach image file(s) or image url(s). img1 img2...')
  parser.add_argument('-m', '--model', action='store', default=None, help='Model to use (any Chat Completions model id; default from config)')
  parser.add_argument('--base-url', action='store', default=None, help='API base URL (default: from config, else OpenAI)')
  parser.add_argument('-v', '--voice', action='store_true', help='Use voice mode (STT and TTS)')
  parser.add_argument('-vt', '--voice-type', action='store', default='coral', help='Voice type for TTS')
  parser.add_argument('-r', '--role', action='store', default=None, help="Role preset 'assistant' or 'coder', a /sd/roles/<name>.txt file, or literal text. Default: assistant.")
  parser.add_argument('--log-file', action='store', default=None, help='Internal: reuse the same log filename across iterations')
  parser.add_argument('--resume', action='store_true', help='Save this turn\'s conversation so a later call can continue it')
  parser.add_argument('--resume-id', '--resume_id', dest='resume_id', action='store', default=None, help="Continue a prior conversation: a conversation id, or 'last' for the most recent saved session")
  parser.add_argument('content', nargs='*', help='Content to ask')
  parser.add_argument('-q', nargs='+', help='Content to ask, use this when you want to specify content explicitly.')

  args = parser.parse_args(args_in[1:])

  if not auto_connect.check(vs, silent=True):
    print("Network is not available", file=vs)
    return

  # base_url + default model come from the config file (created on first run),
  # with --base-url / -m overriding per invocation.
  cfg = load_config(None if args.silent else vs)
  base_url = args.base_url or cfg['base_url']

  gpt_obj = chatgpt_chat(vs, base_url=base_url)
  if not gpt_obj.read_api_key():
    return
  gpt_obj.mode = 'plan' if args.plan else 'auto'

  # Conversation continuity across separate invocations: --resume-id loads a
  # saved messages list, --resume persists the new one afterward. 'last'
  # resolves to the most recent entry in the session list.
  resumed_from = None
  if args.resume_id:
    rid = gptl.last_session_id() if args.resume_id == 'last' else args.resume_id
    msgs = load_conversation(rid) if rid else None
    if msgs:
      gpt_obj.messages = msgs
      resumed_from = rid
      if not args.silent:
        print("Resuming session %s" % rid, file=vs)
    else:
      if not args.silent:
        print("No previous session to resume; starting new.", file=vs)

  message = ""
  tts_response = False

  if args.voice and not args.q and not args.content:
    rec_file = "/sd/work/voice_rec.wav"
    gptl.record_audio(vs, rec_file)
    print("Transcribing...", file=vs)
    message = gpt_obj.stt(rec_file)
    if not message:
      print("Failed to transcribe audio", file=vs)
      return
    print("You (STT): %s" % message, file=vs)
    tts_response = True
  elif not args.content and not args.q:
    if not args.chat:
      message = gptl.get_message(vs)
  else:
    if args.content:
      message += ' '.join(args.content)
    if args.q:
      if len(args.q) == 1 and gptl.file_exists(args.q[0]):
        with open(args.q[0], "r") as f:
          message = f.read()
      else:
        message += ' '.join(args.q)

  if len(message) == 0 and not args.chat:
    return

  references = []
  images = []

  if message:
    message, _, margs = gptl.parse_inline_directives(message, references, images, args, vs)
  else:
    margs = {}

  jp = margs['jp'] if 'jp' in margs else args.jp
  if jp:
    # Switch the terminal to the unicode font first so Japanese (and the IME
    # pre-edit) can render. The IME itself stays off until toggled with Alt+`/j.
    try:
      setuni.main(vs, ['setuni'])
      gpt_obj.jp_font_loaded = True
    except Exception:
      pass

  # Attach -f files / clipboard / -i images (sent on the first turn).
  if args.file:
    for file in args.file:
      if file.startswith("http://") or file.startswith("https://"):
        references.append(file)
        continue
      try:
        with open(file, 'r') as f:
          references.append("---- " + file + " ----\n" + f.read())
      except Exception:
        print("Error when opening %s" % file, file=vs)
        return

  clipboard = margs['clipboard'] if 'clipboard' in margs else args.clipboard
  if clipboard:
    references.append(pdeck.clipboard_paste().decode("utf-8"))

  if args.image:
    for img_path in args.image:
      if img_path.startswith("http://") or img_path.startswith("https://"):
        images.append(img_path)
      else:
        try:
          with open(img_path, 'rb') as f:
            images.append(f.read())
        except Exception:
          print("Error when opening image %s" % img_path, file=vs)
          return

  model = gpt.resolve_model(margs['model'] if 'model' in margs else (args.model or cfg['model']))

  # Role / persona. Default is a plain assistant; -r picks a preset (plain,
  # coder), a /sd/roles/<name>.txt file, or literal text. The coder preset also
  # turns the tools on.
  role, role_wants_agent = gpt.resolve_role(args.role)
  agent = args.agent or (role_wants_agent is True)

  # Agent tools drive the device (run modules, screens, apps) and don't exist on
  # a PC, so plain chat is the only supported PC mode.
  if _IS_PC and agent:
    print("Agent mode is unavailable on PC; continuing as plain chat.", file=vs)
    agent = False

  # gpt_c's own screen, so we can tell the agent to switch the foreground back
  # here when it wants the user to read its answer.
  try:
    my_screen = pdeck.get_screen_num()
  except Exception:
    my_screen = None

  # Agent tools + auto-attached Pocket Deck references.
  app_list = []
  if agent:
    app_list = gpt.load_app_list()
    gpt_obj.app_list = app_list
    if not args.silent:
      print("Agent mode: %d app(s)." % len(app_list), file=vs)
    references += gpt.load_agent_references(vs, silent=args.silent)

  log_filename = args.log_file or gptl.make_log_filename()
  jp_suffix = " and answer in Japanese" if jp else ""

  # Mutable per-conversation config so slash commands can change it on the fly.
  ctx = {
    'model': model,
    'role': role,
    'tts': tts_response,
    'agent': agent,
    'app_list': app_list,
    'instructions': gpt.assemble_instructions(role, tts_response, agent, app_list, my_screen),
    'tools': build_tools_c(app_list, agent=agent),
  }

  def run_turn(turn_message, refs, imgs):
    ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
    time_str = "[User current time: %04d-%02d-%02d %02d:%02d]\n" % (ctime[0], ctime[1], ctime[2], ctime[3], ctime[4])
    full = time_str + turn_message + jp_suffix
    raw = gpt_obj.ask_agent(full, refs, imgs, ctx['model'], ctx['instructions'],
                            ctx['tools'], silent=args.silent)
    gpt.present_response(vs, gpt_obj, full, raw, args, margs, log_filename)
    return raw

  def persist_resume(turn_message):
    """Save the conversation so a later --resume-id can continue it."""
    if not args.resume or not gpt_obj.messages:
      return
    cid = resumed_from or make_conv_id()
    if save_conversation(gpt_obj.messages, cid):
      gptl.save_session(cid, turn_message, replace_id=resumed_from)

  if not args.chat:
    try:
      run_turn(message, references, images)
    finally:
      pdeck.led(1, 0)
      pdeck.led(2, 0)
    persist_resume(message)
    return

  # ---- Conversation mode ----
  history = []
  pending_refs = []   # files queued via /file for the next message

  def refresh():
    ctx['instructions'] = gpt.assemble_instructions(ctx['role'], ctx['tts'], ctx['agent'], ctx['app_list'], my_screen)
    ctx['tools'] = build_tools_c(ctx['app_list'], agent=ctx['agent'])

  def mode_prompt():
    label = '[Plan]' if gpt_obj.mode == 'plan' else '[Auto]'
    jp_marker = ' あ' if gpt_obj.jp_ime else ''
    return el.bold() + label + el.bold_off() + jp_marker + ': '

  def toggle_mode():
    gpt_obj.mode = 'auto' if gpt_obj.mode == 'plan' else 'plan'

  def ensure_jp_font():
    if not gpt_obj.jp_font_loaded:
      try:
        setuni.main(vs, ['setuni'])
        gpt_obj.jp_font_loaded = True
      except Exception:
        pass

  def toggle_ime():
    gpt_obj.jp_ime = not gpt_obj.jp_ime
    if gpt_obj.jp_ime:
      ensure_jp_font()
    return gpt_obj.jp_ime

  def show_help():
    print(
      "Commands:\n"
      "  /help              this help\n"
      "  /quit  /exit       leave conversation\n"
      "  /clear /reset      start fresh (clear conversation context)\n"
      "  /model [name]      show or set model (m/medium, h/high, f/fast, or id)\n"
      "  /role [name|text]  show/set role: presets 'assistant' or 'coder' (resets context)\n"
      "  /tools             toggle function-calling tools (agent) on/off\n"
      "  /mode [auto|plan]  show/set execution mode (no arg toggles); also /auto, /plan\n"
      "  /file <path>       attach a file as reference for the next message\n"
      "  /history           show recent input history\n"
      "Plan mode confirms each command_with_return / write_file before it runs.\n"
      "Japanese input: Alt+` or Alt+j toggles the kana IME (best with -j font).\n"
      "Editing: arrows move, Up/Down history, Ctrl-A/E start/end, Ctrl-K/U kill, Ctrl-C cancel, Shift-Tab toggles mode.",
      file=vs)

  def handle_command(line):
    """Return False to quit, True to keep chatting."""
    parts = line[1:].split()
    if not parts:
      return True
    cmd = parts[0].lower()
    arg = line[1 + len(parts[0]):].strip()
    if cmd in ('quit', 'exit', 'q'):
      return False
    elif cmd in ('help', 'h', '?'):
      show_help()
    elif cmd in ('clear', 'reset', 'new'):
      gpt_obj.messages = []
      print("New conversation (context cleared).", file=vs)
    elif cmd == 'model':
      if arg:
        ctx['model'] = gpt.resolve_model(arg)
      print("Model: %s" % ctx['model'], file=vs)
    elif cmd == 'role':
      if arg:
        rtext, rwants = gpt.resolve_role(arg)
        ctx['role'] = rtext
        if rwants and not ctx['agent']:
          ctx['agent'] = True
          if not ctx['app_list']:
            ctx['app_list'] = gpt.load_app_list()
            gpt_obj.app_list = ctx['app_list']
        refresh()
        gpt_obj.messages = []
        print("Role set to '%s'%s (context reset)." %
              (arg, " (tools on)" if ctx['agent'] else ""), file=vs)
      else:
        print("Role presets: assistant, coder. Current role:\n%s" %
              (ctx['role'] or gpt.DEFAULT_ROLE), file=vs)
    elif cmd in ('mode', 'auto', 'plan'):
      if cmd == 'auto':
        gpt_obj.mode = 'auto'
      elif cmd == 'plan':
        gpt_obj.mode = 'plan'
      elif arg in ('auto', 'plan'):
        gpt_obj.mode = arg
      elif not arg:
        toggle_mode()              # /mode with no argument flips it
      else:
        print("Mode must be auto|plan.", file=vs)
      print("Mode: %s%s" % (gpt_obj.mode,
            " (confirms command_with_return / write_file)" if gpt_obj.mode == 'plan' else ""), file=vs)
    elif cmd in ('tools', 'agent'):
      ctx['agent'] = not ctx['agent']
      if ctx['agent'] and not ctx['app_list']:
        ctx['app_list'] = gpt.load_app_list()
        gpt_obj.app_list = ctx['app_list']
      refresh()
      print("Tools %s." % ("on" if ctx['agent'] else "off"), file=vs)
    elif cmd == 'file':
      if not arg:
        print("Usage: /file <path>", file=vs)
      elif gptl.file_exists(arg):
        try:
          with open(arg, "r") as f:
            pending_refs.append("---- " + arg + " ----\n" + f.read())
          print("Attached %s for the next message." % arg, file=vs)
        except Exception as e:
          print("Error reading %s: %s" % (arg, e), file=vs)
      else:
        print("Not found: %s" % arg, file=vs)
    elif cmd in ('history', 'hist'):
      for h in history[-20:]:
        print("  " + h, file=vs)
    else:
      print("Unknown command: /%s  (try /help)" % cmd, file=vs)
    return True

  print("Conversation mode (Chat Completions). /help for commands, /quit to exit.", file=vs)
  print("Mode: %s (Shift-Tab or /mode to switch; Plan confirms commands & writes)." % gpt_obj.mode, file=vs)
  if gpt.jp_input is not None:
    print("Japanese: Alt+` or Alt+j toggles kana input%s." %
          ("" if jp else " (use -j for the unicode font)"), file=vs)

  sent_initial = False
  first = True
  while True:
    if first and message:
      line = message.strip()
    else:
      line = gpt.read_line(vs, mode_prompt, history, on_shift_tab=toggle_mode,
                           allow_ime=(gpt.jp_input is not None), ime_on=gpt_obj.jp_ime,
                           on_ime_toggle=toggle_ime)
      if line is None:        # Ctrl-C cancelled this line
        first = False
        continue
      line = line.strip()
    first = False

    if not line:
      continue
    if not history or history[-1] != line:
      history.append(line)

    if line[0] == '/':
      if not handle_command(line):
        print("Bye.", file=vs)
        break
      continue

    turn_refs = list(pending_refs)
    pending_refs[:] = []
    turn_imgs = []
    if not sent_initial:
      turn_refs = references + turn_refs
      turn_imgs = images
      sent_initial = True
    # A turn must never drop the user out of the conversation: contain any
    # failure (network error, etc.) and keep prompting.
    try:
      run_turn(line, turn_refs, turn_imgs)
    except BaseException as e:
      print("\n[Turn failed; you can keep going] %r" % (e,), file=vs)

  pdeck.led(1, 0)  # leaving conversation: clear status LEDs
  gpt_obj.led2_gen += 1  # invalidate any pending auto-off timer
  pdeck.led(2, 0)


# On a PC the device shell isn't there to call main(vs, args); provide an entry
# point so `python3 gpt_c.py ...` works. (On the device gpt_c is imported.)
if __name__ == '__main__':
  main(pc_compat.PCStream(), ['gpt_c'] + sys.argv[1:])
