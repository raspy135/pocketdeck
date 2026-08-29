import pdeck
import os
import ls

def _is_dir(path):
  try:
    st = os.stat(path)
    return (st[0] & 0x4000) != 0
  except OSError:
    return False

def _rm_one(vs, arg):
  # Guard: a bare directory argument used to expand to "every file inside",
  # silently deleting all of its contents (and `rm .` wiped the cwd).
  # Refuse it; directories are removed with `rmdir`, contents with a wildcard.
  target = arg
  if len(target) > 1 and target[-1] == '/':
    target = target[:-1]
  if _is_dir(target):
    print(f"rm: '{arg}' is a directory", file=vs)
    print(f"Use 'rmdir {arg}' to remove it, or 'rm {target}/*' to delete its files", file=vs)
    return False

  ret = ls.list_file(arg)
  if ret:
    for item in ret[1]:
      fullpath = ret[0] + '/' + item
      st = os.stat(fullpath)
      if st[0]&0x4000 != 0:
        print(f'{fullpath} is a directory, skipping', file=vs)
        continue
      print(f'{ret[0]}/{item} ', file=vs)
      os.unlink(fullpath)
  return True

def main(vs,args):
  if len(args) < 2:
    print("rm file [file ...]", file = vs)
    return

  deleted = 0
  for arg in args[1:]:
    if _rm_one(vs, arg):
      deleted += 1
  os.sync()
  if deleted:
    print("Deleted", file = vs)
