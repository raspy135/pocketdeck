import pdeck
import os
import re
import argparse
import time
import pdeck_utils as pu

def is_int(s):
  try:
    int(s)
    return True
  except ValueError:
    return False

def _is_dir(path):
  if path == '.':
    return True
  try:
    st = os.stat(path)
    return (st[0] & 0x4000) != 0  # stat.S_IFDIR (MicroPython uses bitmask)
  except OSError:
    return False

def _join_path(base, name):
  if base == '/':
    return '/' + name
  if base == '' or base == '.':
    return name
  return base + '/' + name

_re_meta = '.^$+?()[]{}|\\'

def _glob_to_pat(name):
  # Only '*' is special as a glob. Everything else that is a regex
  # metacharacter must be escaped, otherwise names like 'a+b.txt' or
  # 'x[1].md' can never be matched literally.
  out = ''
  for ch in name:
    if ch == '*':
      out += '.*'
    elif ch in _re_meta:
      out += '\\' + ch
    else:
      out += ch
  return out

def _normalize_query_path(q):
  if q[-1] == '/' and len(q) > 1:
    q = q[:-1]
  return q

def _split_query(q):
  filename = ''
  dirname = q

  if _is_dir(q):
    return q, '^.*', q

  split_folders = q.split('/')
  filename = split_folders[-1]
  split_folders = split_folders[0:-1]

  if len(split_folders) == 0:
    dirname = '.'
  else:
    dirname = '/'.join(split_folders)
    if dirname == '':
      dirname = '/'

  return dirname, '^' + _glob_to_pat(filename) + '$', q

def _collect_recursive(dirname, pat, out, reverse=False):
  try:
    ret = sorted(os.listdir(dirname), reverse=reverse)
  except Exception:
    return

  filelist = []
  for file in ret:
    full = _join_path(dirname, file)
    match = pat.search(file)
    if match:
      filelist.append(file)
    if _is_dir(full):
      _collect_recursive(full, pat, out, reverse)

  if len(filelist) > 0:
    out.append([dirname, filelist])

month_list = ( \
    "","January","Febary","March","April", \
    "May","June", "July", "August","September", \
    "October","November", "December" )

def list_file(q, recursive=False, reverse=False, vs=None):
  # vs is optional: when given, error messages go to that stream instead of
  # the default stdout (screen 0). Returning None is the failure signal for
  # callers such as cat/cp/pem, so nothing is printed when vs is None.
  q = _normalize_query_path(q)
  dirname, filename, original = _split_query(q)
  try:
    if not _is_dir(original):
      os.listdir(dirname)
  except Exception:
    if vs:
      print("Directory not found", file=vs)
    return

  pat = re.compile(filename)

  if recursive:
    out = []
    _collect_recursive(dirname, pat, out, reverse)
    if len(out) == 0:
      return None
    return out

  try:
    ret = os.listdir(dirname)
  except Exception:
    print("Directory not found")
    return

  filelist = []
  for file in ret:
    match = pat.search(file)
    if match:
      filelist.append(file)
  if len(filelist) == 0:
    return None

  filelist.sort(reverse=reverse)
  return [ dirname, filelist ]

def _print_group(vs, dirname, filelist, detailed, index=0):
  print(f'File in {dirname}:', file=vs)

  for i, item in enumerate(filelist):
    if detailed:
      st = os.stat(_join_path(dirname, item))
      t = time.localtime(st[7]+pu.timezone*15*60)
      dirmark = '[Dir]' if st[0]&0x4000 != 0 else ''
      print(f'{index+i}: {dirmark} {item} {st[6]:,} {month_list[t[1]][:3]} {t[2]}, {t[0]} {t[3]:02}:{t[4]:02}:{t[5]:02}', file=vs)
    else:
      print(f'{item} ', end='', file=vs)

  print('', file=vs)
  return index + len(filelist)

def main(vs,args_in):
  parser = argparse.ArgumentParser(
            description='list file')
  parser.add_argument('-c', '--clip',action='store',help='Copy specified index filename to clipboard. -1 means the last one', default='-1000')
  parser.add_argument('-l', '--list',action='store_true', help='list files')
  parser.add_argument('-r', '--reverse', action='store_true', help='reverse sort order')
  parser.add_argument('-R', '--recursive', action='store_true', help='search recursively')
  parser.add_argument('paths',nargs='*', help='Path(s). Default is current dir', default=['.'])

  args = parser.parse_args(args_in[1:])
  paths = args.paths
  if len(paths) == 0:
    paths = ['.']

  groups = []
  for q in paths:
    ret = list_file(q, args.recursive, args.reverse)
    if not ret:
      print(f'No matched files: {q}', file=vs)
      continue
    if args.recursive:
      groups.extend(ret)
    else:
      groups.append(ret)

  if len(groups) == 0:
    return

  flat = []
  index = 0
  for dirname, filelist in groups:
    for item in filelist:
      flat.append(_join_path(dirname, item))
    index = _print_group(vs, dirname, filelist, args.list, index)

  if is_int(args.clip):
    file_index = int(args.clip)
    if file_index != -1000:
      try:
        filename = flat[file_index]
      except IndexError:
        print(f"Index {file_index} was out of range.", file=vs)
        return
      pdeck.clipboard_copy(filename)
      print(f'{filename} was copied to clipboard', file=vs)
