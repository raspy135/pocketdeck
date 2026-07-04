import os
import sys
import argparse
import esclib as elib
import re

el = elib.esclib()

def print_vs():
  pass

def _is_dir(path):
  try:
    st = os.stat(path)[0]
    return (st & 0x4000) != 0
  except Exception:
    return False

def _iter_dir(path):
  for name in os.listdir(path):
    if path == "/" or path.endswith("/"):
      full = path + name
    elif path == ".":
      full = name
    else:
      full = path + "/" + name
    yield full, name

def _bre_compat(pattern):
  # GNU grep's default dialect (BRE) writes alternation/groups as \| \( \).
  # MicroPython's re treats those as literal characters, so such a pattern
  # compiles fine but silently matches nothing. Translate the BRE spelling to
  # the re one so both dialects work. Scans left-to-right in escape pairs, so
  # '\\|' (escaped backslash, then alternation) survives untouched.
  out = []
  i = 0
  n = len(pattern)
  while i < n:
    c = pattern[i]
    if c == '\\' and i + 1 < n:
      nxt = pattern[i + 1]
      if nxt in '|()':
        out.append(nxt)
      else:
        out.append(c)
        out.append(nxt)
      i += 2
      continue
    out.append(c)
    i += 1
  return ''.join(out)

def _match_line(line, pat, ignore_case, regex):
  if ignore_case:
    line = line.lower()
  
  if regex:
    return pat.search(line)
  return pat in line

def _file_size(path):
  try:
    return os.stat(path)[6]
  except Exception:
    return None

def grep_path(pattern, path=".", recursive=False, show_line_numbers=False,
              ignore_case=False, list_files_only=False, includes=None,
              max_bytes=None, out=None, regex=True, invert=False,
              after=0, before=0, count_only=False, max_count=None,
              no_filename=False, stdin_text=None):
  if out is None:
    out = sys.stdout
  if includes is None:
    includes = []
  else:
    includes = includes.split(',')

  pat_src = pattern.lower() if ignore_case else pattern
  # Linux-like default: pattern is a regex. MicroPython's `re` is a limited
  # subset, so if the pattern can't compile, fall back to literal substring
  # search instead of raising (which would waste a caller's retry/tokens).
  use_regex = regex
  if use_regex:
    try:
      pat = re.compile(_bre_compat(pat_src))
    except Exception:
      out.write("grep: unsupported regex, falling back to literal match "
                "(supported: . [] ^ $ ? * + | () \\d \\s \\w; "
                "not: {m,n}, \\b, lookarounds)\n")
      pat = pat_src
      use_regex = False
  else:
    pat = pat_src

  def allowed_file(p):
    #if p != 'tasks.md':
    #  return False
    #else:
    #  return True
    if includes:
      ok = False
      for ext in includes:
        if p.endswith(ext):
          ok = True
          break
      if not ok:
        return False
    if max_bytes is not None:
      sz = _file_size(p)
      if sz is not None and sz > max_bytes:
        return False
    return True

  def emit(fp, ln, s, is_match):
    # Match lines use ':' separators, context lines '-' (like real grep).
    # fp is None for piped stdin, which carries no filename to prefix.
    sep = ":" if is_match else "-"
    if no_filename or fp is None:
      if show_line_numbers:
        out.write("{}{} {}\n".format(ln, sep, s))
      else:
        out.write(s + "\n")
    elif show_line_numbers:
      out.write("{}{}{}{}{}{} {}\n".format(el.set_font_color(1), fp, el.reset_font_color(), sep, ln, sep, s))
    else:
      out.write("{}{}{}{} {}\n".format(el.set_font_color(1), fp, el.reset_font_color(), sep, s))

  # Scan an iterable of lines. fp is the display name for output prefixes, or
  # None for piped stdin (no filename shown). Used for both files and stdin.
  def scan_lines(fp, line_source):
    matched_this_file = False
    count = 0
    before_buf = []   # (ln, text) of the last `before` lines not yet printed
    after_left = 0    # context lines still owed after the last match
    last_printed = 0  # line number of the last written line (for '--' gaps)
    ln = 0
    for line in line_source:
      ln += 1
      s = line.rstrip("\n")
      hit = bool(_match_line(s, pat, ignore_case, use_regex))
      if invert:
        hit = not hit
      if hit and (max_count is None or count < max_count):
        count += 1
        matched_this_file = True
        if list_files_only:
          out.write((fp if fp is not None else "(standard input)") + "\n")
          return True
        if not count_only:
          # '--' between non-adjacent match groups when context is on.
          first_ln = before_buf[0][0] if before_buf else ln
          if (after or before) and last_printed and first_ln > last_printed + 1:
            out.write("--\n")
          for bln, bs in before_buf:
            emit(fp, bln, bs, False)
          before_buf = []
          emit(fp, ln, s, True)
          last_printed = ln
          after_left = after
      elif after_left > 0 and not count_only:
        emit(fp, ln, s, False)
        last_printed = ln
        after_left -= 1
      elif before > 0 and not count_only:
        before_buf.append((ln, s))
        if len(before_buf) > before:
          before_buf.pop(0)
      # -m: once the cap is hit and trailing context is done, stop reading.
      if max_count is not None and count >= max_count and after_left == 0:
        break
    if count_only:
      if no_filename or fp is None:
        out.write("{}\n".format(count))
      else:
        out.write("{}{}{}: {}\n".format(el.set_font_color(1), fp, el.reset_font_color(), count))
    return matched_this_file

  def scan_file(fp):
    if not allowed_file(fp):
      return False
    try:
      with open(fp, "r") as f:
        return scan_lines(fp, f)
    except Exception:
      return False

  def walk(p):
    if _is_dir(p):
      for full, _name in _iter_dir(p):
        if _is_dir(full):
          if recursive:
            walk(full)
        else:
          scan_file(full)
    else:
      scan_file(p)

  if stdin_text is not None:
    try:
      scan_lines(None, iter(stdin_text.splitlines()))
    except Exception:
      pass
    return

  walk(path)

def build_parser():
  parser = argparse.ArgumentParser(
    description="Simple grep implementation for MicroPython"
  )
  parser.add_argument("pattern", help="Search pattern")
  parser.add_argument("path", nargs="*", help="Files or directories to search (default: .)")
  parser.add_argument("-r", "-R", "--recursive", action="store_true", help="Recursive search")
  # Pattern is a regex by default (Linux-like). -E is accepted as an alias and
  # -e is kept for backward compatibility; both are no-ops now. Use -F for literal.
  parser.add_argument("-e", "-E", "--regex", action="store_true", help="(default) treat pattern as a regex")
  parser.add_argument("-F", "--fixed-strings", action="store_true", dest="fixed", help="Treat pattern as a literal string, not a regex")
  parser.add_argument("-v", "--invert-match", action="store_true", dest="invert", help="Select non-matching lines")
  parser.add_argument("-n", action="store_true", dest="show_line_numbers", help="Show line numbers")
  parser.add_argument("-i", "--ignore-case", action="store_true", dest="ignore_case", help="Ignore case")
  parser.add_argument("-l", action="store_true", dest="list_files_only", help="Show filenames only")
  # Context lines. -h is taken by help on the device's argparse, so the
  # filename-suppress option is long-form only (--no-filename).
  parser.add_argument("-A", "--after-context", type=int, default=0, dest="after",
                      metavar="N", help="Show N lines after each match")
  parser.add_argument("-B", "--before-context", type=int, default=0, dest="before",
                      metavar="N", help="Show N lines before each match")
  parser.add_argument("-C", "--context", type=int, default=0, dest="context",
                      metavar="N", help="Show N lines before and after each match")
  parser.add_argument("-c", "--count", action="store_true", dest="count_only",
                      help="Print only a count of matching lines per file")
  parser.add_argument("-m", "--max-count", type=int, default=None, dest="max_count",
                      metavar="N", help="Stop after N matching lines per file")
  parser.add_argument("--no-filename", action="store_true", dest="no_filename",
                      help="Suppress the filename prefix on output lines")
  parser.add_argument(
    "--include",
    default=None,
    help="Only search files with this extension (comma separated for multiple extensions)"
  )
  parser.add_argument(
    "--max",
    type=int,
    dest="max_bytes",
    default=None,
    help="Skip files larger than this many bytes"
  )
  return parser

def main(vs, argv):
  parser = build_parser()

  try:
    args = parser.parse_args(argv[1:])
  except SystemExit:
    return 2

  # -C sets both sides; explicit -A/-B may extend one side further.
  after = args.after or 0
  before = args.before or 0
  if args.context:
    after = max(after, args.context)
    before = max(before, args.context)

  # No path (or an explicit '-') plus piped stdin from the shell: search that
  # instead of the filesystem. Without piped input, keep the Linux-unlike but
  # long-standing default of searching the cwd so interactive `grep pattern`
  # behaves as before.
  paths = args.path
  if not paths or paths == ["-"]:
    import pstdin
    if pstdin.has():
      grep_path(
        args.pattern,
        show_line_numbers=args.show_line_numbers,
        ignore_case=args.ignore_case,
        list_files_only=args.list_files_only,
        out=vs,
        regex=not args.fixed,
        invert=args.invert,
        after=after,
        before=before,
        count_only=args.count_only,
        max_count=args.max_count,
        no_filename=args.no_filename,
        stdin_text=pstdin.take()
      )
      return 0

  paths = paths if paths else ["."]
  for p in paths:
    grep_path(
      args.pattern,
      path=p,
      recursive=args.recursive,
      show_line_numbers=args.show_line_numbers,
      ignore_case=args.ignore_case,
      list_files_only=args.list_files_only,
      includes=args.include,
      max_bytes=args.max_bytes,
      out=vs,
      regex=not args.fixed,
      invert=args.invert,
      after=after,
      before=before,
      count_only=args.count_only,
      max_count=args.max_count,
      no_filename=args.no_filename
    )
  return 0

