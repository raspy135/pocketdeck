import pdeck
import os
import argparse
import ls

DIR_BIT = 0x4000

def _is_dir(path):
  try:
    st = os.stat(path)
    return (st[0] & DIR_BIT) != 0
  except OSError:
    return False

def _join(base, name):
  if base == '/':
    return '/' + name
  if base == '' or base == '.':
    return name
  return base + '/' + name

def _norm(path):
  while len(path) > 1 and path[-1] == '/':
    path = path[:-1]
  return path

def _expand_flags(args):
  # This argparse does not accept clustered short flags, but 'rm -rf x' is the
  # reflexive thing to type, so split '-rf' into '-r' '-f' before parsing.
  out = []
  for a in args:
    if len(a) > 2 and a[0] == '-' and a[1] != '-':
      for ch in a[1:]:
        out.append('-' + ch)
    else:
      out.append(a)
  return out

def _collect(arg, recursive):
  # Resolve one argument through ls.list_file(), so wildcards behave exactly
  # like they do in ls. Returns (files, dirs, error_message).
  # Directories are never deleted here: use rmdir for those.
  target = _norm(arg)
  if _is_dir(target):
    if not recursive:
      return [], [], ("is a directory. Use 'rmdir " + target +
        "', or 'rm -r " + arg + "' to delete the files inside it")
    ret = ls.list_file(target, True)
  else:
    ret = ls.list_file(arg, recursive)

  if not ret:
    return [], [], None

  files = []
  dirs = []
  groups = ret if recursive else [ret]
  for group in groups:
    dirname = group[0]
    for item in group[1]:
      full = _join(dirname, item)
      if _is_dir(full):
        dirs.append(full)
      else:
        files.append(full)
  return files, dirs, None

def _usage(vs):
  print('rm file [file ...]', file=vs)
  print('', file=vs)
  print('  -r, --recursive  match files in subdirectories too', file=vs)
  print('  -n, --dry-run    show what would be deleted, delete nothing', file=vs)
  print('  -f, --force      do not report arguments that match nothing', file=vs)
  print('', file=vs)
  print('Flags may be combined: rm -rf dir/*.log', file=vs)
  print('Wildcards (*) allowed. Directories are never removed: use rmdir.', file=vs)

def main(vs, args_in):
  # argparse here raises SystemExit(0) on -h without printing to our stream.
  if '-h' in args_in[1:] or '--help' in args_in[1:]:
    _usage(vs)
    return

  parser = argparse.ArgumentParser(description='remove files')
  parser.add_argument('-r', '--recursive', action='store_true',
      help='match files in subdirectories too (directories themselves are never removed)')
  parser.add_argument('-n', '--dry-run', action='store_true',
      help='show what would be deleted, delete nothing')
  parser.add_argument('-f', '--force', action='store_true',
      help='do not report arguments that match nothing')
  parser.add_argument('paths', nargs='*', help='File(s) to remove. Wildcards (*) allowed')

  args = parser.parse_args(_expand_flags(args_in[1:]))

  if len(args.paths) == 0:
    _usage(vs)
    return

  targets = []
  missing = 0
  problems = 0

  for p in args.paths:
    files, dirs, err = _collect(p, args.recursive)
    if err:
      print(f'rm: \'{p}\' {err}', file=vs)
      problems += 1
      continue
    for d in dirs:
      print(f'rm: {d} is a directory, skipping', file=vs)
      problems += 1
    if len(files) == 0 and len(dirs) == 0:
      if not args.force:
        print(f'rm: no such file: {p}', file=vs)
      missing += 1
      continue
    targets.extend(files)

  if len(targets) == 0:
    return

  if args.dry_run:
    for f in targets:
      print(f'would delete {f}', file=vs)
    print(f'{len(targets)} file(s) would be deleted', file=vs)
    return

  deleted = 0
  for f in targets:
    try:
      os.unlink(f)
      print(f, file=vs)
      deleted += 1
    except Exception as e:
      print(f'rm: failed to delete {f}: {e}', file=vs)
      problems += 1

  os.sync()
  if deleted:
    print('Deleted', file=vs)
  if problems:
    print(f'{problems} item(s) not deleted', file=vs)
  if missing and not args.force:
    print(f'{missing} argument(s) matched nothing', file=vs)
