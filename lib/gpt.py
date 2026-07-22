# gpt.py - ChatGPT client with native function calling (tools) instead of the
# markdown code-block "agent mode" used by the legacy gpt_l.py.
#
# This reuses gpt_l.py (the legacy frontend, imported below as `gpt`) for all
# the shared plumbing (api key, logging, STT/TTS, the thinking animation,
# message formatting, etc.) and adds:
#   - the function tools that were implemented for gpt_rt.py (command_with_return,
#     write_file, launch_app, list_running_apps, switch_screen, capture_screen,
#     send_keys)
#   - a function-calling loop over the Responses API
#   - an optional conversation mode (-C) that keeps the context across turns
#     using previous_response_id (server-side state).

import sys
# On a PC (CPython) install stand-ins for the device-only modules below before
# any of them (or the MicroPython builtins) are imported. Skipped on the device.
_IS_PC = sys.implementation.name != 'micropython'
if _IS_PC:
  import pc_compat
  pc_compat.install()

import ujson
import ubinascii
import time
import os
import io
import argparse
import re
import gc
import pdeck
import pdeck_utils as pu
import pngwriter
import setuni
import auto_connect
import gpt_l as gpt
import gpt_tools  # shared tool schema + transport-independent executors
import ai_improve  # self-evolving long-term memory (/improve, update_memory)

# Optional Japanese IME (romaji -> kana -> kanji), shared with pem. If the
# module is unavailable the conversation prompt simply stays ASCII-only.
try:
  import jp_input
except ImportError:
  jp_input = None

# Used to auto-clear the "result ready" LED a couple of seconds after output
# without blocking the prompt. Absent on the desktop emulator.
try:
  import _thread
except ImportError:
  _thread = None

el = gpt.el


# ----------------------------------------------------------------------------
# Helpers ported from gpt_rt.py
# ----------------------------------------------------------------------------

def print_exc(e, vs):
  """Print a traceback (with line numbers) for `e` to `vs`, so a failed turn
  points at the offending line instead of just its repr. Works on both the
  device (sys.print_exception) and a PC (traceback)."""
  try:
    sys.print_exception(e, vs)
  except AttributeError:
    import traceback
    traceback.print_exception(type(e), e, e.__traceback__, file=vs)
  except Exception:
    pass


def load_app_list():
  result = []
  for path in ('/config/apps.json', '/config/agent_apps.json'):
    try:
      with open(path, 'r') as f:
        result += ujson.load(f)
    except:
      pass
  return result


# ----------------------------------------------------------------------------
# Training-data capture (-T / --training). Each completed turn is appended to
# /sd/training_data/<file>.jsonl as one OpenAI-style {"messages": [...]} record
# holding the full agent trajectory: system prompt, user message, each
# assistant tool-call round, the tool results, and the final answer. Input
# attachments (reference files, images) are NOT dumped — only a small count —
# so the dataset doesn't balloon with the auto-attached README etc.; long tool
# results are capped at TRAIN_MAX_FIELD chars. Capture is implemented for the
# Chat Completions client (gpt_c) only; the Responses client leaves it unset.
# ----------------------------------------------------------------------------

TRAIN_MAX_FIELD = 8000


def make_training_filename():
  # Just the path; the directory is created lazily on the first write (see
  # append_training_example) so enabling -T never leaves an empty directory
  # behind when nothing ends up being captured.
  ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
  name = "train%02d%02d_%02d%02d.jsonl" % (ctime[1], ctime[2], ctime[3], ctime[4])
  d = "/sd/training_data"
  if _IS_PC:
    d = os.path.expanduser("~/.config/gpt/training_data")
  return d + "/" + name


def _ensure_parent_dir(path):
  d = path.rsplit("/", 1)[0]
  try:
    os.makedirs(d, exist_ok=True)
  except (AttributeError, TypeError):
    try:
      os.mkdir(d)            # MicroPython: no makedirs; single level under /sd
    except OSError:
      pass
  except OSError:
    pass


def append_training_example(path, record, vs=None):
  """Append one JSONL example, creating the parent dir on first write. Returns
  True on success; on failure reports the error to `vs` (if given) instead of
  swallowing it, so a bad write/serialize is visible rather than silently
  producing an empty dataset."""
  try:
    line = ujson.dumps(record)
  except Exception as e:
    if vs is not None:
      print("[training] could not serialize example: %r" % (e,), file=vs)
    return False
  try:
    _ensure_parent_dir(path)
    with open(path, "a") as f:
      f.write(line)
      f.write("\n")
    return True
  except Exception as e:
    if vs is not None:
      print("[training] could not write %s: %r" % (path, e), file=vs)
    return False


def _tools_for_training(tools):
  """Convert the tool list into the Chat fine-tuning shape so it matches the
  emitted messages. Responses-API function tools are flat
  ({"type":"function","name":..,"parameters":..}); the fine-tune format nests
  them under "function". Non-function entries (e.g. hosted web_search) pass
  through unchanged."""
  out = []
  for t in tools or []:
    if not isinstance(t, dict):
      continue
    if t.get("type") == "function" and "function" not in t:
      fn = {"name": t.get("name", "")}
      if t.get("description"):
        fn["description"] = t["description"]
      if "parameters" in t:
        fn["parameters"] = t["parameters"]
      out.append({"type": "function", "function": fn})
    else:
      out.append(t)
  return out


# ----------------------------------------------------------------------------
# Skills — one markdown file per named procedure. Users invoke a skill from the
# prompt with a slash, Claude-CLI style: /<skill-name>. User skills live in
# /sd/Documents/skills (they win on a name clash); read-only system skills that
# ship with the device live in /sd/lib/skills.
# ----------------------------------------------------------------------------

SKILL_DIRS = ('/sd/Documents/skills', '/sd/lib/skills')


def _skill_key(name):
  # Normalize a skill name / filename to the token typed after the slash, so
  # "Morning Ritual.md", "morning-ritual" and "morning_ritual" all match.
  name = name.strip().lower()
  if name.endswith('.md'):
    name = name[:-3]
  return name.replace('-', '_').replace(' ', '_')


def list_skills():
  """All skills as (token, path, source); user skills first, de-duped by token."""
  out = []
  seen = {}
  for source, d in (('user', SKILL_DIRS[0]), ('system', SKILL_DIRS[1])):
    try:
      files = sorted(os.listdir(d))
    except OSError:
      continue
    for f in files:
      if not f.lower().endswith('.md'):
        continue
      token = _skill_key(f)
      if token in seen:
        continue
      seen[token] = True
      out.append((token, d + '/' + f, source))
  return out


def skill_tokens(prefix=''):
  """Sorted, de-duplicated skill tokens for tab-completion, optionally filtered
  to those starting with `prefix`."""
  toks = sorted(set(t for (t, _p, _s) in list_skills()))
  if prefix:
    toks = [t for t in toks if t.startswith(prefix)]
  return toks


def find_skill(name):
  """Resolve a typed name to (path, content), or None if no skill matches."""
  key = _skill_key(name)
  for token, path, _source in list_skills():
    if token == key:
      try:
        with open(path, 'r') as fh:
          return (path, fh.read())
      except OSError:
        return None
  return None


def compose_skill_message(path, content, arg):
  """Turn a skill file into a user message that asks the agent to carry it out."""
  head = "The user invoked the skill `%s`." % path
  if arg:
    head += " Extra input for this run: %s" % arg
  return (head + " Read it and carry it out step by step, following its "
          "instructions exactly.\n\n----- skill: %s -----\n%s\n----- end skill -----"
          % (path, content))


# CaptureStream / _parse_cmd_string moved to pdeck_utils (shared with the
# device shell pipeline). Re-exported here for any callers that still
# reference them via this module.
CaptureStream = pu.CaptureStream
_parse_cmd_string = pu.parse_cmd_string


def build_agent_instructions(app_list, my_screen=None):
  """System prompt describing the function tools (mirrors gpt_rt.py)."""
  text = (
    "You have function tools for working directly on the device;\n"
    "A runnable script/app is a module that defines main(vs, args); run it by "
    "passing its name (plus arguments) to command_with_return. After you EDIT a "
    "script and run it again, prefix the command with 'r ' (e.g. 'r temp_foo') so "
    "the module is reloaded — without it the old cached code runs instead of your "
    "edits. Keep scratch/experimental scripts in /sd/py with names starting temp_* "
    "and rm them when finished. "
    "main(vs, args) receives an output stream as its first argument; write results "
    "with print(..., file=vs) so command_with_return can capture and return that "
    "output to you (plain print() goes to the REPL and is NOT captured).\n"
    "Use command_with_return to look up information too (e.g. list files with "
    "'ls /sd/Documents/word*', read a file with 'cat /path', search with grep).\n "
    "**Pocket Deck is not Linux**: no redirects ('>'), no '&&' or ';', no subshells."
    "See README.md for full command list.\n"
    "The device keeps an activity log under /sd/elog/, one markdown file per day "
    "named YYYY-MM-DD.md, each line an event: app launches, file opens/saves, and "
    "shell commands the user ran. Read the current day's file as needed.\n"
    "The user keeps SKILLS at /sd/Documents/skills/ — one markdown file per "
    "skill: a named, reusable procedure you can perform (a routine with steps "
    "and timings, a recurring workflow like a morning writing setup, a document "
    "format to follow). When the user asks for something by name ('do my morning "
    "ritual', 'make the weekly report'), or asks what you can do, 'ls "
    "/sd/Documents/skills' and cat the matching file, then follow its "
    "instructions step by step. When the user teaches you a repeatable procedure "
    "worth keeping, offer to save it there as a new skill file (the folder may "
    "not exist yet — 'mkdir /sd/Documents/skills' first if needed).\n"
    "The device also ships read-only SYSTEM skills at /sd/lib/skills/. Before you "
    "write a graphical app (dashboard, chart, meter), cat "
    "/sd/lib/skills/dashboard_design.md and follow it; 'ls /sd/lib/skills' for the "
    "rest.\n"
    "You can see and drive other apps running on the device. Use list_running_apps "
    "to see which app is on which screen. Use switch_screen to bring a screen to "
    "the foreground. IMPORTANT: screen numbers in these tools are 0-based and match "
    "what list_running_apps reports (screen 0 is the Python REPL), but the user's "
    "point of view it's 1-based, so the screen the user calls '2' is screen 1 here — "
    "always pass the 0-based number from list_running_apps, switch_screen. "
    "Use capture_screen to take a screenshot of a screen and look "
    "at it (it is returned to you as an image); it takes some time."
    "Use send_keys to type into the app in the "
    "foreground; set enter=true to press Enter, and use escape sequences for "
    "special keys (Up=\\x1b[A, Down=\\x1b[B, Right=\\x1b[C, Left=\\x1b[D, Esc=\\x1b, "
    "Backspace=\\x08, Ctrl-X=\\x18). After acting, capture_screen again to confirm "
    "the result before continuing.\n"
    "To read TEXT a command-line app printed (e.g. to diagnose an error the user "
    "asks about), prefer read_console_log over a screenshot — it returns the "
    "recent console text directly and cheaply.\n"
    "You do not have to solve everything alone. If the same approach has failed "
    "twice, or you need a decision, permission, or information only the user has, "
    "call ask_user with a short question instead of retrying in circles — then "
    "stop and wait for the answer. Asking early beats a long stretch of failing "
    "tool calls.\n"
  )
  if my_screen is not None:
    text += ("\nIMPORTANT: your own screen — where your typed answers are shown — "
             "is screen %d. While working you may switch to other screens to drive "
             "apps, but the user only sees the foreground screen. Whenever you have "
             "an answer or output you want the user to read, call switch_screen(%d) "
             "to bring your screen back to the foreground before you finish.\n"
             % (my_screen, my_screen))
  if app_list:
    text += ("\nUse launch_app to open apps. Pass optional args (e.g. a file path) "
             "to open a specific file. Besides the registered apps listed below, "
             "any installed module can be launched by its module name (e.g. 'myapp' "
             "for /sd/lib/myapp.py). Available apps:\n")
    for item in app_list:
      if isinstance(item, list) and len(item) == 2:
        name = item[0]
        info = item[1]
        desc = info.get('description', '') if isinstance(info, dict) else ''
        text += "  - %s: %s\n" % (name, desc)
  return text


# build_tools moved to gpt_tools (shared, single source of truth). Re-exported
# here so existing callers (and gpt_c.build_tools_c) keep using gpt.build_tools.
build_tools = gpt_tools.build_tools


# ----------------------------------------------------------------------------
# Model registry (/config/gpt.json)
# ----------------------------------------------------------------------------
# An Ollama-style list of named model entries. Each entry selects an API
# ('responses' -> this module's Responses client, 'chat' -> gpt_c's Chat
# Completions client) plus its base_url and model id. -m and the /model command
# pick an entry by name. The file is created with OpenAI defaults on first run.
# An entry may carry its own "key" (bearer token) for providers that need one
# (e.g. xAI); with no "key", OpenAI endpoints fall back to /config/openai_api_key
# for backward compatibility and every other endpoint is called without auth.

OPENAI_BASE = "https://api.openai.com/v1"

DEFAULT_REGISTRY_MODELS = [
  {"name": "gpt-5.4", "api": "responses", "model": "gpt-5.4"},
  {"name": "gpt-5.5", "api": "responses", "model": "gpt-5.5"},
  {"name": "gpt-5.4-mini", "api": "responses", "model": "gpt-5.4-mini"},
]
DEFAULT_REGISTRY_DEFAULT = "gpt-5.4"


def config_path():
  if _IS_PC:
    d = os.path.expanduser("~/.config/gpt")
    try:
      os.makedirs(d, exist_ok=True)
    except Exception:
      pass
    return d + "/gpt.json"
  return "/config/gpt.json"


def _format_registry(models, default):
  # Hand-formatted (not ujson.dump) so the on-device file stays one entry per
  # line and is easy to read and edit.
  lines = ['{', '  "default": "%s",' % default, '  "models": [']
  for i, m in enumerate(models):
    parts = ['"name": "%s"' % m.get("name", ""),
             '"api": "%s"' % m.get("api", "responses")]
    if m.get("base_url"):
      parts.append('"base_url": "%s"' % m["base_url"])
    parts.append('"model": "%s"' % m.get("model", m.get("name", "")))
    comma = "," if i < len(models) - 1 else ""
    lines.append("    {" + ", ".join(parts) + "}" + comma)
  lines.append("  ]")
  lines.append("}")
  return "\n".join(lines) + "\n"


def load_registry(vs=None):
  """Return {'default': name, 'models': [entry, ...]}. Creates the file with
  OpenAI defaults on first run. A malformed file falls back to the built-in
  defaults untouched."""
  default_reg = {"default": DEFAULT_REGISTRY_DEFAULT,
                 "models": list(DEFAULT_REGISTRY_MODELS)}
  path = config_path()
  try:
    with open(path, "r") as f:
      data = ujson.load(f)
    if isinstance(data, dict) and isinstance(data.get("models"), list) and data["models"]:
      return data
    if vs is not None:
      print("Warning: %s has no usable 'models' list; using defaults." % path, file=vs)
    return default_reg
  except OSError:
    pass  # missing -> create below with defaults
  except Exception as e:
    if vs is not None:
      print("Warning: could not parse %s (%s); using defaults." % (path, e), file=vs)
    return default_reg
  try:
    with open(path, "w") as f:
      f.write(_format_registry(DEFAULT_REGISTRY_MODELS, DEFAULT_REGISTRY_DEFAULT))
    if vs is not None:
      print("Created model config %s (edit to add models/endpoints)." % path, file=vs)
  except Exception:
    pass
  return default_reg


def _normalize_entry(entry):
  """Fill defaults so callers can rely on every field being present."""
  name = entry.get("name") or entry.get("model") or DEFAULT_REGISTRY_DEFAULT
  api = (entry.get("api") or "responses").lower()
  if api in ("completions", "chat_completions", "openai_chat"):
    api = "chat"
  return {"name": name, "api": api,
          "base_url": entry.get("base_url") or OPENAI_BASE,
          "model": entry.get("model") or name,
          "effort": entry.get("effort"),
          "key": entry.get("key"),
          "audio": entry.get("audio")}  # link to an api:"audio" entry, if any


def resolve_entry(registry, name):
  """Resolve a model name to a normalized entry. None -> the registry default;
  a registered name -> that entry; a legacy shortcut (f/m/h...) or any other
  string -> an ad-hoc OpenAI Responses entry with that model id."""
  models = registry.get("models") or []
  if not name:
    name = registry.get("default") or (models[0].get("name") if models else DEFAULT_REGISTRY_DEFAULT)
  for m in models:
    if isinstance(m, dict) and m.get("name") == name:
      return _normalize_entry(m)
  # Not registered: a legacy shortcut or raw model id -> ad-hoc Responses entry.
  return _normalize_entry({"name": name, "api": "responses", "model": resolve_model(name)})


# Audio (STT/TTS) backend resolution lives in gpt_l (imported as `gpt`) so it is
# shared with standalone tools like tts.py: gpt.resolve_audio / gpt.apply_audio_config.
# A local LLM can still use OpenAI — or a local OpenAI-compatible speech server —
# for voice; with no api:"audio" entry selected it defaults to OpenAI.


def make_client(entry, vs):
  """Build the API client for a normalized registry entry: the Responses client
  (this module) for api 'responses', else gpt_c's Chat Completions client."""
  if entry["api"] == "chat":
    import gpt_c  # lazy: gpt_c imports this module at top level
    obj = gpt_c.chatgpt_chat(vs, base_url=entry["base_url"])
  else:
    obj = chatgpt_agent(vs)
    obj.url = entry["base_url"].rstrip("/") + "/responses"
  obj.base_url = entry["base_url"]  # remembered so /model can detect endpoint changes
  return obj


def init_client(entry, vs, plan_mode, registry=None):
  """Build a client for `entry`, load the API key and set the execution mode.
  An explicit "key" on the entry is used verbatim as the bearer token (for
  non-OpenAI providers like xAI that need their own key). With no "key", an
  OpenAI endpoint falls back to /config/openai_api_key (required, returns None
  if missing) for backward compatibility; any other endpoint proceeds keyless.
  When `registry` is given, the STT/TTS backend is resolved and applied too."""
  obj = make_client(entry, vs)
  key = entry.get("key")
  if key:
    obj.api_key = key.strip()
  elif entry["base_url"].rstrip("/") == OPENAI_BASE:
    if not obj.read_api_key():
      return None
  else:
    obj.api_key = ""  # no key field -> no authorization
  obj.mode = 'plan' if plan_mode else 'auto'
  if registry is not None:
    gpt.apply_audio_config(obj, gpt.resolve_audio(registry, entry.get("audio")))
  return obj


# ----------------------------------------------------------------------------
# Agent client
# ----------------------------------------------------------------------------

class chatgpt_agent(gpt.chatgpt_util, gpt_tools.ToolExecBase):
  # Capability flags + hooks the shared driver in main() reads so it can drive
  # either client uniformly. gpt_c.chatgpt_chat overrides these for Chat
  # Completions (no server-side effort, no built-in web_search, can compact).
  API = "responses"
  USE_EFFORT = True
  USE_WEB_SEARCH = True
  CAN_COMPACT = False
  def __init__(self, vs):
    super().__init__(vs)
    self.app_list = []
    self.capture_buf = None
    self.pending_image = None
    # Server-side conversation state. Chaining requests with this id lets the
    # server keep prior turns so we only send the new user message each turn.
    self.prev_response_id = None
    # Execution mode for effectful tools. 'auto' runs command_with_return and
    # write_file without asking; 'plan' confirms each one with the user first.
    # Toggled at runtime via the /mode|/auto|/plan commands or Shift-Tab.
    self.mode = 'auto'
    # Japanese IME state for conversation-mode input. jp_ime tracks whether the
    # romaji->kana IME is active (toggled with Alt+`/Alt+j); jp_font_loaded
    # records whether the unicode terminal font has been switched in.
    self.jp_ime = False
    self.jp_font_loaded = False
    # Generation token for the deferred "result ready" LED (2) auto-off, so a
    # stale timer can't clear an LED that a newer result has just relit.
    self.led2_gen = 0
    # Training-data capture: when set to a path, each completed turn's full
    # trajectory is appended there as a JSONL example (-T / --training).
    self.training_file = None

  def schedule_led2_off(self, secs=2):
    """Turn LED 2 off `secs` seconds from now in a tiny background thread, so
    the prompt isn't blocked. Guarded by led2_gen: if a newer result lights the
    LED (or the conversation ends) before the timer fires, this no-ops."""
    self.led2_gen += 1
    gen = self.led2_gen
    def _worker():
      try:
        time.sleep(secs)
      except Exception:
        return
      if self.led2_gen == gen:
        try:
          pdeck.led(2, 0)
        except Exception:
          pass
    if _thread is None:
      return            # no threads (emulator): leave it; next turn clears it
    try:
      _thread.start_new_thread(_worker, ())
    except Exception:
      pass

  # --- uniform client interface (shared driver in main() calls these) --------

  def reset_context(self):
    self.prev_response_id = None

  def build_tools_for(self, app_list, agent):
    # Genuine OpenAI endpoints get OpenAI's hosted web_search; any other
    # Responses-compatible provider (e.g. xAI) has no hosted search, so it falls
    # back to the device-side web_search function instead of scraping with curl.
    hosted = getattr(self, 'base_url', '').rstrip('/') == OPENAI_BASE
    return build_tools(app_list, agent=agent, web_search=True, hosted_search=hosted)

  def resume_from(self, rid, vs=None, silent=False):
    """Seed server-side context from a saved session id ('last' = most recent).
    Returns the id resumed from, or None."""
    resumed = gpt.last_session_id() if rid == 'last' else rid
    self.prev_response_id = resumed
    if not silent and vs is not None:
      if resumed:
        print("Resuming session %s" % resumed[:24], file=vs)
      else:
        print("No previous session to resume; starting new.", file=vs)
    return resumed

  def persist_session(self, turn_message, resumed_from):
    """Save the new response id so a later --resume-id can continue this chat.
    A new id distinct from what we resumed from means the turn produced a fresh
    response; if they match (or it's None) the turn failed, so skip."""
    new_id = self.prev_response_id
    if new_id and new_id != resumed_from:
      gpt.save_session(new_id, turn_message, replace_id=resumed_from)

  # --- request payload -------------------------------------------------------

  def _build_content(self, message, references, images):
    content_items = []
    if len(references) > 0:
      ref_text = ("I put some attached text files as reference. Then answer the "
                  "question by using attached information. You are not limited to "
                  "reference the attached text, you can use all your knowledge. \n")
      for i, item in enumerate(references):
        ref_text += "----- reference %d -----\n%s\n" % (i, item)
      ref_text += "----- Question -----\n"
      message = ref_text + message
    content_items.append({"type": "input_text", "text": message})
    if images:
      for img in images:
        if type(img) == str:
          img_url = img
        else:
          b64 = ubinascii.b2a_base64(img).decode('utf-8').strip()
          img_url = "data:image/jpeg;base64," + b64
        content_items.append({"type": "input_image", "image_url": img_url})
    return content_items

  def ask_agent(self, message, references, images, model, instructions, effort,
                tools, silent=False, max_iters=25):
    """Run one user turn: send the message, resolve any function calls, and
    return the model's final text. Keeps self.prev_response_id updated so the
    next turn (conversation mode) continues the same context."""
    content_items = self._build_content(message, references, images)
    input_list = [{"type": "message", "role": "user", "content": content_items}]
    prev_id = self.prev_response_id
    final_text = None
    in_flight = False  # True once we have answered outputs not yet confirmed delivered
    pdeck.led(2, 0)  # clear the "result ready" indicator at the start of a turn

    # Cap the tool round-trips. On the final allowed round we set
    # tool_choice="none" so the model returns a text answer instead of yet
    # another call. That round still carries the previous batch of
    # function_call_outputs, so self.prev_response_id never ends up pointing at a
    # response with an unanswered function call — which would otherwise make the
    # *next* turn fail with "no tool output found for function call ...".
    ask_stop = False  # set when the model calls ask_user: next round is text-only
    for i in range(max_iters + 1):
      force_final = (i == max_iters) or ask_stop
      gc.collect()  # large JSON/base64 each round-trip fragments the small heap
      payload = {
        "model": model,
        "reasoning": {"effort": effort},
        "tools": tools,
        "input": input_list,
      }
      if instructions:
        payload["instructions"] = instructions
      if prev_id:
        payload["previous_response_id"] = prev_id
      if force_final:
        payload["tool_choice"] = "none"

      pdeck.led(1, 40)  # working: waiting for the model's response
      if not silent:
        _anim = gpt.ThinkingAnimation(self.vs, "Asking GPT..")
      try:
        response = self.post(self.url, ujson.dumps(payload).encode('utf-8'))
      except BaseException:
        # post() already retried; a raise here means the network is really
        # down. Stop the animation (it would keep drawing forever) and drop a
        # broken chain before letting the caller report the failure.
        if not silent:
          _anim.stop()
        pdeck.led(1, 0)
        if in_flight:
          self.prev_response_id = None  # outputs never delivered; chain is broken
        raise
      try:
        data = response.json()
      except:
        if not silent:
          _anim.stop()
        # If the body read itself died (e.g. connection reset mid-read), the
        # socket is already closed and .text would raise; keep the real error.
        try:
          body = response.text[:200]
        except Exception:
          body = "(body unavailable)"
        print("Error: Non-JSON response (%s)" % response.status_code, file=self.vs)
        print(body, file=self.vs)
        response.close()
        pdeck.led(1, 0)
        if in_flight:
          self.prev_response_id = None  # outputs never delivered; chain is broken
        return final_text
      response.close()
      if not silent:
        _anim.stop()
      pdeck.led(1, 0)  # got the response

      if data.get("error"):
        err = data["error"]
        # OpenAI returns {"error": {"message": ...}}; some compatible providers
        # (e.g. xAI) return {"error": "message string"}.
        msg = err.get("message", "Unknown error") if isinstance(err, dict) else err
        print("API Error: %s" % msg, file=self.vs)
        if in_flight:
          self.prev_response_id = None  # outputs never delivered; chain is broken
        return final_text

      # A successful response confirms the prior batch of outputs was delivered.
      prev_id = data.get("id")
      in_flight = False

      fn_calls = []
      text_out = None
      for item in data.get("output", []):
        if not isinstance(item, dict):
          continue
        t = item.get("type")
        if t == "function_call":
          fn_calls.append(item)
        elif t == "message":
          content = item.get("content", [])
          # OpenAI returns content as a list of parts; some compatible providers
          # (e.g. xAI) may return it as a plain string.
          if isinstance(content, str):
            text_out = (text_out or "") + content
          else:
            for c in content:
              if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                text_out = (text_out or "") + c.get("text", "")
      if text_out:
        final_text = text_out

      if not fn_calls:
        self.prev_response_id = prev_id  # clean response: safe to chain next turn
        break
      if force_final:
        # Model ignored tool_choice="none" and still asked for calls. We won't
        # answer them now, so drop the chain to avoid leaving a dangling
        # function call that would break the next turn.
        self.prev_response_id = None
        print("\n[Reached tool-call limit; stopping here.]", file=self.vs)
        break

      # Execute the requested calls; their outputs become the next request's
      # input. With previous_response_id we only send the new items.
      next_input = []
      self.pending_image = None
      for fc in fn_calls:
        name = fc.get("name", "")
        call_id = fc.get("call_id", "")
        arguments = fc.get("arguments", "")
        print("\n%s[Call]%s %s" % (el.bold(), el.bold_off(), self._call_display(name, arguments)), file=self.vs)
        # Plan mode: the two effectful tools must be confirmed before they run.
        # A decline is reported back to the model as the tool output so it can
        # adjust instead of silently failing.
        if self.mode == 'plan' and name in ('command_with_return', 'write_file'):
          approved, feedback = self.confirm_tool(name, arguments)
          if not approved:
            result = "User declined to run %s (Plan mode)." % name
            if feedback:
              result += " User feedback: " + feedback
            print("%s[Skipped]%s %s" % (el.bold(), el.bold_off(), result[:200]), file=self.vs)
            next_input.append({
              "type": "function_call_output",
              "call_id": call_id,
              "output": result
            })
            continue
        try:
          result = self.execute_function_call(call_id, name, arguments)
        except BaseException as e:
          # Never let a tool (e.g. a module raising SystemExit) kill the session.
          result = "Error: %r" % (e,)
        print("%s[Result]%s %s" % (el.bold(), el.bold_off(), result[:200]), file=self.vs)
        next_input.append({
          "type": "function_call_output",
          "call_id": call_id,
          "output": result
        })

      # A capture_screen call leaves a base64 PNG to feed back as a user image.
      if self.pending_image is not None:
        next_input.append({
          "type": "message",
          "role": "user",
          "content": [{
            "type": "input_image",
            "image_url": "data:image/png;base64," + self.pending_image
          }]
        })
        self.pending_image = None

      # An ask_user call ends the turn: the next round is text-only so the
      # model states its question and control returns to the user.
      if self.user_question is not None:
        ask_stop = True
        self.user_question = None

      input_list = next_input
      in_flight = True  # these outputs are delivered on the next successful POST

    return final_text

  # --- plan-mode confirmation ------------------------------------------------

  def _call_display(self, name, arguments):
    """How a tool call is echoed on the '[Call]' line. For write_file we show
    only the path and size — the full file content would otherwise flood the
    screen; the change itself is shown afterwards as a diff (see _show_write)."""
    if name == "write_file":
      try:
        a = ujson.loads(arguments) if arguments else {}
      except:
        a = {}
      return "write_file  %s  (%d bytes)" % (a.get("path", ""), len(a.get("content", "")))
    return "%s %s" % (name, arguments)

  def _summarize_action(self, name, arguments):
    """One-line human-readable description of a pending tool call."""
    try:
      a = ujson.loads(arguments) if arguments else {}
    except:
      a = {}
    if name == "command_with_return":
      return "run command:  %s" % a.get("command", "")
    if name == "write_file":
      return "write %d byte(s) to  %s" % (len(a.get("content", "")), a.get("path", ""))
    return "%s %s" % (name, arguments)

  def confirm_tool(self, name, arguments):
    """Plan mode: show what the tool will do and ask the user to confirm.
    Returns (approved, feedback). Enter/y/yes approve; n/no decline silently;
    any other text declines and is sent back to the model as feedback."""
    vs = self.vs
    print("%s[Plan]%s %s" % (el.bold(), el.bold_off(), self._summarize_action(name, arguments)), file=vs)
    resp = read_line(vs, "Run? [Y]es / [n]o / type a reason to decline: ", [], lead="")
    r = (resp or "").strip()
    low = r.lower()
    if low in ("", "y", "yes"):
      return True, ""
    if low in ("n", "no"):
      return False, ""
    return False, r

  # --- tool implementations: the transport-independent ones come from
  # gpt_tools.ToolExecBase. Only _show_write (needs a screen) is overridden here.

  def _show_write(self, path, backup_path, content):
    """Display the effect of a write_file call. For an update (backup_path set),
    reuse the `diff` command to show old vs new; for a new file, print the
    content so the user can see what was created."""
    vs = self.vs
    if backup_path:
      try:
        import diff
        diff.main(vs, ['diff', backup_path, path])
        return
      except Exception as e:
        print("(diff unavailable: %s)" % e, file=vs)
    print("%s[New file]%s %s" % (el.bold(), el.bold_off(), path), file=vs)
    print(content, file=vs)


# ----------------------------------------------------------------------------
# Output (format / print / voice / save) - shared by single-shot and chat turns
# ----------------------------------------------------------------------------

def present_response(vs, gpt_obj, message, raw_response, args, margs, log_filename):
  if not raw_response:
    return

  no_format = margs['no_format'] if 'no_format' in margs else args.no_format
  response = raw_response if no_format else gpt.format(raw_response)
  pdeck.led(2, 130)  # result ready for the user to read
  print(response, file=vs)

  voice = margs['voice'] if 'voice' in margs else args.voice
  if voice:
    raw_response_sub = re.sub('\]\(ht.+?\)', ']', raw_response)
    gc.collect()
    if args.silent:
      print("TTS processing..", file=vs)
    else:
      _anim = gpt.ThinkingAnimation(vs, "TTS..")
    vtype = margs['voice_type'] if 'voice_type' in margs else args.voice_type
    res = gpt_obj.tts_stream(raw_response_sub, voice=vtype)
    if not args.silent:
      _anim.stop()
    print("TTS processing done", file=vs)
    if res and res.status_code == 200:
      stream = getattr(res, "raw", getattr(res, "s", res))
      try:
        gpt.play_audio_stream(vs, stream)
      except Exception as e:
        print("Streaming failed: %s." % e, file=vs)
      res.close()

  nosave = margs['nosave'] if 'nosave' in margs else args.nosave
  if not nosave:
    try:
      saved_filename = gpt.save_log(message, raw_response, log_filename)
      print(el.bold_off(), file=vs)
      print("Saved to %s and the filename copied to clipboard" % saved_filename, file=vs)
    except Exception as e:
      print("Failed to save log: %s" % e, file=vs)

  # In conversation mode the turn ends but the app keeps running, so the
  # "result ready" LED would stay lit until the next turn. Clear it ~2s after
  # the output instead. (Single-shot turns it off in run_turn's finally.)
  if args.chat:
    gpt_obj.schedule_led2_off(2)


# ----------------------------------------------------------------------------
# Role / instructions assembly
# ----------------------------------------------------------------------------

DEFAULT_ROLE = "You are a helpful assistant. Keep answers clear and concise."

CODER_ROLE = (
  "You are an expert MicroPython coding assistant for the Pocket Deck handheld "
  "device. You write, run, and debug code directly on the device. Favor small, "
  "correct, idiomatic MicroPython.\n"
  "INDENTATION RULE: exactly 2 spaces per indent level, never 4, never tabs. "
  "'2-space' means each nesting level ADDS 2 spaces: a line one level deep "
  "starts with 2 spaces, two levels deep with 4, three deep with 6. Correct:\n"
  "def main(vs, args):\n"
  "  for i in range(3):\n"
  "    if i > 1:\n"
  "      print(i, file=vs)\n"
  "To convert 4-space code to this style, halve the leading spaces of every "
  "line (8->4, 4->2). Do not judge a file by one nested line: check the FIRST "
  "indented line under a 'def' — it must start with exactly 2 spaces.\n"
  " Before you tell the user "
  "a task is done, run the code with your tools and confirm it works; if it "
  "errors, read the output, fix it, and re-run. Briefly explain what you changed."
  "Refer and follow /sd/Documents/pd/app_development.md as needed, the document has all available APIs in Pocket Deck")

TTS_NOTE = ("Your reply will be fed to a TTS engine; optimize for text-to-speech: "
            "keep it short and speakable.")

# Auto-attached in agent mode so the model knows Pocket Deck basics.
DEFAULT_AGENT_REFS = ["/sd/Documents/pd/README.md",
                      "/sd/Documents/pd/gpt_output_rules.md"]

# Named role presets so users don't have to write a persona from scratch.
# Maps name -> (role_text, wants_agent). wants_agent=True turns on the tools.
ROLE_PRESETS = {
  'plain':     (DEFAULT_ROLE, False),
  'assistant': (DEFAULT_ROLE, False),
  'coder':     (CODER_ROLE, True),
  'coding':    (CODER_ROLE, True),
  'code':      (CODER_ROLE, True),
}

# Users can drop their own role text in /sd/roles/<name>.txt and pass -r <name>.
ROLES_DIR = "/sd/roles"


def resolve_role(value):
  """Resolve a -r/role value to (role_text, wants_agent).
  value may be a preset name (plain, coder), a file path, a name under
  /sd/roles/<name>.txt, or literal role text. None -> default plain assistant.
  wants_agent is True/False for presets, or None when it should not force tools."""
  if not value:
    return DEFAULT_ROLE, False
  key = value.strip().lower()
  if key in ROLE_PRESETS:
    return ROLE_PRESETS[key]
  for path in (value, ROLES_DIR + "/" + value + ".txt"):
    if gpt.file_exists(path):
      try:
        with open(path, "r") as f:
          return f.read(), None
      except Exception:
        pass
  return value, None   # literal role text


def resolve_model(m):
  if m in ('m', 'medium'):
    return 'ngpt-5.4'
  if m in ('h', 'high'):
    return 'gpt-5.5'
  if m in ('f', 'fast'):
    return 'gpt-5.4-mini'
  return m


def assemble_instructions(role, tts, agent, app_list, my_screen=None):
  text = role if role else DEFAULT_ROLE
  if tts:
    text += "\n\n" + TTS_NOTE
  if agent:
    text += "\n\n" + build_agent_instructions(app_list, my_screen)
    # Fold in the self-evolving memory (learned in past sessions) in agent mode.
    text += ai_improve.memory_block()
  return text


def load_agent_references(vs, silent=False):
  """Read the default Pocket Deck reference files (README.md) for agent mode.
  On PC the /sd paths don't exist, so fall back to ~/.config/gpt/pd/ and the
  repo's docs/ so the model still gets device context. A missing reference is
  reported even in silent mode: the model silently knowing nothing about the
  device is a misconfiguration worth one line."""
  refs = []
  for path in DEFAULT_AGENT_REFS:
    candidates = [path]
    if _IS_PC:
      base = path.rsplit("/", 1)[-1]
      candidates.append(os.path.expanduser("~/.config/gpt/pd/") + base)
      candidates.append(os.path.dirname(os.path.abspath(__file__)) +
                        "/../docs/" + base)
    for cand in candidates:
      try:
        with open(cand, "r") as f:
          refs.append("---- " + path + " ----\n" + f.read())
        if not silent:
          print("Attached reference: %s" % cand, file=vs)
        break
      except Exception:
        pass
    else:
      print("Warning: agent reference %s not found - device context will be "
            "limited." % path, file=vs)
  return refs


# ----------------------------------------------------------------------------
# Interactive single-line editor (conversation mode)
# ----------------------------------------------------------------------------

def _wide(cp):
  # Mirror displayapi.c is_cjk_double_width: which codepoints the terminal draws
  # as 2 cells. Must match exactly so cursor moves line up with what's on screen.
  return ((0x1100 <= cp <= 0x115F) or (0x2329 <= cp <= 0x232A) or
          (0x2E80 <= cp <= 0xA4CF) or (0xAC00 <= cp <= 0xD7A3) or
          (0xF900 <= cp <= 0xFAFF) or (0xFE10 <= cp <= 0xFE19) or
          (0xFE30 <= cp <= 0xFE6F) or (0xFF01 <= cp <= 0xFF60) or
          (0xFFE0 <= cp <= 0xFFE6) or (0x16FE0 <= cp <= 0x18DFF) or
          (0x1B000 <= cp <= 0x1B2FF) or (0x1F000 <= cp <= 0x1FFFF) or
          (0x20000 <= cp <= 0x3FFFD))


def _vis_cells(s):
  """Width of `s` in terminal cells, counting CJK glyphs as 2 and skipping any
  CSI escape sequences (e.g. the SGR markers inside an IME pre-edit)."""
  total = 0
  i = 0
  n = len(s)
  while i < n:
    c = s[i]
    if c == '\x1b':                  # skip an escape sequence (no visible width)
      i += 1
      if i < n and s[i] == '[':
        i += 1
        while i < n and not ('\x40' <= s[i] <= '\x7e'):
          i += 1
      i += 1                         # consume the final byte (or the char after ESC)
      continue
    total += 2 if _wide(ord(c)) else 1
    i += 1
  return total


def _install_pc_skill_completer():
  """Emulator only: teach readline to Tab-complete /skill names. '/' is a default
  word delimiter, so `text` is the token typed after the slash. Only completes the
  command word of a slash line, matching the device editor."""
  try:
    import readline
  except ImportError:
    return
  def _completer(text, state):
    line = readline.get_line_buffer()
    if not line.startswith('/') or ' ' in line:
      return None
    matches = skill_tokens(text)
    return matches[state] if state < len(matches) else None
  readline.set_completer(_completer)
  readline.parse_and_bind('tab: complete')


def read_line(vs, prompt, history, on_shift_tab=None, lead="\n",
              allow_ime=False, ime_on=False, on_ime_toggle=None):
  """Read one line with editing. Arrows move the cursor; Up/Down browse history;
  Ctrl-A/E jump to start/end; Ctrl-K/U kill to end/start; Ctrl-B/F move; Backspace
  and Delete edit. Mirrors the device cmdshell key handling. Returns the line, or
  None if cancelled with Ctrl-C.

  prompt may be a string or a zero-arg callable returning the current prompt
  string, so a Shift-Tab handler can redraw it after changing the mode. `lead`
  is written once before the prompt (a newline by default). When on_shift_tab is
  given, Shift-Tab (ESC [ Z) calls it and the prompt line is redrawn.

  When allow_ime is set and jp_input is available, Alt+`/Alt+j toggle a Japanese
  romaji->kana->kanji IME (the same one pem uses). on_ime_toggle() flips the
  caller's persistent state and returns the new on/off bool; ime_on is the state
  at entry. While composing, keys feed the IME and a highlighted pre-edit is
  shown at the caret; the line caret does not move until text is committed."""
  if _IS_PC:
    # Cooked-mode stdin can't do the raw per-key editor, but input() already
    # gives line editing and history (via readline). Ctrl-C cancels the line
    # (return None, like the device); Ctrl-D quits the conversation.
    p = prompt() if callable(prompt) else prompt
    _install_pc_skill_completer()
    try:
      return input(p)
    except KeyboardInterrupt:
      vs.write("^C\r\n")
      return None
    except EOFError:
      return "/quit"
  def render_prompt():
    return prompt() if callable(prompt) else prompt
  buf = []
  cur = 0
  hcur = len(history)
  pending = None
  # Active IME session while composing Japanese (None when off/unavailable).
  im = jp_input.input_session() if (allow_ime and ime_on and jp_input) else None

  # anchor[0] = cells from the prompt start to the caret, as last rendered. Used
  # to step back to the prompt start before each repaint.
  anchor = [0]

  def redraw():
    # Repaint prompt + text from the prompt start. We step the cursor back by the
    # last anchor (CUB wraps up across rows in REPL/wrap mode) and erase to end of
    # screen, so a line that has WRAPPED onto several rows is fully cleared and the
    # prompt is not duplicated. Counts are in display cells (CJK = 2), so the caret
    # lands correctly with mixed ASCII/Japanese; only a 2-cell glyph landing exactly
    # on the right margin (which the terminal skips) can drift by a cell.
    if anchor[0] > 0:
      vs.write('\x1b[%dD' % anchor[0])
    vs.write('\x1b[0J')                                  # erase cursor -> end of screen
    p = render_prompt()
    head = ''.join(buf[:cur])
    pre = ''
    if im is not None and im.buffer:
      pre = el.set_font_color(4) + im.d_buffer + el.set_font_color(0)
    tail = ''.join(buf[cur:])
    vs.write(p + head + pre + tail)
    back = _vis_cells(tail)
    if back > 0:
      vs.write('\x1b[%dD' % back)
    anchor[0] = _vis_cells(p) + _vis_cells(head) + _vis_cells(pre)

  if lead:
    vs.write(lead)
  p0 = render_prompt()
  vs.write(p0)
  anchor[0] = _vis_cells(p0)

  while True:
    ch = vs.read(1)
    if not ch:
      continue
    o = ord(ch)

    # Route keys to the IME while it is on, except control chars / space when
    # nothing is being composed (those stay normal editor keys: Enter submits,
    # Backspace edits committed text, a leading space is literal). Escape
    # sequences (arrows, Alt-toggles) are handled in the ESC branch below.
    if (im is not None and ch != '\x1b'
        and not (not im.buffer and (o <= 0x20 or o == 0x7f))):
      result = im.feed_key(ch.encode('utf-8'))
      if result:
        for c in result:
          buf.insert(cur, c)
          cur += 1
      redraw()
      continue

    if ch == '\x1b':                               # escape sequence
      c1 = vs.read(1)
      if allow_ime and on_ime_toggle and c1 in ('`', 'j', '~'):  # Alt+`/j: toggle IME
        if on_ime_toggle():
          im = jp_input.input_session() if jp_input else None
        else:
          im = None                                # discards any active pre-edit
        redraw()
        continue
      if c1 not in ('[', 'O'):
        continue
      c2 = vs.read(1)
      if im is not None and im.buffer and c2 in ('A', 'B', 'C', 'D'):
        # While composing, arrows drive henkan candidate selection, not the line.
        im.feed_key(('\x1b[' + c2).encode('utf-8'))
        redraw()
        continue
      # All edits below mutate buf/cur then repaint via redraw(), which is
      # column-aware — essential because committed Japanese glyphs are 2 cells
      # wide, so character-count cursor moves (or a single '\b') would desync.
      if c2 and '0' <= c2 <= '9':                  # extended (\x1b[3~ etc.)
        vs.read(1)                                 # consume trailing '~'
        if c2 == '3' and cur < len(buf):           # Delete (forward)
          del buf[cur]; redraw()
        elif c2 in ('1', '7') and cur > 0:         # Home
          cur = 0; redraw()
        elif c2 in ('4', '8') and cur < len(buf):  # End
          cur = len(buf); redraw()
        continue
      if c2 == 'A':                                # Up: history back
        if history and hcur > 0:
          if hcur == len(history):
            pending = ''.join(buf)
          hcur -= 1
          buf = list(history[hcur]); cur = len(buf); redraw()
      elif c2 == 'B':                              # Down: history forward
        if hcur < len(history):
          hcur += 1
          buf = list(pending or '') if hcur == len(history) else list(history[hcur])
          cur = len(buf); redraw()
      elif c2 == 'C':                              # Right
        if cur < len(buf):
          cur += 1; redraw()
      elif c2 == 'D':                              # Left
        if cur > 0:
          cur -= 1; redraw()
      elif c2 == 'H' and cur > 0:                  # Home
        cur = 0; redraw()
      elif c2 == 'F' and cur < len(buf):           # End
        cur = len(buf); redraw()
      elif c2 == 'Z' and on_shift_tab:             # Shift-Tab: toggle mode
        on_shift_tab(); redraw()
      continue

    if ch == '\r' or ch == '\n':
      if cur < len(buf):
        cur = len(buf); redraw()   # park caret past all text so the newline lands below it
      vs.write('\r\n')
      return ''.join(buf)
    elif o in (8, 127):                            # Backspace
      if cur > 0:
        cur -= 1; del buf[cur]; redraw()
    elif o == 1:                                   # Ctrl-A: start
      if cur > 0:
        cur = 0; redraw()
    elif o == 5:                                   # Ctrl-E: end
      if cur < len(buf):
        cur = len(buf); redraw()
    elif o == 2:                                   # Ctrl-B: left
      if cur > 0:
        cur -= 1; redraw()
    elif o == 6:                                   # Ctrl-F: right
      if cur < len(buf):
        cur += 1; redraw()
    elif o == 11:                                  # Ctrl-K: kill to end
      if cur < len(buf):
        del buf[cur:]; redraw()
    elif o == 21:                                  # Ctrl-U: kill to start
      if cur > 0:
        del buf[:cur]; cur = 0; redraw()
    elif o == 4:                                   # Ctrl-D: delete forward
      if cur < len(buf):
        del buf[cur]; redraw()
    elif o == 3:                                   # Ctrl-C: cancel line
      vs.write('^C\r\n')
      return None
    elif o == 9:                                   # Tab: complete a /skill name
      # Only while typing the command word of a slash line ("/foo", no space yet)
      # and with the caret at the end, so Tab is inert everywhere else.
      s = ''.join(buf)
      if s.startswith('/') and ' ' not in s and cur == len(buf):
        prefix = s[1:]
        toks = skill_tokens(prefix)
        if len(toks) == 1:                         # unique: fill it in + a space
          buf = list('/' + toks[0] + ' '); cur = len(buf); redraw()
        elif len(toks) > 1:
          cp = toks[0]                             # extend to the common prefix
          for t in toks[1:]:
            while not t.startswith(cp):
              cp = cp[:-1]
          if len(cp) > len(prefix):
            buf = list('/' + cp); cur = len(buf); redraw()
          else:                                    # ambiguous: list the candidates
            vs.write('\r\n' + '  '.join(toks) + '\r\n')
            anchor[0] = 0; redraw()
    elif o >= 0x20 and ch != '\x7f':               # printable: insert
      buf.insert(cur, ch); cur += 1; redraw()


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main(vs, args_in):
  parser = argparse.ArgumentParser(description='ChatGPT query with function calling')
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
  parser.add_argument('-m', '--model', action='store', default=None, help='Model to use: a name from /config/gpt.json, a shortcut (f/m/h), or a raw model id. Default: the registry default.')
  parser.add_argument('--base-url', action='store', default=None, help='Override the endpoint base URL for this run')
  parser.add_argument('-e', '--effort', action='store', default='medium', help='Reasoning effort (low, medium, high) - Responses models only')
  parser.add_argument('-v', '--voice', action='store_true', help='Use voice mode (STT and TTS)')
  parser.add_argument('-vt', '--voice-type', action='store', default=None, help='Voice type for TTS (overrides the audio backend voice; default: its configured voice, else coral)')
  parser.add_argument('-r', '--role', action='store', default=None, help="Role preset 'assistant' or 'coder', a /sd/roles/<name>.txt file, or literal text. Default: assistant.")
  parser.add_argument('--log-file', action='store', default=None, help='Internal: reuse the same log filename across iterations')
  parser.add_argument('--resume', action='store_true', help='Save this turn\'s response id to the session list so a later call can continue the conversation')
  parser.add_argument('--resume-id', '--resume_id', dest='resume_id', action='store', default=None, help="Continue a prior conversation: a response id, or 'last' for the most recent saved session")
  parser.add_argument('-T', '--training', action='store_true', help='Dump each turn (system/user/tool-calls/results/answer + tool schema) as JSONL to /sd/training_data for fine-tuning. Attachments are excluded. Chat Completions models only.')
  parser.add_argument('content', nargs='*', help='Content to ask')
  parser.add_argument('-q', nargs='+', help='Content to ask, use this when you want to specify content explicitly.')

  args = parser.parse_args(args_in[1:])

  if not auto_connect.check(vs, silent=True):
    print("Network is not available", file=vs)
    return

  # Model registry: -m selects an entry (name/shortcut/raw id); the entry picks
  # the API (Responses here vs Chat Completions in gpt_c), base_url and model id.
  registry = load_registry(None if args.silent else vs)
  entry = resolve_entry(registry, args.model)
  if args.base_url:
    entry = dict(entry); entry['base_url'] = args.base_url
  gpt_obj = init_client(entry, vs, args.plan, registry)
  if gpt_obj is None:
    return

  # Training-data capture: one JSONL file per run, carried on the client so it
  # survives model/endpoint switches within a conversation.
  training_file = make_training_filename() if args.training else None
  gpt_obj.training_file = training_file
  if training_file and not args.silent:
    print("Training capture ON -> %s" % training_file, file=vs)
    if gpt_obj.API != 'chat':
      print("  note: capture is Chat Completions only; the current model uses "
            "the %s API, so nothing will be written. Switch to a chat model "
            "(/model or -m)." % gpt_obj.API, file=vs)

  message = ""
  tts_response = False

  if args.voice and not args.q and not args.content:
    rec_file = "/sd/work/voice_rec.wav"
    gpt.record_audio(vs, rec_file)
    print("Transcribing...", file=vs)
    message = gpt_obj.stt(rec_file)
    if not message:
      print("Failed to transcribe audio", file=vs)
      return
    print("You (STT): %s" % message, file=vs)
    tts_response = True
  elif not args.content and not args.q:
    if not args.chat:
      message = gpt.get_message(vs)
  else:
    if args.content:
      message += ' '.join(args.content)
    if args.q:
      if len(args.q) == 1 and gpt.file_exists(args.q[0]):
        with open(args.q[0], "r") as f:
          message = f.read()
      else:
        message += ' '.join(args.q)

  if len(message) == 0 and not args.chat:
    return

  references = []
  images = []

  if message:
    message, _, margs = gpt.parse_inline_directives(message, references, images, args, vs)
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

  # An inline [[-m ...]] directive can pick a different registry entry; if it
  # changes the API/endpoint, rebuild the client before the first turn.
  if 'model' in margs:
    new_entry = resolve_entry(registry, margs['model'])
    if args.base_url:
      new_entry = dict(new_entry); new_entry['base_url'] = args.base_url
    if (new_entry['api'] != gpt_obj.API or
        new_entry['base_url'].rstrip('/') != gpt_obj.base_url.rstrip('/')):
      rebuilt = init_client(new_entry, vs, args.plan, registry)
      if rebuilt is None:
        return
      rebuilt.jp_font_loaded = gpt_obj.jp_font_loaded
      rebuilt.training_file = training_file
      gpt_obj = rebuilt
    entry = new_entry
  model = entry['model']

  # Conversation continuity across separate gpt invocations: --resume-id seeds
  # the prior context, --resume persists it afterward. 'last' resolves to the
  # most recent saved session. Both clients implement resume_from/persist_session.
  resumed_from = None
  if args.resume_id:
    resumed_from = gpt_obj.resume_from(args.resume_id, vs, args.silent)

  # Reasoning effort applies to Responses models only; a registry entry may set
  # a default that a command-line -e (or inline directive) still overrides.
  effort = margs['effort'] if 'effort' in margs else args.effort
  if 'effort' not in margs and args.effort == 'medium' and entry.get('effort'):
    effort = entry['effort']
  if effort not in ('low', 'medium', 'high'):
    print("Invalid effort: %s. Using medium." % effort, file=vs)
    effort = 'medium'

  # Role / persona. Default is a plain assistant; -r picks a preset (plain,
  # coder), a /sd/roles/<name>.txt file, or literal text. The coder preset also
  # turns the tools on.
  role, role_wants_agent = resolve_role(args.role)
  agent = args.agent or (role_wants_agent is True)

  # Agent tools drive the device (run modules, screens, apps) and don't exist on
  # a PC, so plain chat is the only supported PC mode.
  if _IS_PC and agent:
    print("Agent mode is unavailable on PC; continuing as plain chat.", file=vs)
    agent = False

  # The assistant's own screen, so we can tell the agent to switch the foreground back
  # here when it wants the user to read its answer.
  try:
    my_screen = pdeck.get_screen_num()
  except Exception:
    my_screen = None

  # Agent tools + auto-attached Pocket Deck references.
  app_list = []
  if agent:
    app_list = load_app_list()
    gpt_obj.app_list = app_list
    if not args.silent:
      print("Agent mode: %d app(s)." % len(app_list), file=vs)
    references += load_agent_references(vs, silent=args.silent)

  log_filename = args.log_file or gpt.make_log_filename()
  jp_suffix = " and answer in Japanese" if jp else ""

  # Mutable per-conversation config so slash commands can change it on the fly.
  ctx = {
    'model': model,
    'entry': entry,
    'effort': effort,
    'role': role,
    'tts': tts_response,
    'agent': agent,
    'app_list': app_list,
    'instructions': assemble_instructions(role, tts_response, agent, app_list, my_screen),
    'tools': gpt_obj.build_tools_for(app_list, agent),
  }

  def run_turn(turn_message, refs, imgs):
    gpt_obj.model = ctx['model']  # so update_memory / self-improve can reach the active model/endpoint
    ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
    time_str = "[User current time: %04d-%02d-%02d %02d:%02d]\n" % (ctime[0], ctime[1], ctime[2], ctime[3], ctime[4])
    full = time_str + turn_message + jp_suffix
    raw = gpt_obj.ask_agent(full, refs, imgs, ctx['model'], ctx['instructions'],
                            ctx['effort'], ctx['tools'], silent=args.silent)
    present_response(vs, gpt_obj, full, raw, args, margs, log_filename)
    return raw

  if not args.chat:
    try:
      run_turn(message, references, images)
    finally:
      pdeck.led(1, 0)
      pdeck.led(2, 0)
    # Persist the conversation so a later --resume-id can continue it. Each
    # client saves what it needs (a response id for Responses, the messages list
    # for Chat Completions).
    if args.resume:
      gpt_obj.persist_session(message, resumed_from)
    return

  # ---- Conversation mode ----
  history = []
  pending_refs = []   # files queued via /file for the next message
  # Auto-compaction (Chat Completions clients only): 'every' = compact after
  # this many turns (0 = off); 'since' = turns completed since last compaction.
  compact_state = {'every': 0, 'since': 0}
  # Auto-improve: run /improve every this many completed turns (0 = off) to
  # distill the session into long-term memory, mirroring gpt_rt's periodic run.
  improve_state = {'every': 8, 'since': 0}

  def refresh():
    ctx['instructions'] = assemble_instructions(ctx['role'], ctx['tts'], ctx['agent'], ctx['app_list'], my_screen)
    ctx['tools'] = gpt_obj.build_tools_for(ctx['app_list'], ctx['agent'])

  def switch_model(name):
    """Switch to registry entry `name`. If the API or endpoint changes, rebuild
    the client (which resets the conversation context); otherwise just retarget
    the model id on the current client."""
    nonlocal gpt_obj
    new_entry = resolve_entry(registry, name)
    same = (new_entry['api'] == gpt_obj.API and
            new_entry['base_url'].rstrip('/') == gpt_obj.base_url.rstrip('/'))
    if same:
      ctx['model'] = new_entry['model']
      ctx['entry'] = new_entry
      print("Model: %s (%s API)." % (new_entry['name'], new_entry['api']), file=vs)
      return
    new_obj = init_client(new_entry, vs, gpt_obj.mode == 'plan', registry)
    if new_obj is None:
      print("Could not switch to %s (no API key for %s)." %
            (new_entry['name'], new_entry['base_url']), file=vs)
      return
    new_obj.jp_ime = gpt_obj.jp_ime
    new_obj.jp_font_loaded = gpt_obj.jp_font_loaded
    new_obj.training_file = training_file
    new_obj.app_list = ctx['app_list']
    gpt_obj.led2_gen += 1        # cancel any pending LED timer on the old client
    gpt_obj = new_obj
    ctx['model'] = new_entry['model']
    ctx['entry'] = new_entry
    compact_state['since'] = 0
    improve_state['since'] = 0
    refresh()
    print("Switched to %s (%s API); context reset." %
          (new_entry['name'], new_entry['api']), file=vs)

  def do_compact(auto=False):
    """Summarize and shrink the conversation (Chat Completions only)."""
    if not gpt_obj.CAN_COMPACT:
      if not auto:
        print("Compaction isn't available for this model.", file=vs)
      return False
    before = len(gpt_obj.messages)
    summary = gpt_obj.compact(ctx['model'], silent=args.silent)
    if summary is None:
      if not auto:
        print("Nothing to compact yet (conversation too short)." if before <= 3
              else "Compaction failed; context unchanged.", file=vs)
      return False
    compact_state['since'] = 0
    print("%sContext compacted: %d -> %d messages." %
          ("[Auto-compact] " if auto else "", before, len(gpt_obj.messages)), file=vs)
    if not auto:
      print(gpt.format(summary), file=vs)
    return True

  def run_improve(reason=None, auto=False):
    """Distill the session into long-term memory (the /improve action). Auto runs
    stay quiet unless they actually update the memory; manual runs are verbose.
    On success the instructions are refreshed so the freshened memory applies on
    the next turn (memory is injected in agent mode)."""
    improve_state['since'] = 0
    gpt_obj.model = ctx['model']  # route self-improve to the active model/endpoint
    if not auto:
      print("[ Improving — distilling lessons into long-term memory... ]", file=vs)
    try:
      ok, msg = gpt_obj.run_self_improve(reason)
    except Exception as e:
      ok, msg = False, str(e)
    if ok:
      refresh()
    if auto:
      if ok:
        print("[ Auto-improve: %s ]" % msg, file=vs)
    else:
      print(("Memory updated: %s" % msg) if ok else ("Improve skipped: %s" % msg), file=vs)
      if ok and not ctx['agent']:
        print("(Tip: memory is loaded into the prompt in agent mode; enable with /tools.)", file=vs)
    return ok

  def mode_prompt():
    # Replaces the old "You:" prompt; shows the current execution mode in bold,
    # plus a kana marker while the Japanese IME is active.
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
    lines = [
      "Commands:",
      "  /help              this help",
      "  /quit  /exit       leave conversation",
      "  /clear /reset      start fresh (clear conversation context)",
      "  /model [name]      show or set model (a name from /config/gpt.json, m/h/f, or id)",
      "  /models            list configured models",
    ]
    if gpt_obj.USE_EFFORT:
      lines.append("  /effort [level]    show or set reasoning effort (low|medium|high)")
    lines.append("  /role [name|text]  show/set role: presets 'assistant' or 'coder' (resets context)")
    lines.append("  /tools             toggle function-calling tools (agent) on/off")
    lines.append("  /mode [auto|plan]  show/set execution mode (no arg toggles); also /auto, /plan")
    lines.append("  /file <path>       attach a file as reference for the next message")
    lines.append("  /history           show recent input history")
    if gpt_obj.CAN_COMPACT:
      lines.append("  /compact           summarize & shrink the conversation context now")
      lines.append("  /auto-compact [n]  auto-compact every n turns (no arg shows; 'off' disables)")
    lines.append("  /skills            list available skills (user + system)")
    lines.append("  /<skill-name>      run a skill by name (e.g. /morning_ritual; Tab completes)")
    lines.append("  /improve           learn from this session & update long-term memory")
    lines.append("  /auto-improve [n]  auto-run /improve every n turns (no arg shows; 'off' disables)")
    lines.append("Plan mode confirms each command_with_return / write_file before it runs.")
    lines.append("Japanese input: Alt+` or Alt+j toggles the kana IME (best with -j font).")
    lines.append("Editing: arrows move, Up/Down history, Ctrl-A/E start/end, Ctrl-K/U kill, Ctrl-C cancel, Shift-Tab toggles mode.")
    lines.append("Tab on a /<skill> line completes the name (or lists matches).")
    print("\n".join(lines), file=vs)

  def show_models():
    print("Configured models (%s = current):" % ctx['entry']['name'], file=vs)
    for m in registry.get('models', []):
      e = _normalize_entry(m)
      mark = "* " if e['name'] == ctx['entry']['name'] else "  "
      loc = "" if e['base_url'].rstrip('/') == OPENAI_BASE else "  @ " + e['base_url']
      print("  %s%-16s %-9s %s%s" % (mark, e['name'], e['api'], e['model'], loc), file=vs)

  def handle_command(line):
    """Return 'quit' to leave, 'ok' when handled, 'unknown' if unrecognized."""
    parts = line[1:].split()
    if not parts:
      return 'ok'
    cmd = parts[0].lower()
    arg = line[1 + len(parts[0]):].strip()
    if cmd in ('quit', 'exit', 'q'):
      return 'quit'
    elif cmd in ('help', 'h', '?'):
      show_help()
    elif cmd in ('clear', 'reset', 'new'):
      gpt_obj.reset_context()
      compact_state['since'] = 0
      improve_state['since'] = 0
      print("New conversation (context cleared).", file=vs)
    elif cmd == 'model':
      if arg:
        switch_model(arg)
      else:
        print("Model: %s (%s)" % (ctx['entry']['name'], ctx['entry']['api']), file=vs)
    elif cmd in ('models', 'ls'):
      show_models()
    elif cmd == 'effort':
      if not gpt_obj.USE_EFFORT:
        print("Reasoning effort isn't used by this model.", file=vs)
      elif arg in ('low', 'medium', 'high'):
        ctx['effort'] = arg
        print("Effort: %s" % ctx['effort'], file=vs)
      elif arg:
        print("Effort must be low|medium|high.", file=vs)
      else:
        print("Effort: %s" % ctx['effort'], file=vs)
    elif cmd == 'role':
      if arg:
        rtext, rwants = resolve_role(arg)
        ctx['role'] = rtext
        if rwants and not ctx['agent']:
          ctx['agent'] = True
          if not ctx['app_list']:
            ctx['app_list'] = load_app_list()
            gpt_obj.app_list = ctx['app_list']
        refresh()
        gpt_obj.reset_context()
        print("Role set to '%s'%s (context reset)." %
              (arg, " (tools on)" if ctx['agent'] else ""), file=vs)
      else:
        print("Role presets: assistant, coder. Current role:\n%s" %
              (ctx['role'] or DEFAULT_ROLE), file=vs)
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
        ctx['app_list'] = load_app_list()
        gpt_obj.app_list = ctx['app_list']
      refresh()
      print("Tools %s." % ("on" if ctx['agent'] else "off"), file=vs)
    elif cmd == 'file':
      if not arg:
        print("Usage: /file <path>", file=vs)
      elif gpt.file_exists(arg):
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
    elif cmd == 'compact':
      do_compact()
    elif cmd in ('auto-compact', 'autocompact'):
      if not gpt_obj.CAN_COMPACT:
        print("Auto-compact isn't available for this model.", file=vs)
      elif arg.lower() in ('off', '0', 'none'):
        compact_state['every'] = 0
        print("Auto-compact off.", file=vs)
      elif arg:
        try:
          n = int(arg)
        except:
          n = -1
        if n < 1:
          print("Usage: /auto-compact <num_iterations>  (or 'off')", file=vs)
        else:
          compact_state['every'] = n
          compact_state['since'] = 0
          print("Auto-compact every %d turn(s)." % n, file=vs)
      elif compact_state['every']:
        print("Auto-compact: every %d turn(s) (%d since last)." %
              (compact_state['every'], compact_state['since']), file=vs)
      else:
        print("Auto-compact: off. Use /auto-compact <num_iterations>.", file=vs)
    elif cmd == 'skills':
      sk = list_skills()
      if not sk:
        print("No skills found in %s." % " or ".join(SKILL_DIRS), file=vs)
      else:
        print("Skills (type /<name> to run):", file=vs)
        for token, path, source in sk:
          print("  /%-22s (%s)" % (token, source), file=vs)
    elif cmd in ('improve', 'learn'):
      run_improve(arg or None)
    elif cmd in ('auto-improve', 'autoimprove'):
      if arg.lower() in ('off', '0', 'none'):
        improve_state['every'] = 0
        print("Auto-improve off.", file=vs)
      elif arg:
        try:
          n = int(arg)
        except:
          n = -1
        if n < 1:
          print("Usage: /auto-improve <num_turns>  (or 'off')", file=vs)
        else:
          improve_state['every'] = n
          improve_state['since'] = 0
          print("Auto-improve every %d turn(s)." % n, file=vs)
      elif improve_state['every']:
        print("Auto-improve: every %d turn(s) (%d since last)." %
              (improve_state['every'], improve_state['since']), file=vs)
      else:
        print("Auto-improve: off. Use /auto-improve <num_turns>.", file=vs)
    else:
      return 'unknown'          # maybe a /<skill-name> — resolved by the caller
    return 'ok'

  print("Conversation mode. /help for commands, /quit to exit.", file=vs)
  print("Model: %s (%s). Mode: %s (Shift-Tab or /mode to switch)." %
        (ctx['entry']['name'], ctx['entry']['api'], gpt_obj.mode), file=vs)
  if jp_input is not None:
    print("Japanese: Alt+` or Alt+j toggles kana input%s." %
          ("" if jp else " (use -j for the unicode font)"), file=vs)

  sent_initial = False
  first = True
  while True:
    if first and message:
      line = message.strip()
    else:
      line = read_line(vs, mode_prompt, history, on_shift_tab=toggle_mode,
                       allow_ime=(jp_input is not None), ime_on=gpt_obj.jp_ime,
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
      status = handle_command(line)
      if status == 'quit':
        print("Bye.", file=vs)
        break
      if status != 'unknown':
        continue
      # Not a built-in command — try to run it as a skill: /<skill-name> [args].
      word = line[1:].split()[0]
      arg = line[1 + len(word):].strip()
      hit = find_skill(word)
      if hit is None:
        print("Unknown command: /%s  (try /help or /skills)" % word, file=vs)
        continue
      path, content = hit
      print("Running skill: %s" % path, file=vs)
      line = compose_skill_message(path, content, arg)
      # fall through: run the skill as a normal user turn

    turn_refs = list(pending_refs)
    pending_refs[:] = []
    turn_imgs = []
    if not sent_initial:
      turn_refs = references + turn_refs
      turn_imgs = images
      sent_initial = True
    # A turn must never drop the user out of the conversation: contain any
    # failure (network error, etc.) and keep prompting. (Each client only commits
    # its context on a clean response, so a thrown turn leaves the prior context
    # intact and the next prompt can continue.)
    try:
      run_turn(line, turn_refs, turn_imgs)
      # Count completed turns; auto-compact once the threshold is reached.
      if gpt_obj.CAN_COMPACT and compact_state['every']:
        compact_state['since'] += 1
        if compact_state['since'] >= compact_state['every']:
          do_compact(auto=True)
      # Periodically distill the session into long-term memory (like gpt_rt).
      if improve_state['every']:
        improve_state['since'] += 1
        if improve_state['since'] >= improve_state['every']:
          run_improve(reason="periodic auto-improve", auto=True)
    except BaseException as e:
      print("\n[Turn failed; you can keep going] %r" % (e,), file=vs)
      print_exc(e, vs)

  pdeck.led(1, 0)  # leaving conversation: clear status LEDs
  gpt_obj.led2_gen += 1  # invalidate any pending auto-off timer
  pdeck.led(2, 0)


# On a PC the device shell isn't there to call main(vs, args); provide an entry
# point so `python3 gpt.py ...` works. (On the device gpt is imported, not run.)
if __name__ == '__main__':
  main(pc_compat.PCStream(), ['gpt'] + sys.argv[1:])
