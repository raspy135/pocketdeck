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


# web_search backends (see ToolExecBase.execute_web_search):
#   - Default, keyless: DuckDuckGo's HTML endpoint. It returns a plain server-
#     rendered result page that _ddg_parse turns into (title, url, snippet)
#     tuples on-device, so the model never sees raw HTML.
#   - Optional upgrade: drop a Tavily key at TAVILY_KEY_PATH and web_search
#     switches to Tavily's LLM-native JSON search (api.tavily.com), which has a
#     free tier for real use. Both paths feed the same result formatter.
DDG_SEARCH_URL = "https://html.duckduckgo.com/html/"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
TAVILY_KEY_PATH = "/config/tavily_api_key"
# A browser-like UA: DuckDuckGo's HTML endpoint 403s a bare tool user-agent.
WEB_UA = "Mozilla/5.0 (X11; Linux x86_64) pdeck/0.2"


def url_quote(s):
  """Percent-encode a query string for a URL. Keeps the RFC3986 unreserved set
  (alnum and -_.~) verbatim and encodes everything else, including spaces, as
  %XX. Small standalone helper because MicroPython has no urllib.parse.quote."""
  safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
  out = []
  for b in s.encode("utf-8"):
    c = chr(b)
    if c in safe:
      out.append(c)
    else:
      out.append("%%%02X" % b)
  return "".join(out)


# Minimal HTML entity table for the few entities DuckDuckGo emits in titles and
# snippets; numeric (&#39; / &#x27;) forms are handled generically below.
_HTML_ENTITIES = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'",
                  "nbsp": " ", "#39": "'", "#47": "/"}


def html_unescape(s):
  """Decode the HTML entities that appear in DDG result text. Handles the named
  set above plus numeric &#NN; / &#xHH; references; leaves anything else as-is."""
  if "&" not in s:
    return s
  out = []
  i = 0
  n = len(s)
  while i < n:
    c = s[i]
    if c == "&":
      j = s.find(";", i + 1)
      if 0 < j <= i + 8:
        ent = s[i + 1:j]
        if ent in _HTML_ENTITIES:
          out.append(_HTML_ENTITIES[ent])
          i = j + 1
          continue
        if ent[:1] == "#":
          try:
            code = int(ent[2:], 16) if ent[1:2] in ("x", "X") else int(ent[1:])
            out.append(chr(code))
            i = j + 1
            continue
          except:
            pass
      out.append(c)
      i += 1
    else:
      out.append(c)
      i += 1
  return "".join(out)


def strip_tags(s):
  """Remove HTML tags from a fragment and unescape entities, returning trimmed
  plain text. A simple depth counter drops everything between '<' and '>'."""
  out = []
  depth = 0
  for c in s:
    if c == "<":
      depth += 1
    elif c == ">":
      if depth > 0:
        depth -= 1
    elif depth == 0:
      out.append(c)
  return html_unescape("".join(out)).strip()


def url_unquote(s):
  """Percent-decode a URL-encoded string (inverse of url_quote). Used to recover
  the real destination from DuckDuckGo's '/l/?uddg=<encoded>' redirect links."""
  if "%" not in s:
    return s
  res = bytearray()
  i = 0
  n = len(s)
  while i < n:
    c = s[i]
    if c == "%" and i + 2 < n:
      try:
        res.append(int(s[i + 1:i + 3], 16))
        i += 3
        continue
      except:
        pass
    res.append(ord(c) & 0xFF)
    i += 1
  try:
    return bytes(res).decode("utf-8")
  except:
    return bytes(res).decode("utf-8", "replace")


def _decode_ddg_href(href):
  # DDG wraps outbound links as '//duckduckgo.com/l/?uddg=<percent-encoded url>';
  # unwrap that to the real URL. Bare '//host' links get an https: scheme.
  href = html_unescape(href)
  p = href.find("uddg=")
  if p >= 0:
    v = href[p + 5:]
    amp = v.find("&")
    if amp >= 0:
      v = v[:amp]
    return url_unquote(v)
  if href.startswith("//"):
    return "https:" + href
  return href


def _ddg_parse(body, num):
  """Extract up to `num` (title, url, snippet) tuples from a DuckDuckGo HTML
  results page using plain string scanning (MicroPython's `re` has no findall
  and no DOTALL, so regex is avoided). Each result is an <a class="result__a">
  anchor for the title/link, followed by an <a class="result__snippet">."""
  items = []
  pos = 0
  while len(items) < num:
    i = body.find('class="result__a"', pos)
    if i < 0:
      break
    h = body.find('href="', i)
    if h < 0:
      break
    h += 6
    he = body.find('"', h)
    href = body[h:he]
    gt = body.find(">", he)
    te = body.find("</a>", gt)
    if gt < 0 or te < 0:
      break
    title = strip_tags(body[gt + 1:te])
    snippet = ""
    s = body.find('class="result__snippet"', te)
    if s >= 0:
      sg = body.find(">", s)
      se = body.find("</a>", sg)
      if sg >= 0 and se >= 0:
        snippet = strip_tags(body[sg + 1:se])
    items.append((title, _decode_ddg_href(href), snippet))
    pos = te + 4
  return items


class AgentCaptureStream(pu.CaptureStream):
  """CaptureStream for command_with_return runs. A graphic/interactive app
  immediately reaches for screen facilities (vs.v, register_module, read_nb,
  ...) that a capture buffer cannot provide; fail fast with a marker message
  so execute_command_with_return can relaunch the app on a real screen via
  the launch_app path instead of surfacing a bare AttributeError."""
  NEEDS_SCREEN = "needs a real screen"

  def __getattr__(self, name):
    raise AttributeError("CaptureStream has no '%s': this app %s"
                         % (name, AgentCaptureStream.NEEDS_SCREEN))


def indent_hint(path, content):
  """Post-write teaching hint: Pocket Deck Python uses 2 spaces per indent
  level. Models often emit 4 (training bias) and can't 'see' the difference,
  so tell them right when it happens, with a mechanical fix. Only the first
  statement under a top-level 'def main():'-style opener is measured — that
  line is one level deep by definition, while deeper nesting, continuation
  lines and string contents legitimately start with 4+ spaces even in
  2-space style (so measuring any other line would false-alarm)."""
  if not path.endswith('.py'):
    return ''
  opener_indent = None
  for line in content.split('\n'):
    stripped = line.lstrip(' \t')
    if not stripped or stripped.startswith('#'):
      continue
    if opener_indent is not None:
      if '\t' in line[:len(line) - len(stripped)]:
        return ("\nNote: this file is indented with tabs but Pocket Deck "
                "Python uses 2 spaces per indent level. Rewrite it using "
                "spaces (first level = 2 spaces, second = 4).")
      n = (len(line) - len(line.lstrip(' '))) - opener_indent
      if n >= 3:
        return ("\nNote: this file is indented with %d spaces per level but "
                "Pocket Deck Python uses 2 spaces per indent level. Rewrite "
                "the file, halving each line's leading spaces (first level = "
                "2 spaces, second = 4)." % n)
      return ''
    # Arm on a block opener like 'def main(vs, args):'. A line containing
    # '#' anywhere is never used as the opener: the '#' could sit inside a
    # string, so stripping "the comment" off is not reliable. The next code
    # line is one level deeper, so the indent it ADDS is the indent unit.
    if '#' not in line and line.rstrip().endswith(':'):
      opener_indent = len(line) - len(line.lstrip(' '))
  return ''


def module_exists(modname):
  """True if modname can be launched: already imported (incl. frozen), a
  .py/.mpy on sys.path, or importable (covers frozen modules not yet loaded)."""
  if modname in sys.modules:
    return True
  for d in sys.path:
    base = (d if d.endswith('/') or not d else d + '/') + modname
    for ext in ('.py', '.mpy'):
      try:
        os.stat(base + ext)
        return True
      except OSError:
        pass
  try:
    __import__(modname)
    return True
  except ImportError:
    return False
  except Exception:
    return True  # exists but crashed at import; launching will show why


def build_tools(app_list, agent=False, web_search=True, realtime=False,
                hosted_search=False):
  """Tool schemas in the flat function format. Function tools are only included
  in agent mode; plain mode keeps just web_search (when requested). `realtime`
  adds tools that only make sense in the always-on voice agent (gpt_rt), where a
  non-blocking wait can run in the background with the mic still live.

  Web search comes in two flavours, selected by `hosted_search`:
    - hosted_search=True: OpenAI's server-side hosted web_search tool
      ({"type": "web_search"}). Used for genuine OpenAI Responses endpoints,
      where it is the best available search.
    - hosted_search=False (default): a DEVICE-side web_search FUNCTION tool
      (see ToolExecBase.execute_web_search) that queries DuckDuckGo (or Tavily
      with a key). This is what non-OpenAI endpoints, the local/Chat-Completions
      models in gpt_c, and the voice agent use — those have no hosted search, so
      without it the model resorts to scraping search pages with curl. Only one
      of the two is ever emitted, so their shared name never collides."""
  tools = []
  if web_search:
    if hosted_search:
      tools.append({"type": "web_search"})
    else:
      tools.append({
        "type": "function",
        "name": "web_search",
        "description": "Search the web and get back ranked, up-to-date results (title, URL, and a short snippet for each) from an AI-friendly search engine. Use this for ANY general web search or whenever you need current information the model may not know: news, documentation, product/prices, facts, people, etc. IMPORTANT: prefer this over running curl on a search-engine URL — scraping search result pages with curl is unreliable and frequently blocked, which is why searches fail. Workflow: call web_search to find relevant pages, then, if you need the full text of a specific result, fetch just that page with command_with_return using 'curl -s <url>'.",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "The search query, in natural language or keywords, e.g. 'micropython ssd1306 i2c wiring' or 'latest esp32-s3 price'."
            },
            "num_results": {
              "type": "integer",
              "description": "How many results to return (default 5, max 10)."
            }
          },
          "required": ["query"]
        }
      })
  if not agent:
    return tools

  tools.append({
    "type": "function",
    "name": "command_with_return",
    "description": "Run a device command (or any installed module) and return its captured output for non-graphical apps. GRAPHIC/interactive apps cannot run here (there is no screen to draw on): launch them with launch_app instead, setting reload=true after editing their source — launch_app's reload replaces the 'r' prefix. If a graphic app is run here by mistake it is detected and relaunched via launch_app automatically. This is your primary tool for TESTING AND VERIFYING CODE: after you write a script with write_file, run it here by name and read the output to confirm it works, see errors, and iterate. A runnable script/app is a module exposing main(vs, args); invoke it by its name plus arguments, e.g. 'temp_foo arg1' for /sd/py/temp_foo.py, or any existing app/command. IMPORTANT: if you EDIT a script and run it again, prefix the command with 'r ' to reload it (e.g. 'r temp_foo arg1') — without 'r' the previous, cached version runs instead of your new code. Built-in commands include: ls (glob patterns like 'word*'; 'ls -r path' lists recursively), cat (read file), head, tail, rm, mv, cp, mkdir, rmdir, grep (search in files), ping, curl. This not Linux, available options are limited. See README.md for available options for the commands. Simple pipes ('|') are supported: a stage's output is fed to the next command as stdin, and stdin-aware filters read it when given no file (grep, head, and tail, e.g. 'ls -r /sd/py | grep clock', 'curl -s URL | grep -i error | head -n 5', or 'cat log.txt | tail -n 20'). Other commands ignore piped stdin, so only pipe INTO grep/head/tail. Output redirect to a file is supported on the final stage: '> file' truncates, '>> file' appends (e.g. 'ls -r /sd/py > files.txt' or 'curl -s URL | grep -i error >> log.txt'); the written text is plain (color codes stripped) and capped at ~50KB. This is not Linux otherwise: no input redirect ('<'), backticks, '&&', or subshells; use one command per stage.",
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
    "description": "Write text content to a file on the device filesystem. Creates or overwrites the WHOLE file. To change only part of an existing (especially large) file, use edit_file instead — it sends just the changed snippet rather than the entire file. The original file will be backed up under /sd/backup, so you don't need to take a backup file",
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

  tools.append({
    "type": "function",
    "name": "edit_file",
    "description": "Edit part of an existing file by exact text replacement — PREFERRED over write_file for changing a large file, since you send only the snippet that changes, not the whole file. `old_string` must match the current file content EXACTLY, including whitespace and indentation (Pocket Deck Python uses 2 spaces per indent level), and must appear exactly ONCE — include enough surrounding lines to make it unique. It is replaced with `new_string`. To delete text, pass an empty new_string. Read the file first (e.g. 'cat path') so you quote it exactly. The original file is backed up under /sd/backup. If old_string is not found or is not unique, nothing is changed and an error is returned — fix the snippet and retry.",
    "parameters": {
      "type": "object",
      "properties": {
        "path": {
          "type": "string",
          "description": "Absolute file path to edit, e.g. '/sd/py/myapp.py'"
        },
        "old_string": {
          "type": "string",
          "description": "Exact existing text to replace (must occur exactly once)."
        },
        "new_string": {
          "type": "string",
          "description": "Replacement text. Empty string deletes old_string."
        }
      },
      "required": ["path", "old_string", "new_string"]
    }
  })

  if not realtime:
    # Voice agent excluded: there the model just asks out loud. For the text
    # agents this is the explicit escape hatch, so the model stops grinding on
    # a failing approach instead of burning tool rounds.
    tools.append({
      "type": "function",
      "name": "ask_user",
      "description": "Stop working and hand control back to the user. Call this when you are stuck: an approach failed twice, you need a decision, permission, or information only the user has, or continuing would just repeat the same failing attempts. Retrying in circles is worse than asking. After this call, do not call more tools: your next reply should be a short text message stating what you tried, what went wrong, and what you need from the user.",
      "parameters": {
        "type": "object",
        "properties": {
          "question": {
            "type": "string",
            "description": "What you need from the user: the question or decision, with one line of context on what you tried and why you are stuck."
          }
        },
        "required": ["question"]
      }
    })

  if app_list:
    tools.append({
      "type": "function",
      "name": "launch_app",
      "description": "Launch a Pocket Deck application by its exact name, or any installed module/custom app by its module name (e.g. 'myapp' for /sd/lib/myapp.py), optionally passing arguments such as a file path to open. It returns screen number (0-based).",
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
          },
          "reload": {
            "type": "boolean",
            "description": "Set true after editing the app's source so the NEW code runs (clears the cached module before launching, like the shell's 'r' prefix). Without it a previously launched app runs its old cached code."
          }
        },
        "required": ["app_name"]
      }
    })

  tools.append({
    "type": "function",
    "name": "list_running_apps",
    "description": "List the apps currently running and which screen number each is on. Use this before switching, capturing, or driving an app. Note screen number starts from 0, but user's perspective screen number starts from 1.",
    "parameters": {"type": "object", "properties": {}, "required": []}
  })

  tools.append({
    "type": "function",
    "name": "switch_screen",
    "description": "Bring a screen to the foreground so it becomes active. Required before capturing or sending keys to that screen. Note the screen number in the function is 0-based.",
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
    "description": "Read the recent text output (scrollback) from a screen's terminal/console. Use this to see what a command-line app printed — e.g. to find an error message the user is asking about ('what's the error in the console?'). Returns the last N lines of console text. Defaults to the foreground screen. Note: to debug graphic apps, read that screen's log first; debug prints without file=vs still go to screen 0 (REPL).",
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
    "name": "launch_command_line_shell",
    "description": "Launch a new command-line shell on a given screen so you can drive it with switch_screen / send_keys / capture_screen (e.g. to run interactive commands that command_with_return cannot). You must use this call to launch command line shell. 'cmd' is not working with command_with_return or launch_app function call. This is useful to debug graphical applications. The screen number is 0-based and matches list_running_apps (screen 0 is the Python REPL). Valid screens are 2-9; the screen must be free (nothing already running there). Returns whether the shell was started.",
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
    "description": "Type text / keystrokes into the foreground app. Use escape sequences for special keys (arrows \\x1b[A/B/C/D, Esc \\x1b, Backspace \\x08, Ctrl-X \\x18). Typical use of this function is sending command to command line shell.",
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

  # Set by execute_ask_user; the frontend loop reads and clears it, then
  # forces the next round to be text-only so the turn ends with the question.
  user_question = None

  # Linux-only commands that don't exist here. Not pre-blocked (a user-installed
  # /sd/py/find.py must still run): only used to append a teaching hint when one
  # of these genuinely fails with ImportError, so a weak model can recover.
  _LINUX_ONLY = ('bash', 'sh', 'zsh', 'python', 'python3', 'pip', 'pip3',
                 'find', 'sed', 'awk', 'echo', 'touch', 'chmod', 'chown',
                 'sudo', 'apt', 'apt-get', 'wget', 'which', 'xargs', 'export',
                 'source', 'env', 'ps', 'kill', 'uname')

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
    if name == "web_search":
      return self.execute_web_search(arguments)
    if name == "command_with_return":
      return self.execute_command_with_return(arguments)
    if name == "write_file":
      return self.execute_write_file(arguments)
    if name == "edit_file":
      return self.execute_edit_file(arguments)
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
    if name == "launch_command_line_shell":
      return self.execute_launch_command_shell(arguments)
    if name == "launch_app":
      return self.execute_launch_app(arguments)
    if name == "ask_user":
      return self.execute_ask_user(arguments)
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
    return ("Unknown function: %s. Only the listed tools exist; to run a "
            "device command, call command_with_return." % name)

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
    base_url = getattr(self, 'base_url', '') or ''
    is_openai = (not base_url) or base_url.rstrip('/') == 'https://api.openai.com/v1'
    # For OpenAI keep the cheap dedicated summary model (ai_improve's default);
    # for a local / other endpoint that model won't exist there, so summarize
    # with the model currently in use (set by the frontend as self.model).
    model = None if is_openai else getattr(self, 'model', None)
    stats = self._improve_stats()
    if reason:
      stats = (stats + "\n" if stats else "") + "Trigger: " + str(reason)
    return ai_improve.improve(api_key, self._improve_conversation(), stats or None,
                              model=model, base_url=(None if is_openai else base_url))

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

  # ---- web search ----------------------------------------------------------
  def _read_tavily_key(self):
    # Optional bearer key for the Tavily search endpoint. When present, web_search
    # upgrades from keyless DuckDuckGo to Tavily's JSON search. Missing = keyless.
    try:
      with open(TAVILY_KEY_PATH) as f:
        return f.read().strip()
    except OSError:
      return ""

  def _format_web_results(self, query, items):
    # items: list of (title, url, snippet). Render a compact numbered list.
    if not items:
      return "No web results found for '%s'." % query
    lines = ["Web search results for '%s':" % query]
    for i, (title, link, snippet) in enumerate(items):
      title = (title or "").strip() or "(no title)"
      snippet = (snippet or "").strip()
      if len(snippet) > 500:
        snippet = snippet[:500] + "..."
      lines.append("\n%d. %s\n   %s" % (i + 1, title, (link or "").strip()))
      if snippet:
        lines.append("   %s" % snippet)
    return "\n".join(lines)

  def execute_web_search(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    query = (args.get("query") or "").strip()
    if not query:
      return "Error: no query specified"
    try:
      num = int(args.get("num_results", 5))
    except:
      num = 5
    if num < 1:
      num = 1
    if num > 10:
      num = 10
    key = self._read_tavily_key()
    if key:
      return self._tavily_search(query, num, key)
    return self._ddg_search(query, num)

  def _ddg_search(self, query, num):
    # Keyless DuckDuckGo HTML endpoint, POSTing the query as a form field.
    try:
      import curl
      status, _rh, body = curl.request(
        DDG_SEARCH_URL, method="POST", data="q=" + url_quote(query),
        user_agent=WEB_UA, timeout=30, follow=3)
    except Exception as e:
      return ("Error: web search request failed: %s. Check the network "
              "connection (try 'ping duckduckgo.com' via command_with_return)." % e)
    try:
      code = int(status.split(" ")[1])
    except:
      code = 0
    if code != 200:
      return ("Error: web search returned HTTP %d from DuckDuckGo. Retry in a "
              "moment; if it persists the endpoint may be rate-limiting." % code)
    html = body.decode("utf-8", "replace") if body else ""
    return self._format_web_results(query, _ddg_parse(html, num))

  def _tavily_search(self, query, num, key):
    # Tavily JSON search (used when a key is configured). POSTs the query and
    # gets back LLM-ready results with a content snippet per hit.
    payload = ujson.dumps({"query": query, "max_results": num})
    headers = ["Content-Type: application/json",
               "Authorization: Bearer " + key]
    try:
      import curl
      status, _rh, body = curl.request(
        TAVILY_SEARCH_URL, method="POST", data=payload,
        header_lines=headers, timeout=30, follow=3)
    except Exception as e:
      return "Error: web search request failed: %s." % e
    try:
      code = int(status.split(" ")[1])
    except:
      code = 0
    if code == 401:
      return ("Error: Tavily rejected the API key (HTTP 401). Check the key in "
              "%s, or remove that file to fall back to keyless search." % TAVILY_KEY_PATH)
    if code == 429:
      return "Error: Tavily search is rate-limited (HTTP 429). Retry shortly."
    if code != 200:
      snippet = body[:200].decode("utf-8", "replace") if body else ""
      return "Error: Tavily search returned HTTP %d. %s" % (code, snippet)
    try:
      data = ujson.loads(body)
    except Exception:
      return "Error: could not parse Tavily search response."
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
      return "No web results found for '%s'." % query
    items = []
    for r in results[:num]:
      if isinstance(r, dict):
        items.append((r.get("title"), r.get("url"), r.get("content")))
    return self._format_web_results(query, items)

  # ---- implementations -----------------------------------------------------
  def execute_command_with_return(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return 'Error: invalid arguments. Send JSON like {"command": "ls /sd"}.'
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
    # stdin via the pstdin bridge, a trailing '> file'/'>> file' on the final
    # stage writes output to a file, and bare '2>&1' redirects are dropped.
    cap, result = pu.run_pipeline(command, AgentCaptureStream)
    if cap is None:
      return "Error: " + result
    # A graphic/interactive app crashed on the capture buffer (see
    # AgentCaptureStream): relaunch it properly on a real screen. reload=True
    # because the failed run has already cached the module. Pipes are not
    # auto-relaunched — a graphic app makes no sense as a pipe stage.
    if result and AgentCaptureStream.NEEDS_SCREEN in result and parts and '|' not in command:
      la = self.execute_launch_app(ujson.dumps(
        {"app_name": parts[0], "args": parts[1:], "reload": True}))
      return ("'%s' is a graphic/interactive app; it cannot run under "
              "command_with_return (no screen to draw on). Launched it via "
              "launch_app instead, with the module reloaded: %s\n"
              "Use capture_screen to see it; if it errors, the traceback "
              "appears on the app's own screen — read_console_log on that "
              "screen returns it. Next time call launch_app directly "
              "(reload=true after editing its source)." % (parts[0], la))
    if not result:
      return "(no output)"
    if cap._total >= CaptureStream._MAX:
      result += "\n...(truncated)"
    # A Linux-only command that genuinely doesn't exist surfaces as an
    # ImportError traceback; append a teaching hint so the model can recover.
    if 'ImportError' in result and "Error running '" in result:
      for name in self._LINUX_ONLY:
        if "Error running '%s':" % name in result:
          result += ("\nHint: '%s' does not exist - this is a MicroPython "
                     "device, not Linux. Use ls/cat/grep/head/tail/curl, or "
                     "write a MicroPython script with write_file and run it "
                     "by name. For wget, use curl -O." % name)
          break
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
      return "Written %d bytes to %s%s%s" % (len(content), path, backup_msg,
                                             indent_hint(path, content))
    except Exception as e:
      return "Error: %s" % str(e)

  def execute_edit_file(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    path = args.get("path", "").strip()
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    if not path:
      return "Error: no path specified"
    if not isinstance(old, str) or not isinstance(new, str):
      return "Error: old_string and new_string must be strings"
    if old == "":
      return "Error: old_string is empty; use write_file to create a file."
    try:
      with open(path, "r") as f:
        existing = f.read()
    except OSError:
      return "Error: %s not found. Use write_file to create it." % path
    count = existing.count(old)
    if count == 0:
      return ("Error: old_string not found in %s. Read the file (cat %s) and "
              "quote it exactly, including 2-space indentation." % (path, path))
    if count > 1:
      return ("Error: old_string appears %d times in %s; it must be unique. "
              "Add more surrounding lines to disambiguate." % (count, path))
    # Back up the original, mirroring execute_write_file.
    backup_path = None
    try:
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
    except Exception:
      backup_path = None
    content = existing.replace(old, new)
    try:
      with open(path, "w") as f:
        f.write(content)
    except Exception as e:
      return "Error: %s" % str(e)
    # Show the user what changed (frontends that have a screen override the hook).
    self._show_write(path, backup_path, content)
    return "Edited %s%s%s" % (path,
                              (" (backup: %s)" % backup_path) if backup_path else "",
                              indent_hint(path, content))

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

  def execute_ask_user(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      args = {}
    q = args.get("question", "") if isinstance(args, dict) else ""
    self.user_question = q or "(the assistant is stuck and needs your input)"
    return ("Question delivered. STOP now: no more tool calls. Reply with a "
            "short text message for the user — what you tried, what went "
            "wrong, and the question — then wait for their answer.")

  def execute_launch_app(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    app_name = args.get("app_name", "")
    extra_args = args.get("args", [])
    do_reload = args.get("reload", False)
    for item in self.app_list:
      if not (isinstance(item, list) and len(item) == 2 and item[0] == app_name):
        continue
      info = item[1]
      if not (isinstance(info, dict) and info.get('type') == 'program'):
        continue
      command = [list(c) for c in info.get('command', [])]
      if extra_args and command:
        command[0] = [command[0][0]] + extra_args
      if do_reload:
        for one in command:
          if one and one[0] in sys.modules:
            del sys.modules[one[0]]
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
      if launched:
        return ("Launched %s on screen %s" %
                (app_name, ", ".join(str(s) for s in launched)))
      return "Error: no free screen to launch %s" % app_name
    # Not registered: launch it like a shell command, so any module on
    # sys.path (lib/, /sd/lib, custom apps) can be started by name. A path
    # or filename is accepted too: '/sd/lib/myapp.py' -> 'myapp'.
    modname = app_name.split('/')[-1]
    for ext in ('.py', '.mpy'):
      if modname.endswith(ext):
        modname = modname[:-len(ext)]
    if not modname or not module_exists(modname):
      return ("App not found: %s (not in the registered app list, and no "
              "module named '%s' on sys.path)" % (app_name, modname))
    # After the existence check: module_exists may itself have imported (and
    # therefore cached) the module.
    if do_reload and modname in sys.modules:
      del sys.modules[modname]
    self._mute_audio(3000)
    scnum = self._search_free_screen([], 2)
    if scnum == -1:
      return "Error: no free screen to launch %s" % modname
    pdeck.change_screen(scnum)
    pu.launch([modname] + [str(a) for a in extra_args], scnum)
    pdeck.show_screen_num()
    return "Launched %s on screen %d" % (modname, scnum)
