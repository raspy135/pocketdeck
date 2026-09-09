import pdeck
import os
import cpmv
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
  parts = path.split('/')
  while len(parts) > 1 and parts[-1] == '':
    parts.pop()
  return parts[-1]

def _expand(vs, src):
  # Wildcard: expand through ls. Literal path: keep as-is (also matches dirs).
  if '*' in src or '?' in src:
    ret = ls.list_file(src, False)
    if not ret:
      return None
    dirname, filelist = ret[0], ret[1]
    out = [_join_path(dirname, item) for item in filelist]
    if len(out) == 0:
      return None
    return out
  try:
    os.stat(src)
  except OSError:
    print("Source file is not correct", file=vs)
    return None
  return [src]

def main(vs, args):
  if len(args) < 3:
    print("mv src [src ...] dst", file=vs)
    return
  dst_arg = args[-1]
  srcs = []
  for s in args[1:-1]:
    exp = _expand(vs, s)
    if exp is None:
      return
    srcs += exp

  dst_is_dir = _is_dir(dst_arg) or dst_arg[-1] == '/'

  if len(srcs) > 1 and not dst_is_dir:
    print("Destination must be a directory when moving multiple files", file=vs)
    return

  if len(srcs) == 1 and not dst_is_dir:
    ret = cpmv.check_src_dst_names(vs, srcs[0], dst_arg, True)
    if not ret:
      return
    srcs, dst_arg = [ret[0]], ret[1]

  moved = 0
  for src in srcs:
    if dst_is_dir:
      dst = _join_path(dst_arg.rstrip('/') or '/', _basename(src))
    else:
      dst = dst_arg
    print(f"{src} => {dst}", file=vs)
    try:
      os.rename(src, dst)
    except OSError as e:
      print("Failed to rename:", src, e, file=vs)
      return
    moved += 1
  os.sync()
  if moved == 1:
    print("Renamed", file=vs)
  else:
    print("Renamed " + str(moved) + " files", file=vs)
