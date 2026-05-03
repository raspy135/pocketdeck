import os
import argparse
import ls

def _is_dir(path):
  try:
    st = os.stat(path)
    return (st[0] & 0x4000) != 0
  except OSError:
    return False

def _join_path(base, name):
  if base == '/':
    return '/' + name
  if base == '' or base == '.':
    return name
  return base + '/' + name

def _basename(path):
  if path == '/':
    return '/'
  parts = path.split('/')
  while len(parts) > 1 and parts[-1] == '':
    parts.pop()
  if len(parts) == 0:
    return path
  return parts[-1]

def _normalize_dir_path(path):
  if path == '/':
    return '/'
  while len(path) > 1 and path[-1] == '/':
    path = path[:-1]
  return path

def _copy_file(src, dst):
  try:
    fsrc = open(src, 'rb')
  except Exception:
    return False, 'Failed to open source file: ' + src

  try:
    fdst = open(dst, 'wb')
  except Exception:
    fsrc.close()
    return False, 'Failed to open destination file: ' + dst

  try:
    while True:
      data = fsrc.read(1024)
      if not data:
        break
      fdst.write(data)
  except Exception:
    fsrc.close()
    fdst.close()
    return False, 'Failed while copying: ' + src

  fsrc.close()
  fdst.close()
  return True, None

def _collect_sources(src, recursive):
  ret = ls.list_file(src, recursive)
  if not ret:
    return None

  out = []
  if recursive:
    for group in ret:
      dirname = group[0]
      filelist = group[1]
      for item in filelist:
        full = _join_path(dirname, item)
        if not _is_dir(full):
          out.append(full)
  else:
    dirname = ret[0]
    filelist = ret[1]
    for item in filelist:
      full = _join_path(dirname, item)
      if not _is_dir(full):
        out.append(full)

  if len(out) == 0:
    return None
  return out

def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='copy file')
  parser.add_argument('-r', '--recursive', action='store_true', help='search recursively')
  parser.add_argument('src', help='Source path')
  parser.add_argument('dst', help='Destination path')

  args = parser.parse_args(args_in[1:])

  src_files = _collect_sources(args.src, args.recursive)
  if not src_files:
    print('No matched files', file=vs)
    return

  dst_path = _normalize_dir_path(args.dst)
  dst_is_dir = _is_dir(dst_path) or (len(args.dst) > 1 and args.dst[-1] == '/')

  if not dst_is_dir and len(src_files) > 1:
    print('Destination must be a directory when copying multiple files', file=vs)
    return

  copied = 0

  for src in src_files:
    if dst_is_dir:
      dst = _join_path(dst_path, _basename(src))
    else:
      dst = dst_path

    ok, err = _copy_file(src, dst)
    if not ok:
      print(err, file=vs)
      return

    copied += 1

  if copied == 1:
    print('Copied 1 file', file=vs)
  else:
    print('Copied ' + str(copied) + ' files', file=vs)
