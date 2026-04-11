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
              max_bytes=None, out=None, regex= False):
  if out is None:
    out = sys.stdout
  if includes is None:
    includes = []
  else:
    includes = includes.split(',')

  pat = pattern.lower() if ignore_case else pattern
  pat = re.compile(pat) if regex else pat
  print(pat)

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

  def scan_file(fp):
    if not allowed_file(fp):
      return False
    #print(fp)
    matched_this_file = False
    try:
      with open(fp, "r") as f:
        ln = 0
        for line in f:
          ln += 1
          s = line.rstrip("\n")
          if _match_line(s, pat, ignore_case, regex):
            matched_this_file = True
            if list_files_only:
              out.write(fp + "\n")
              return True
            if show_line_numbers:
              out.write("{}{}{}:{}: {}\n".format(el.set_font_color(1), fp, el.reset_font_color(), ln, s))
            else:
              out.write("{}{}{}: {}\n".format(el.set_font_color(1), fp, el.reset_font_color(), s))
    except Exception:
      return False
    return matched_this_file

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

  walk(path)

def build_parser():
  parser = argparse.ArgumentParser(
    description="Simple grep implementation for MicroPython"
  )
  parser.add_argument("pattern", help="Search pattern")
  parser.add_argument("path", nargs="?", default=".", help="File or directory to search")
  parser.add_argument("-r", "--recursive", action="store_true", help="Recursive search")
  parser.add_argument("-e", "--regex", action="store_true", help="RegEx search")
  parser.add_argument("-n", action="store_true", dest="show_line_numbers", help="Show line numbers")
  parser.add_argument("-i", "--ignore-case", action="store_true", dest="ignore_case", help="Ignore case")
  parser.add_argument("-l", action="store_true", dest="list_files_only", help="Show filenames only")
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

  print(f"pat:{args.pattern}, re={args.regex}")
  grep_path(
    args.pattern,
    path=args.path,
    recursive=args.recursive,
    show_line_numbers=args.show_line_numbers,
    ignore_case=args.ignore_case,
    list_files_only=args.list_files_only,
    includes=args.include,
    max_bytes=args.max_bytes,
    out=vs,
    regex=args.regex
  )
  return 0

