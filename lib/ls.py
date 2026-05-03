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

  return dirname, '^' + filename.replace('.','\.').replace('*','.*') + '$', q

def _collect_recursive(dirname, pat, out):
  try:
    ret = os.listdir(dirname)
  except Exception:
    return

  filelist = []
  for file in ret:
    full = _join_path(dirname, file)
    match = pat.search(file)
    if match:
      filelist.append(file)
    if _is_dir(full):
      _collect_recursive(full, pat, out)

  if len(filelist) > 0:
    out.append([dirname, filelist])

def list_file(q, recursive=False):
  q = _normalize_query_path(q)
  dirname, filename, original = _split_query(q)

  try:
    if not _is_dir(original):
      os.listdir(dirname)
  except Exception:
    print("Directory not found")
    return

  pat = re.compile(filename)

  if recursive:
    out = []
    _collect_recursive(dirname, pat, out)
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

  return [ dirname, filelist ]

def _print_group(vs, dirname, filelist, detailed):
  print(f'File in {dirname}:', file=vs)

  for i, item in enumerate(filelist):
    if detailed:
      st = os.stat(_join_path(dirname, item))
      t = time.localtime(st[7]+pu.timezone*15*60)
      print(f'{i}: {'[Dir]' if st[0]&0x4000 != 0 else ''} {item} {st[6]:,} {t[0]}/{t[1]}/{t[2]} {t[3]:02}:{t[4]:02}:{t[5]:02}', file=vs)
    else:
      print(f'{item} ', end='', file=vs)

  print('', file=vs)

def main(vs,args_in):
  parser = argparse.ArgumentParser(
            description='list file')
  parser.add_argument('-c', '--clip',action='store',help='Copy specified index filename to clipboard. -1 means the last one', default='-1000')
  parser.add_argument('-l', '--list',action='store_true', help='list files')
  parser.add_argument('-r', '--recursive', action='store_true', help='search recursively')
  parser.add_argument('path',nargs='?', help='Path', default = '.')

  args = parser.parse_args(args_in[1:])
  q = args.path

  ret = list_file(q, args.recursive)
  if not ret:
    print('No matched files', file=vs)
    return

  if args.recursive:
    for group in ret:
      _print_group(vs, group[0], group[1], args.list)

    if is_int(args.clip):
      file_index = int(args.clip)
      if file_index != -1000:
        flat = []
        for group in ret:
          dirname = group[0]
          for item in group[1]:
            flat.append(_join_path(dirname, item))
        try:
          filename = flat[file_index]
        except IndexError:
          print(f"Index {file_index} was out of range.", file=vs)
          return
        pdeck.clipboard_copy(filename)
        print(f'{filename} was copied to clipboard', file=vs)
    return

  filelist = ret[1]
  _print_group(vs, ret[0], filelist, args.list)

  if is_int(args.clip):
    file_index = int(args.clip)
    if file_index != -1000:
      try:
        filename = filelist[file_index]
      except IndexError as e:
        print(f"Index {file_index} was out of range.", file=vs)
        return
      filename = _join_path(ret[0], filename)
      pdeck.clipboard_copy(filename)
      print(f'{filename} was copied to clipboard', file = vs)
