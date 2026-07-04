import argparse


def _head_lines(vs, lines, n):
  count = 0
  for line in lines:
    print(line.rstrip('\n'), file=vs)
    count += 1
    if count >= n:
      break
  return 0


def _head_file(vs, path, n):
  try:
    with open(path, 'r') as f:
      return _head_lines(vs, f, n)
  except OSError as e:
    print('head: cannot open {}: {}'.format(path, e), file=vs)
    return 1


def main(vs, args_in):
  parser = argparse.ArgumentParser(description='print first lines of files')
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
      _head_lines(vs, iter(pstdin.take().splitlines()), args.n)
    else:
      print('Usage: head [-n N] file [file...]', file=vs)
    return

  first = True
  for path in args.files:
    if len(args.files) > 1:
      if not first:
        print('', file=vs)
      print('==> {} <=='.format(path), file=vs)
    _head_file(vs, path, args.n)
    first = False
