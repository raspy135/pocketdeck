import argparse


def _tail_lines(vs, lines, n):
  buf = []
  for line in lines:
    if len(buf) >= n:
      buf.pop(0)
    buf.append(line.rstrip('\n'))
  for line in buf:
    print(line, file=vs)
  return 0


def _tail_file(vs, path, n):
  try:
    with open(path, 'r') as f:
      return _tail_lines(vs, f, n)
  except OSError as e:
    print('tail: cannot open {}: {}'.format(path, e), file=vs)
    return 1


def main(vs, args_in):
  parser = argparse.ArgumentParser(description='print last lines of files')
  parser.add_argument('-n', type=int, default=10, help='number of lines')
  parser.add_argument('files', nargs='*', help='file paths')

  try:
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return

  # No file (or '-'): read piped stdin if the shell provided any.
  if not args.files or args.files == ['-']:
    import pstdin
    if pstdin.has():
      _tail_lines(vs, iter(pstdin.take().splitlines()), args.n)
    else:
      print('Usage: tail [-n N] file [file...]', file=vs)
    return

  first = True
  for path in args.files:
    if len(args.files) > 1:
      if not first:
        print('', file=vs)
      print('==> {} <=='.format(path), file=vs)
    _tail_file(vs, path, args.n)
    first = False
