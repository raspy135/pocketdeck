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
  _MAX = 300000

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
    "BE TOKEN-EFFICIENT WITH TOOL CALLS. Each command_with_return call is "
    "expensive, so make every one count: think before you call, get the command "
    "syntax right the first time, and prefer one precise command over several "
    "exploratory ones. Pocket Deck is not Linux. Read README.md and use only the options "
    "that is mentioned in the manual."
    "cat, grep, ls, head, tail are great tools to reduce funciton calls. See README.md for full command list.\n"
    "You can see and drive other apps running on the device. Use list_running_apps "
    "to see which app is on which screen. Use switch_screen to bring a screen to "
    "the foreground. IMPORTANT: screen numbers in these tools are 0-based and match "
    "what list_running_apps reports (screen 0 is the Python REPL), but the device's "
    "GUI shows them 1-based, so the screen the user calls '2' is screen 1 here — "
    "always pass the 0-based number from list_running_apps, not the GUI number. "
    "Use capture_screen to take a screenshot of a screen and look "
    "at it (it is returned to you as an image); it takes some time, so do not "
    "request screenshots at a high rate. Use send_keys to type into the app in the "
    "foreground; set enter=true to press Enter, and use escape sequences for "
    "special keys (Up=\\x1b[A, Down=\\x1b[B, Right=\\x1b[C, Left=\\x1b[D, Esc=\\x1b, "
    "Backspace=\\x08, Ctrl-X=\\x18). After acting, capture_screen again to confirm "
    "the result before continuing.\n"
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
             "to open a specific file. Available apps:\n")
    for item in app_list:
      if isinstance(item, list) and len(item) == 2:
        name = item[0]
        info = item[1]
        desc = info.get('description', '') if isinstance(info, dict) else ''
        text += "  - %s: %s\n" % (name, desc)
  return text


def build_tools(app_list, agent=False, web_search=True):
  """Tool schemas for the Responses API (flat function format). Function tools
  are only included in agent mode; plain mode keeps just web_search."""
  tools = []
  if web_search:
    tools.append({"type": "web_search"})
  if not agent:
    return tools

  tools.append({
    "type": "function",
    "name": "command_with_return",
    "description": "Run a device command (or any installed module) and return its captured output. This is your primary tool for TESTING AND VERIFYING CODE: after you write a script with write_file, run it here by name and read the output to confirm it works, see errors, and iterate. A runnable script/app is a module exposing main(vs, args); invoke it by its name plus arguments, e.g. 'temp_foo arg1' for /sd/py/temp_foo.py, or any existing app/command. IMPORTANT: if you EDIT a script and run it again, prefix the command with 'r ' to reload it (e.g. 'r temp_foo arg1') — without 'r' the previous, cached version runs instead of your new code. Built-in commands include: ls (glob patterns like 'word*'; 'ls -r path' lists recursively), cat (read file), head, tail, rm, mv, cp, mkdir, rmdir, grep (search in files), ping, dic (dictionary lookup), curl (fetch web content), and 'analog_clock_set_timer <minutes>'. grep behaves like Linux grep: the PATTERN is a regex by default (no -e needed), with -i ignore-case, -n line numbers, -r recursive, -l filenames only, -v invert, -F literal/fixed-string match, and --include .py,.md to filter by extension; e.g. 'grep -rn \"def .*main\" /sd/py'. No shell pipes ('|') — this is not Linux, so do NOT chain commands or use redirects, backticks, &&, or subshells; run one command at a time. See README.md for command usage.",
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
  })

  tools.append({
    "type": "function",
    "name": "write_file",
    "description": "Write text content to a file on the device filesystem. Creates or overwrites the file. The original file will be backed up under /sd/backup, so you don't need to take a backup file",
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
  })

  if app_list:
    tools.append({
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
    })

  tools.append({
    "type": "function",
    "name": "list_running_apps",
    "description": "List the apps currently running and which screen number each is on. Use this before switching, capturing, or driving an app.",
    "parameters": {"type": "object", "properties": {}, "required": []}
  })

  tools.append({
    "type": "function",
    "name": "switch_screen",
    "description": "Bring a screen to the foreground so it becomes active. Required before capturing or sending keys to that screen. Note the screen number in the function is 0-based, however, screen number shown in GUI is 1-based. So if the user wants to switch to screen 2, send 1 as an argument.",
    "parameters": {
      "type": "object",
      "properties": {
        "screen": {"type": "integer", "description": "Screen number to switch to (0-9)"}
      },
      "required": ["screen"]
    }
  })

  tools.append({
    "type": "function",
    "name": "capture_screen",
    "description": "Take a screenshot of a screen and return it to you as an image so you can read what is on it. If screen is given, switches to it first.",
    "parameters": {
      "type": "object",
      "properties": {
        "screen": {"type": "integer", "description": "Optional screen number to switch to and capture. If omitted, captures the current foreground screen."}
      },
      "required": []
    }
  })

  tools.append({
    "type": "function",
    "name": "launch_command_shell",
    "description": "Launch a new command-line shell on a given screen so you can drive it with switch_screen / send_keys / capture_screen (e.g. to run interactive commands that command_with_return cannot). The screen number is 0-based and matches list_running_apps (screen 0 is the Python REPL). Valid screens are 2-9; the screen must be free (nothing already running there). Returns whether the shell was started.",
    "parameters": {
      "type": "object",
      "properties": {
        "screen": {"type": "integer", "description": "0-based screen number to start the shell on (2-9, must be free)"}
      },
      "required": ["screen"]
    }
  })

  tools.append({
    "type": "function",
    "name": "send_keys",
    "description": "Type text / keystrokes into the foreground app. Use escape sequences for special keys (arrows \\x1b[A/B/C/D, Esc \\x1b, Backspace \\x08, Ctrl-X \\x18).",
    "parameters": {
      "type": "object",
      "properties": {
        "text": {"type": "string", "description": "Characters to inject as keyboard input"},
        "screen": {"type": "integer", "description": "Optional screen number to switch to before typing (input only reaches the foreground app)"},
        "enter": {"type": "boolean", "description": "If true, press Enter (carriage return) after the text"}
      },
      "required": ["text"]
    }
  })

  return tools


# ----------------------------------------------------------------------------
# Agent client
# ----------------------------------------------------------------------------

class chatgpt_agent(gpt.chatgpt_util):
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
    for i in range(max_iters + 1):
      force_final = (i == max_iters)
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
        if in_flight:
          self.prev_response_id = None  # outputs never delivered; chain is broken
        return final_text
      response.close()
      if not silent:
        _anim.stop()
      pdeck.led(1, 0)  # got the response

      if data.get("error"):
        print("API Error: %s" % data["error"].get("message", "Unknown error"), file=self.vs)
        if in_flight:
          self.prev_response_id = None  # outputs never delivered; chain is broken
        return final_text

      # A successful response confirms the prior batch of outputs was delivered.
      prev_id = data.get("id")
      in_flight = False

      fn_calls = []
      text_out = None
      for item in data.get("output", []):
        t = item.get("type")
        if t == "function_call":
          fn_calls.append(item)
        elif t == "message":
          for c in item.get("content", []):
            if c.get("type") == "output_text" or c.get("type") == "text":
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

  # --- tool implementations (ported from gpt_rt.py, screen/file only) --------

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
    if name == "launch_command_shell":
      return self.execute_launch_command_shell(arguments)
    if name == "launch_app":
      return self.execute_launch_app(arguments)
    return "Unknown function: %s" % name

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
    # 'r' prefix forces a fresh re-import of the module, exactly like the device
    # shell (pdeck_utils.process_prefix). Essential after editing a script you
    # already ran, since MicroPython otherwise reuses the cached module.
    if parts[0] == 'r' and len(parts) > 1:
      parts.pop(0)
      if parts[0] in sys.modules:
        del sys.modules[parts[0]]
    modname = parts[0]
    # Refuse to launch the assistant from inside itself: a nested agent session
    # would re-enter the whole loop (networking + JSON) on the already-deep
    # 8KB command stack and overflow.
    if modname in ('gpt', 'gpt_l', 'gptn'):
      return "Error: refusing to run '%s' recursively from inside the assistant." % modname
    cap = CaptureStream()
    try:
      exec("import %s" % modname, {})
      sys.modules[modname].main(cap, parts)
    except BaseException as e:
      # Catch BaseException, not just Exception: a module that calls sys.exit()/
      # quit() (SystemExit) or raises KeyboardInterrupt would otherwise escape
      # and kill gptn. Capture the full traceback so the model can debug it.
      cap.write("\nError running '%s':\n" % modname)
      sys.print_exception(e, cap)
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
      backup_path = None
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
        backup_path = "/sd/backup/" + backup_name
        with open(backup_path, "w") as f:
          f.write(existing)
        backup_msg = " (backup: %s)" % backup_path
      except OSError:
        backup_path = None  # no existing file: this is a fresh create, not an update
      with open(path, "w") as f:
        f.write(content)
      # Show the user what changed: a diff against the backup for an update,
      # or the content itself for a brand-new file. (The model still gets the
      # short summary below as the tool result.)
      self._show_write(path, backup_path, content)
      return "Written %d bytes to %s%s" % (len(content), path, backup_msg)
    except Exception as e:
      return "Error: %s" % str(e)

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

  def execute_list_running_apps(self, arguments):
    lines = ["screen 0: Python REPL"]
    try:
      apps_scnums = []
      for key in pu.app_list:
        app = pu.app_list[key]
        name = app.get('name', '?') if isinstance(app, dict) else str(app)
        lines.append("screen %s: %s" % (key, name))
        apps_scnums.append(key)
      for i in range(1, 10):
        if pdeck.cmd_exists(i) and i not in apps_scnums:
          lines.append("screen %d: command line shell" % i)
      lines.sort()
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
      # Give the target one frame to render before capture.
      pdeck.delay_tick(40)
    target = "screen %d" % scnum if scnum is not None else "the current screen"
    if self.capture_buf is None:
      # 400x240 1-bit = 50 bytes/row * 240 rows.
      self.capture_buf = bytearray(12000)
    try:
      v = pdeck.vscreen()
      if not v.take_screenshot(0, 0, 400, 240, self.capture_buf):
        return "Error: screenshot timed out (display busy or screen not active)"
      png = pngwriter.encode_mono_xbm(self.capture_buf, 400, 240)
      b64 = ubinascii.b2a_base64(png).decode().strip()
    except Exception as e:
      return "Error capturing screen: %s" % str(e)
    # Fed back as a user image on the next request.
    self.pending_image = b64
    return ("Captured %s. The screenshot is attached as an image; look at it and "
            "describe what you see." % target)

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
    except Exception as e:
      return "Error sending keys: %s" % str(e)
    return "Sent %d key(s)" % len(text)

  def execute_launch_command_shell(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
      scnum = int(args.get("screen"))
    except:
      return "Error: invalid arguments"
    if pdeck.cmd_exists(scnum):
      return "Error: screen %d is already in use" % scnum
    try:
      ok = pdeck.command_shell(scnum)
    except Exception as e:
      return "Error launching command shell: %s" % str(e)
    if not ok:
      return ("Error: could not launch a shell on screen %d (must be a free "
              "screen 2-9 other than the current one)" % scnum)
    return "Launched a command shell on screen %d" % scnum

  def _search_free_screen(self, launched, scnum=2):
    while True:
      if not pdeck.cmd_exists(scnum) and scnum not in launched:
        return scnum
      scnum += 1
      if scnum == 10:
        return -1

  def execute_launch_app(self, arguments):
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
    res = gpt_obj.tts_stream(raw_response_sub, voice=args.voice_type)
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
  "correct, idiomatic MicroPython (2-space indentation). Before you tell the user "
  "a task is done, run the code with your tools and confirm it works; if it "
  "errors, read the output, fix it, and re-run. Briefly explain what you changed.")

TTS_NOTE = ("Your reply will be fed to a TTS engine; optimize for text-to-speech: "
            "keep it short and speakable.")

# Auto-attached in agent mode so the model knows Pocket Deck basics.
DEFAULT_AGENT_REFS = ["/sd/Documents/pd/README.md",
                      "/sd/Documents/pd/gpt_output_rules.md",
                      "/sd/Documents/pd/gpt_readme.md"]

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
  return text


def load_agent_references(vs, silent=False):
  """Read the default Pocket Deck reference files (README.md) for agent mode."""
  refs = []
  for path in DEFAULT_AGENT_REFS:
    try:
      with open(path, "r") as f:
        refs.append("---- " + path + " ----\n" + f.read())
      if not silent:
        print("Attached reference: %s" % path, file=vs)
    except Exception:
      pass
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
  parser.add_argument('-m', '--model', action='store', default='gpt-5.4', help='Model to use (e.g. gpt-5-mini)')
  parser.add_argument('-e', '--effort', action='store', default='medium', help='Reasoning effort (low, medium, high)')
  parser.add_argument('-v', '--voice', action='store_true', help='Use voice mode (STT and TTS)')
  parser.add_argument('-vt', '--voice-type', action='store', default='coral', help='Voice type for TTS')
  parser.add_argument('-r', '--role', action='store', default=None, help="Role preset 'assistant' or 'coder', a /sd/roles/<name>.txt file, or literal text. Default: assistant.")
  parser.add_argument('--log-file', action='store', default=None, help='Internal: reuse the same log filename across iterations')
  parser.add_argument('--resume', action='store_true', help='Save this turn\'s response id to the session list so a later call can continue the conversation')
  parser.add_argument('--resume-id', '--resume_id', dest='resume_id', action='store', default=None, help="Continue a prior conversation: a response id, or 'last' for the most recent saved session")
  parser.add_argument('content', nargs='*', help='Content to ask')
  parser.add_argument('-q', nargs='+', help='Content to ask, use this when you want to specify content explicitly.')

  args = parser.parse_args(args_in[1:])

  if not auto_connect.check(vs, silent=True):
    print("Network is not available", file=vs)
    return

  gpt_obj = chatgpt_agent(vs)
  if not gpt_obj.read_api_key():
    return
  gpt_obj.mode = 'plan' if args.plan else 'auto'

  # Conversation continuity across separate gpt invocations: --resume-id seeds
  # the previous_response_id (server-side state), --resume persists the new id
  # afterward. 'last' resolves to the most recent entry in the session list.
  resumed_from = None
  if args.resume_id:
    resumed_from = gpt.last_session_id() if args.resume_id == 'last' else args.resume_id
    gpt_obj.prev_response_id = resumed_from
    if not args.silent:
      if resumed_from:
        print("Resuming session %s" % resumed_from[:24], file=vs)
      else:
        print("No previous session to resume; starting new.", file=vs)

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

  model = resolve_model(margs['model'] if 'model' in margs else args.model)

  effort = margs['effort'] if 'effort' in margs else args.effort
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

  # gptn's own screen, so we can tell the agent to switch the foreground back
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
    'effort': effort,
    'role': role,
    'tts': tts_response,
    'agent': agent,
    'app_list': app_list,
    'instructions': assemble_instructions(role, tts_response, agent, app_list, my_screen),
    'tools': build_tools(app_list, agent=agent, web_search=True),
  }

  def run_turn(turn_message, refs, imgs):
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
    # Persist the (new) response id so a later --resume-id can continue this
    # chat. A new id distinct from what we resumed from means the turn produced
    # a fresh response; if they match (or it's None) the turn failed, so skip.
    if args.resume:
      new_id = gpt_obj.prev_response_id
      if new_id and new_id != resumed_from:
        gpt.save_session(new_id, message, replace_id=resumed_from)
    return

  # ---- Conversation mode ----
  history = []
  pending_refs = []   # files queued via /file for the next message

  def refresh():
    ctx['instructions'] = assemble_instructions(ctx['role'], ctx['tts'], ctx['agent'], ctx['app_list'], my_screen)
    ctx['tools'] = build_tools(ctx['app_list'], agent=ctx['agent'], web_search=True)

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
    print(
      "Commands:\n"
      "  /help              this help\n"
      "  /quit  /exit       leave conversation\n"
      "  /clear /reset      start fresh (clear server-side context)\n"
      "  /model [name]      show or set model (m/medium, h/high, f/fast, or id)\n"
      "  /effort [level]    show or set reasoning effort (low|medium|high)\n"
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
      gpt_obj.prev_response_id = None
      print("New conversation (context cleared).", file=vs)
    elif cmd == 'model':
      if arg:
        ctx['model'] = resolve_model(arg)
      print("Model: %s" % ctx['model'], file=vs)
    elif cmd == 'effort':
      if arg in ('low', 'medium', 'high'):
        ctx['effort'] = arg
      elif arg:
        print("Effort must be low|medium|high.", file=vs)
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
        gpt_obj.prev_response_id = None
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
    else:
      print("Unknown command: /%s  (try /help)" % cmd, file=vs)
    return True

  print("Conversation mode. /help for commands, /quit to exit.", file=vs)
  print("Mode: %s (Shift-Tab or /mode to switch; Plan confirms commands & writes)." % gpt_obj.mode, file=vs)
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
    # failure (network error, etc.) and keep prompting. (ask_agent only commits
    # prev_response_id on a clean response, so a thrown turn leaves the prior
    # context intact and the next prompt can continue.)
    try:
      run_turn(line, turn_refs, turn_imgs)
    except BaseException as e:
      print("\n[Turn failed; you can keep going] %r" % (e,), file=vs)

  pdeck.led(1, 0)  # leaving conversation: clear status LEDs
  gpt_obj.led2_gen += 1  # invalidate any pending auto-off timer
  pdeck.led(2, 0)


# On a PC the device shell isn't there to call main(vs, args); provide an entry
# point so `python3 gpt.py ...` works. (On the device gpt is imported, not run.)
if __name__ == '__main__':
  main(pc_compat.PCStream(), ['gpt'] + sys.argv[1:])
