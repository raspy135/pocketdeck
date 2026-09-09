import os
import re
import argparse

_meta = '.^$+?()[]{}|\\'

def _glob_to_pat(name):
  # Only '*' is special as a glob. Everything else that is a regex
  # metacharacter must be escaped.
  out = ''
  for ch in name:
    if ch == '*':
      out += '.*'
    elif ch in _meta:
      out += '\\' + ch
    else:
      out += ch
  return out

def _is_dir(path):
  if path == '.':
    return True
  try:
    st = os.stat(path)
    return (st[0] & 0x4000) != 0
  except OSError:
    return False

def _join(base, name):
  if base == '/':
    return '/' + name
  if base == '' or base == '.':
    return name
  return base + '/' + name

_UNITS = {'c': 1, 'w': 2, 'b': 512, 'k': 1024, 'M': 1048576, 'G': 1073741824}

def _size_ok(full, spec):
  # GNU-like size spec: [+|-]N[unit]. Applies to files only.
  try:
    op = ''
    if spec[0] in '+-':
      op = spec[0]
      spec = spec[1:]
    num = ''
    i = 0
    while i < len(spec) and spec[i].isdigit():
      num += spec[i]
      i += 1
    if not num:
      return True
    unit = spec[i:]
    limit = int(num) * _UNITS.get(unit, 1)
    sz = os.stat(full)[6]
    if op == '+':
      return sz > limit
    if op == '-':
      return sz < limit
    return sz == limit
  except (OSError, ValueError, IndexError):
    return True

def _matches(name, args):
  # name-pattern. GNU find's -name/-iname match the WHOLE base name,
  # so the glob must be anchored with ^ and $ (not re.search anywhere).
  if args.name is not None:
    if args.iname:
      pat = _glob_to_pat(args.name.lower())
      return re.match('^' + pat + '$', name.lower()) is not None
    else:
      pat = _glob_to_pat(args.name)
      return re.match('^' + pat + '$', name) is not None
  if args.iname is not None:
    pat = _glob_to_pat(args.iname.lower())
    return re.match('^' + pat + '$', name.lower()) is not None
  return True

def _do_find(root, args, depth, out):
  try:
    entries = sorted(os.listdir(root))
  except OSError:
    return
  for e in entries:
    full = _join(root, e)
    is_dir = _is_dir(full)
    g = depth + 1  # GNU depth of this entry (start point = level 0)
    if ((args.mindepth is None or g >= args.mindepth) and
        (args.maxdepth is None or g <= args.maxdepth)):
      # size filter (files only); dirs still recurse below
      if args.size is not None and not is_dir and not _size_ok(full, args.size):
        pass
      # type filter
      elif args.type:
        if args.type in ('f', 'file') and is_dir:
          pass  # skip dirs
        elif args.type in ('d', 'dir') and not is_dir:
          pass
        else:
          if _matches(e, args):
            out.append(full)
      else:
        if _matches(e, args):
          out.append(full)
    if is_dir and (args.maxdepth is None or g < args.maxdepth):
      _do_find(full, args, depth + 1, out)

def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='search for files in a directory hierarchy')
  parser.add_argument('path', nargs='?', default='.', help='directory to search (default: current)')
  parser.add_argument('-name', metavar='PATTERN', help='base name matches PATTERN (shell glob)')
  parser.add_argument('-iname', metavar='PATTERN', help='like -name but case-insensitive')
  parser.add_argument('-type', metavar='T', help='file type: f (file) or d (directory)')
  parser.add_argument('-maxdepth', metavar='N', type=int, help='descend at most N levels below the start point')
  parser.add_argument('-mindepth', metavar='N', type=int, help='do not output entries at levels less than N')
  parser.add_argument('-size', metavar='N', help='file size [+|-]N[c|w|b|k|M|G] (files only; + larger, - smaller)')
  parser.add_argument('-count', action='store_true', help='only print the number of matches')

  args = parser.parse_args(args_in[1:])

  root = args.path.rstrip('/') or '/'
  try:
    os.stat(root)
  except OSError:
    print(f'find: {args.path}: No such file or directory', file=vs)
    return

  results = []
  _do_find(root, args, 0, results)

  if args.count:
    print(len(results), file=vs)
    return

  for r in results:
    print(r, file=vs)
