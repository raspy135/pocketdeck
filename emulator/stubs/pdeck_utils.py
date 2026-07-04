import sys
import io
import importlib

app_list = {}

def reimport(module_name):
  if module_name in sys.modules:
    del sys.modules[module_name]
  return importlib.import_module(module_name)

def launch(command, screen_num=0):
  pass

timezone = 0

# Pipeline machinery, kept in sync with the real pdeck_utils (used by
# gpt_tools and the device shell).
class CaptureStream(io.IOBase):
  """Captures a command's stdout (it is passed as the `vs` to main()) so the
  output can be piped to the next stage or returned. Bounded so a runaway
  command can't exhaust RAM."""
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

def split_pipeline(text):
  """Split a command line on top-level '|' into stage strings, ignoring pipes
  inside quotes. Empty stages (e.g. from '||' or a trailing '|') are dropped."""
  stages = []
  cur = ''
  in_quote = False
  quote = ''
  for ch in text:
    if in_quote:
      cur += ch
      if ch == quote:
        in_quote = False
    elif ch in ('"', "'"):
      in_quote = True
      quote = ch
      cur += ch
    elif ch == '|':
      stages.append(cur.strip())
      cur = ''
    else:
      cur += ch
  stages.append(cur.strip())
  return [s for s in stages if s]

def parse_cmd_string(text):
  """Split a command string into argv parts, honoring quotes. Bare (unquoted)
  '2>&1' tokens are dropped: MicroPython has no separate stderr to merge, so
  the redirect is meaningless noise. A quoted '2>&1' (e.g. a grep pattern) is
  kept."""
  parts = []
  cur = ''
  in_quote = False
  quote = ''
  quoted = False  # current token contained quotes
  for ch in text:
    if in_quote:
      if ch == quote:
        in_quote = False
      else:
        cur += ch
    elif ch in ('"', "'"):
      in_quote = True
      quote = ch
      quoted = True
    elif ch == ' ':
      if cur and (quoted or cur != '2>&1'):
        parts.append(cur)
      cur = ''
      quoted = False
    else:
      cur += ch
  if cur and (quoted or cur != '2>&1'):
    parts.append(cur)
  return parts

def split_pipeline_args(args):
  """Split an argv token list (as produced by the C shell) on standalone '|'
  tokens into per-stage argv lists. Bare '2>&1' tokens are dropped:
  MicroPython has no separate stderr to merge, so the redirect is meaningless
  noise. Empty stages are dropped."""
  stages = []
  cur = []
  for a in args:
    if a == '|':
      if cur:
        stages.append(cur)
      cur = []
    elif a != '2>&1':
      cur.append(a)
  if cur:
    stages.append(cur)
  return stages

def run_stages(stages, make_stream=CaptureStream):
  """Run pre-split pipeline stages (a list of argv lists): each stage's
  captured output is handed to the next as stdin via the pstdin bridge. Filter
  commands (head/tail/grep, and any module that reads pstdin) pick it up when
  given no file argument; commands that ignore stdin just drop it.
  make_stream() must return a stream with write()/getvalue(), passed as the
  `vs` to each stage's main(). Returns (last_stream, output) on success,
  (None, error message) on failure."""
  if not stages:
    return None, "empty command"
  import pstdin
  pstdin.take()  # clear any stale stdin left by a previous run

  cap = None
  prev_output = None
  for parts in stages:
    if not parts:
      return None, "empty command in pipeline"
    # 'r' prefix forces a fresh re-import of the module, exactly like the
    # device shell (process_prefix). Essential after editing a script you
    # already ran, since MicroPython otherwise reuses the cached module.
    if parts[0] == 'r' and len(parts) > 1:
      parts.pop(0)
      if parts[0] in sys.modules:
        del sys.modules[parts[0]]
    modname = parts[0]
    if prev_output is not None:
      pstdin.feed(prev_output)
    cap = make_stream()
    try:
      exec("import %s" % modname, {})
      sys.modules[modname].main(cap, parts)
    except BaseException as e:
      # Catch BaseException, not just Exception: a module that calls sys.exit()/
      # quit() (SystemExit) or raises KeyboardInterrupt would otherwise escape
      # and kill the caller. Capture the full traceback so the model can debug.
      cap.write("\nError running '%s':\n" % modname)
      sys.print_exception(e, cap)
    finally:
      pstdin.take()  # don't leak stdin to a command that never read it
    prev_output = cap.getvalue()
  return cap, prev_output

def run_pipeline(command, make_stream=CaptureStream):
  """Run an 'a | b | c' command line given as a single string (used by the gpt
  assistants). Splits on top-level '|' with quote handling, then runs the
  stages via run_stages(). Returns (last_stream, output) on success,
  (None, error message) on failure."""
  stage_strs = split_pipeline(command)
  if not stage_strs:
    return None, "empty command"
  stages = []
  for s in stage_strs:
    parts = parse_cmd_string(s)
    if not parts:
      return None, "empty command in pipeline"
    stages.append(parts)
  return run_stages(stages, make_stream)

# System helpers we don't emulate (autosleep, priority, etc.) become no-ops.
def __getattr__(name):
  return lambda *a, **kw: None
