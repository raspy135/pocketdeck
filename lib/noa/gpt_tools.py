# gpt_tools.py - shared function-calling spec for the gpt assistants.
#
# Single source of truth for the agent tools used by the three frontends:
#   - gpt.py    (OpenAI Responses API)
#   - gpt_c.py  (Chat Completions API / local servers)
#   - gpt_rt.py (OpenAI Realtime API / voice)
#
# It provides:
#   - build_tools(): the tool schemas in the flat function format. Responses and
#     Realtime consume this directly; gpt_c wraps each entry into the nested
#     Chat Completions shape (gpt_c.build_tools_c). The descriptions live here,
#     so they no longer drift between frontends.
#   - ToolExecBase: a mixin carrying the transport-independent tool
#     implementations (command_with_return, write_file, list_running_apps,
#     switch_screen, capture_screen, send_keys, launch_command_shell,
#     launch_app) plus the execute_function_call dispatcher.
#
# A subclass must provide these instance attributes:
#   self.vs           - the vscreen_stream for output
#   self.app_list     - list of [name, info] app entries (or [])
#   self.capture_buf  - preallocated bytearray for screenshots, or None (lazy)
#   self.pending_image- set to a base64 PNG by capture_screen; the frontend's
#                       loop is responsible for delivering it on the next turn.
# and may override these hooks (both default to no-op here):
#   _mute_audio(ms)            - silence audio around screen/app actions (gpt_rt)
#   _show_write(path, bak, txt)- display a diff/new-file view (gpt.py)

import sys
import os
import io
import time
import ujson
import ubinascii
import pdeck
import pdeck_utils as pu
import pngwriter
import ai_improve


# CaptureStream (bounded stdout capture) and the pipeline machinery now live in
# pdeck_utils, so the device shell pipes with the same code. Re-exported here
# because gpt.py / gpt_rt.py import it from this module.
CaptureStream = pu.CaptureStream


def build_tools(app_list, agent=False, web_search=True, realtime=False):
  """Tool schemas in the flat function format. Function tools are only included
  in agent mode; plain mode keeps just web_search (when requested). `realtime`
  adds tools that only make sense in the always-on voice agent (gpt_rt), where a
  non-blocking wait can run in the background with the mic still live."""
  tools = []
  if web_search:
    tools.append({"type": "web_search"})
  if not agent:
    return tools

  tools.append({
    "type": "function",
    "name": "command_with_return",
    "description": "Run a device command (or any installed module) and return its captured output. This is your primary tool for TESTING AND VERIFYING CODE: after you write a script with write_file, run it here by name and read the output to confirm it works, see errors, and iterate. A runnable script/app is a module exposing main(vs, args); invoke it by its name plus arguments, e.g. 'temp_foo arg1' for /sd/py/temp_foo.py, or any existing app/command. IMPORTANT: if you EDIT a script and run it again, prefix the command with 'r ' to reload it (e.g. 'r temp_foo arg1') — without 'r' the previous, cached version runs instead of your new code. Built-in commands include: ls (glob patterns like 'word*'; 'ls -r path' lists recursively), cat (read file), head, tail, rm, mv, cp, mkdir, rmdir, grep (search in files), ping, curl (fetch web content — use -L to follow redirects when researching the web, -m 15 for a timeout, -I for headers only, -o file or -O to save; URL goes LAST), and 'analog_clock_set_timer <minutes>'. grep behaves like Linux grep: the PATTERN is a regex by default (no -e needed), with -i ignore-case, -n line numbers, -r recursive, -l filenames only, -v invert, -F literal/fixed-string match, -A/-B/-C N context lines around matches (prefer 'grep -n -C 2' when inspecting code instead of cat-ing the whole file), -c count only, -m N stop after N matches (keeps output small), --no-filename, multiple file arguments, and --include .py,.md to filter by extension; e.g. 'grep -rn \"def .*main\" /sd/py'. Simple pipes ('|') are supported: a stage's output is fed to the next command as stdin, and stdin-aware filters read it when given no file (grep, head, and tail, e.g. 'ls -r /sd/py | grep clock', 'curl -s URL | grep -i error | head -n 5', or 'cat log.txt | tail -n 20'). Other commands ignore piped stdin, so only pipe INTO grep/head/tail. This is not Linux otherwise: no redirects ('>'), backticks, '&&', or subshells; use one command per stage.",
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
    "description": "Write text content to a file on the device filesystem. Creates or overwrites the file. For long file, making a patch Micropython code is preferred. The original file will be backed up under /sd/backup, so you don't need to take a backup file",
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
    "name": "read_console_log",
    "description": "Read the recent text output (scrollback) from a screen's terminal/console. Use this to see what a command-line app printed — e.g. to find an error message the user is asking about ('what's the error in the console?'). Returns the last N lines of console text. Defaults to the foreground screen.",
    "parameters": {
      "type": "object",
      "properties": {
        "lines": {"type": "integer", "description": "How many recent lines of console output to return (default 40, max 200)."},
        "screen": {"type": "integer", "description": "Optional 0-based screen number to read (matches list_running_apps). If omitted, reads the current foreground screen."}
      },
      "required": []
    }
  })

  tools.append({
    "type": "function",
    "name": "launch_command_shell",
    "description": "Launch a new command-line shell on a given screen so you can drive it with switch_screen / send_keys / capture_screen (e.g. to run interactive commands that command_with_return cannot). This is useful to debug graphical applications. The screen number is 0-based and matches list_running_apps (screen 0 is the Python REPL). Valid screens are 2-9; the screen must be free (nothing already running there). Returns whether the shell was started.",
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

  tools.append({
    "type": "function",
    "name": "pem_get_status",
    "description": "Get the current state of the PEM text editor, if it is running on some screen: the file being edited, the cursor position (1-based line and column), the number of lines, whether it has unsaved changes, and the list of open files/buffers. Call this before pem_edit_block so you know the current file and its line numbers. Returns an error if PEM is not running.",
    "parameters": {"type": "object", "properties": {}, "required": []}
  })

  tools.append({
    "type": "function",
    "name": "pem_edit_block",
    "description": "Edit the file currently open in the PEM text editor by replacing a range of lines with new content. line_from and line_to are 1-based and INCLUSIVE (the first line of the file is 1); set line_to equal to line_from to replace a single line. The replacement `content` may contain multiple newline-separated lines, or be an empty string to delete the range. To add lines without losing existing ones, replace a line with that line's original text followed by the new lines. The change is applied in the live editor (the user can undo it with C-z) and left unsaved so the user can review. Requires PEM to be running at its main editing screen; use pem_get_status first to read the current line numbers.",
    "parameters": {
      "type": "object",
      "properties": {
        "line_from": {"type": "integer", "description": "First line to replace (1-based, inclusive)"},
        "line_to": {"type": "integer", "description": "Last line to replace (1-based, inclusive). Use the same value as line_from to replace a single line."},
        "content": {"type": "string", "description": "Replacement text; may be multiple newline-separated lines, or empty to delete the range."}
      },
      "required": ["line_from", "line_to", "content"]
    }
  })

  tools.append({
    "type": "function",
    "name": "pem_read_content",
    "description": "Read text from the file currently open in the PEM text editor. line_from and line_to are 1-based and INCLUSIVE (the first line of the file is 1). Set line_to to null (or omit it) to read from line_from to the end of the file. Use pem_get_status first to learn the file's length. Returns the requested lines joined by newlines, or an error if PEM is not running.",
    "parameters": {
      "type": "object",
      "properties": {
        "line_from": {"type": "integer", "description": "First line to read (1-based, inclusive). Defaults to 1."},
        "line_to": {"type": ["integer", "null"], "description": "Last line to read (1-based, inclusive). Null or omitted reads to the end of the file."}
      },
      "required": ["line_from"]
    }
  })

  tools.append({
    "type": "function",
    "name": "pem_switch_buffer",
    "description": "Switch the PEM text editor to one of its already-open buffers, making `filename` the current editing file. Only files already open in PEM can be selected (see the open files list from pem_get_status); this does not open new files from disk. After switching, pem_get_status / pem_read_content / pem_edit_block operate on the newly selected file. Returns an error if PEM is not running or the file is not open.",
    "parameters": {
      "type": "object",
      "properties": {
        "filename": {"type": "string", "description": "Name of an already-open buffer to switch to, as shown in pem_get_status's open files list."}
      },
      "required": ["filename"]
    }
  })

  if realtime:
    tools.append({
      "type": "function",
      "name": "wait_and_resume",
      "description": "Pace a spoken, timed routine such as a stretch or yoga sequence, workout intervals, or guided breathing. CRITICAL ORDERING: This function call will wait specified time period in seconds. Speak what you need to inform to user before this function call. Example: in one reply, say 'Let's start with a standing quad stretch — hold it for thirty seconds,' and in that same reply call wait_and_resume with seconds=30. This does NOT block: the wait runs in the background with the microphone live, so the user can interrupt at any moment. When the hold finishes, this function call returns result. You are prompted again; then SPEAK the NEXT move and, in that reply, call wait_and_resume for it — repeat until the routine is done, then give a short 'nice work, that's the set' and stop calling it. ",
      "parameters": {
        "type": "object",
        "properties": {
          "seconds": {"type": "integer", "description": "How many seconds the user should hold the move you JUST spoke, before you are resumed to give the next one (1-600)."}
        },
        "required": ["seconds"]
      }
    })

  tools.append({
    "type": "function",
    "name": "update_memory",
    "description": "Review this session and update your long-term memory now (the same thing the /improve command does). Call this when the user asks you to 'remember this', 'learn from this', 'improve yourself', or update your memory, or when you notice a lasting user preference or a tool/command that reliably worked or failed. It analyzes the recent event log and conversation, distills durable lessons (user preferences, what worked, what to avoid), and saves a small memory file that is loaded back into your prompt in future sessions. Keep it rare; there is nothing to undo.",
    "parameters": {
      "type": "object",
      "properties": {
        "reason": {"type": "string", "description": "Optional short note on what prompted this update (e.g. 'user prefers concise answers')."}
      },
      "required": []
    }
  })

  return tools


class ToolExecBase:
  """Transport-independent implementations of the agent tools. Mixed into each
  frontend's agent class. See the module docstring for the required attributes
  and overridable hooks."""

  # Assistant modules that must never be run from inside command_with_return: a
  # nested session would re-enter the whole loop (networking + JSON) on the
  # already-deep 8KB command stack and overflow.
  RECURSIVE_GUARD = ('gpt', 'gpt_l', 'gpt_rt', 'gpt_c', 'gptn', 'gpt_tools')

  # ---- hooks (overridden by some frontends) --------------------------------
  def _mute_audio(self, ms):
    # gpt_rt silences audio around screen/app actions; no-op elsewhere.
    pass

  def _show_write(self, path, backup_path, content):
    # gpt.py shows a diff (or new-file view) of a write_file; no-op elsewhere.
    pass

  # ---- self-improvement hooks (overridden by the frontends) ----------------
  def _improve_conversation(self):
    # Recent conversation text to feed the memory summarizer; '' by default.
    return ''

  def _improve_stats(self):
    # Optional summary of this session's tool successes/failures; '' by default.
    return ''

  # ---- dispatch ------------------------------------------------------------
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
    if name == "read_console_log":
      return self.execute_read_console_log(arguments)
    if name == "send_keys":
      return self.execute_send_keys(arguments)
    if name == "launch_command_shell":
      return self.execute_launch_command_shell(arguments)
    if name == "launch_app":
      return self.execute_launch_app(arguments)
    if name == "pem_get_status":
      return self.execute_pem_get_status(arguments)
    if name == "pem_edit_block":
      return self.execute_pem_edit_block(arguments)
    if name == "pem_read_content":
      return self.execute_pem_read_content(arguments)
    if name == "pem_switch_buffer":
      return self.execute_pem_switch_buffer(arguments)
    if name == "wait_and_resume":
      return self.execute_wait_and_resume(arguments)
    if name == "update_memory":
      return self.execute_update_memory(arguments)
    return "Unknown function: %s" % name

  # ---- timed-program pacing ------------------------------------------------
  def _parse_wait_seconds(self, arguments):
    # Shared parse+clamp for wait_and_resume. Returns (seconds, err): err is a
    # ready-to-return error string, else None.
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return 0, "Error: invalid arguments"
    try:
      seconds = int(args.get("seconds"))
    except:
      return 0, "Error: seconds must be an integer"
    if seconds < 1:
      seconds = 1
    if seconds > 600:
      seconds = 600
    return seconds, None

  def execute_wait_and_resume(self, arguments):
    # Base (synchronous) fallback. gpt_rt overrides this with a non-blocking
    # version and is the only frontend that registers the tool, so this is a
    # safety net rather than a normal path.
    seconds, err = self._parse_wait_seconds(arguments)
    if err:
      return err
    time.sleep(seconds)
    return "Waited %d seconds. Deliver the next step now." % seconds

  # ---- PEM editor remote control -------------------------------------------
  def _find_pem(self):
    # Locate a running PEM editor by the object it registered via
    # vs.register_module() (stored in pu.app_list[scnum]['obj']). Match on the
    # public method rather than the app name so it works whatever pem was
    # launched as. Returns the editor object, or None if PEM isn't running.
    try:
      for key in pu.app_list:
        entry = pu.app_list[key]
        obj = entry.get('obj') if isinstance(entry, dict) else None
        if obj is not None and hasattr(obj, 'pub_edit_block'):
          return obj
    except Exception:
      pass
    return None

  def execute_pem_get_status(self, arguments):
    ed = self._find_pem()
    if ed is None:
      return "Error: PEM is not running (launch pem and open a file first)."
    try:
      st = ed.pub_get_status()
    except Exception as e:
      return "Error reading PEM status: %s" % str(e)
    fname = st.get('filename')
    files = ", ".join(st.get('open_files', []))
    return ("file: %s\ncursor: line %d, col %d\nlines: %d\nmodified: %s\nopen files: %s"
            % (fname if fname is not None else '** New file **',
               st.get('row', 0), st.get('col', 0), st.get('num_lines', 0),
               "yes" if st.get('modified') else "no", files))

  def execute_pem_edit_block(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    ed = self._find_pem()
    if ed is None:
      return "Error: PEM is not running (launch pem and open a file first)."
    try:
      line_from = int(args.get("line_from"))
      line_to = int(args.get("line_to"))
    except:
      return "Error: line_from and line_to must be integers"
    content = args.get("content", "")
    if not isinstance(content, str):
      return "Error: content must be a string"
    try:
      ok, msg = ed.pub_edit_block(line_from, line_to, content)
    except Exception as e:
      return "Error applying edit: %s" % str(e)
    return ("OK: " + msg) if ok else ("Error: " + msg)

  def execute_pem_read_content(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    ed = self._find_pem()
    if ed is None:
      return "Error: PEM is not running (launch pem and open a file first)."
    line_from = args.get("line_from", 1)
    if line_from is None:
      line_from = 1
    try:
      line_from = int(line_from)
    except:
      return "Error: line_from must be an integer"
    line_to = args.get("line_to", None)
    if line_to is not None:
      try:
        line_to = int(line_to)
      except:
        return "Error: line_to must be an integer or null"
    try:
      ok, text = ed.pub_read_content(line_from, line_to)
    except Exception as e:
      return "Error reading content: %s" % str(e)
    return text if ok else ("Error: " + text)

  def execute_pem_switch_buffer(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    ed = self._find_pem()
    if ed is None:
      return "Error: PEM is not running (launch pem and open a file first)."
    filename = args.get("filename")
    if not isinstance(filename, str) or filename == "":
      return "Error: filename must be a non-empty string"
    try:
      ok, msg = ed.pub_switch_buffer(filename)
    except Exception as e:
      return "Error switching buffer: %s" % str(e)
    return ("OK: " + msg) if ok else ("Error: " + msg)

  # ---- self-improvement (the /improve command, AI-callable) ----------------
  def run_self_improve(self, reason=None):
    # Shared by the update_memory tool, gpt_c's /improve command and gpt_rt's
    # periodic auto-run. Analyzes the recent event log + conversation and
    # rewrites the compact memory file. Returns (ok, message).
    api_key = getattr(self, 'api_key', '') or ''
    stats = self._improve_stats()
    if reason:
      stats = (stats + "\n" if stats else "") + "Trigger: " + str(reason)
    return ai_improve.improve(api_key, self._improve_conversation(), stats or None)

  def execute_update_memory(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      args = {}
    reason = args.get("reason") if isinstance(args, dict) else None
    try:
      ok, msg = self.run_self_improve(reason)
    except Exception as e:
      return "Error updating memory: %s" % str(e)
    return ("OK: " + msg) if ok else ("Error: " + msg)

  # ---- implementations -----------------------------------------------------
  def execute_command_with_return(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    command = args.get("command", "").strip()
    if not command:
      return "Error: no command specified"
    # Recursion guard: only the first command of the line is checked. Guarded
    # modules take over the conversation, so they can't meaningfully appear as
    # a later pipe stage anyway.
    parts = pu.parse_cmd_string(command)
    if parts and parts[0] == 'r' and len(parts) > 1:
      parts.pop(0)
    if parts and parts[0] in self.RECURSIVE_GUARD:
      return "Error: refusing to run '%s' recursively from inside the assistant." % parts[0]
    # Pipeline splitting/execution lives in pdeck_utils.run_pipeline: stages are
    # split on top-level '|', each stage's captured output feeds the next as
    # stdin via the pstdin bridge, and bare '2>&1' redirects are dropped.
    cap, result = pu.run_pipeline(command, CaptureStream)
    if cap is None:
      return "Error: " + result
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
      # Show the user what changed (frontends that have a screen override the hook).
      self._show_write(path, backup_path, content)
      return "Written %d bytes to %s%s" % (len(content), path, backup_msg)
    except Exception as e:
      return "Error: %s" % str(e)

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
    self._mute_audio(800)
    try:
      v = pdeck.vscreen()
      if not v.take_screenshot(0, 0, 400, 240, self.capture_buf):
        return "Error: screenshot timed out (display busy or screen not active)"
      png = pngwriter.encode_mono_xbm(self.capture_buf, 400, 240)
      b64 = ubinascii.b2a_base64(png).decode().strip()
    except Exception as e:
      return "Error capturing screen: %s" % str(e)
    # Fed back as a user image on the next turn; the frontend's loop delivers it.
    self.pending_image = b64
    return ("Captured %s. The screenshot is attached as an image; look at it and "
            "describe what you see." % target)

  def execute_read_console_log(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    try:
      lines = int(args.get("lines", 40))
    except:
      lines = 40
    if lines <= 0:
      lines = 40
    if lines > 200:
      lines = 200
    scnum = args.get("screen", None)
    try:
      if scnum is not None:
        scnum = int(scnum)
        v = pdeck.vscreen(scnum)
        target = "screen %d" % scnum
      else:
        v = pdeck.vscreen()
        target = "the foreground screen"
      text = v.get_console_log(lines)
    except Exception as e:
      return "Error reading console: %s" % str(e)
    text = text.rstrip() if text else ""
    if not text:
      return "(%s console is empty)" % target
    return "Console output (%s), last %d lines:\n%s" % (target, lines, text)

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
