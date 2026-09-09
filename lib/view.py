# view - print numbered lines of a file, to locate code for editing.
# Usage: view file [start_line] [count]   (start_line is 1-based, default 1)

def main(vs, args):
  if len(args) < 2:
    print('usage: view file [start_line] [count]', file=vs)
    return
  try:
    f = open(args[1], 'r')
  except OSError:
    print('cannot open', args[1], file=vs)
    return
  lines = f.read().split('\n')
  f.close()
  start = int(args[2]) if len(args) > 2 else 1
  count = int(args[3]) if len(args) > 3 else 40
  if start < 1:
    start = 1
  for i in range(start - 1, min(start - 1 + count, len(lines))):
    print('%4d: %s' % (i + 1, lines[i]), file=vs)
  print('total lines: %d' % len(lines), file=vs)
