import pdeck
import os
import ls

def _is_dir(path):
  try:
    st = os.stat(path)
    return (st[0] & 0x4000) != 0
  except OSError:
    return False

def main(vs,args):
  if len(args) != 2:
    print("rm file", file = vs)
    return

  # Guard: a bare directory argument used to expand to "every file inside",
  # silently deleting all of its contents (and `rm .` wiped the cwd).
  # Refuse it; directories are removed with `rmdir`, contents with a wildcard.
  target = args[1]
  if len(target) > 1 and target[-1] == '/':
    target = target[:-1]
  if _is_dir(target):
    print(f"rm: '{args[1]}' is a directory", file=vs)
    print(f"Use 'rmdir {args[1]}' to remove it, or 'rm {target}/*' to delete its files", file=vs)
    return

  ret = ls.list_file(args[1])
  if ret:
    for item in ret[1]:
      fullpath = ret[0] + '/' + item
      st = os.stat(fullpath)
      if st[0]&0x4000 != 0:
        print(f'{fullpath} is a directory, skipping', file=vs)
        continue
      print(f'{ret[0]}/{item} ', file=vs)
      os.unlink(fullpath)

  os.sync()
  print("Deleted", file = vs)

