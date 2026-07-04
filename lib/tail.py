import argparse


def _decode(data):
  # Trim a leading partial UTF-8 sequence left by a byte-count cut.
  for trim in range(4):
    try:
      return (data[trim:] if trim else data).decode('utf-8')
    except UnicodeError:
      pass
  return ''.join(chr(b) for b in data)


def _tail_bytes(vs, data, n):
  vs.write(_decode(data[-n:] if n else b''))
  return 0


def _tail_lines(vs, lines, n):
  buf = []
  for line in lines:
    if len(buf) >= n:
      buf.pop(0)
    buf.append(line.rstrip('\n'))
  for line in buf:
    print(line, file=vs)
  return 0


def _tail_file(vs, path, n, nbytes):
  try:
    if nbytes is not None:
      with open(path, 'rb') as f:
        size = f.seek(0, 2)
        f.seek(size - nbytes if nbytes < size else 0)
        return _tail_bytes(vs, f.read(), nbytes)
    with open(path, 'r') as f:
      return _tail_lines(vs, f, n)
  except OSError as e:
    print('tail: cannot open {}: {}'.format(path, e), file=vs)
    return 1


def main(vs, args_in):
  parser = argparse.ArgumentParser(description='print last lines of files')
  parser.add_argument('-n', type=int, default=10, help='number of lines')
  parser.add_argument('-c', type=int, default=None, help='number of bytes')
  parser.add_argument('files', nargs='*', help='file paths')

  try:
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return

  # No file (or '-'): read piped stdin if the shell provided any.
  if not args.files or args.files == ['-']:
    import pstdin
    if pstdin.has():
      if args.c is not None:
        _tail_bytes(vs, pstdin.take().encode('utf-8'), args.c)
      else:
        _tail_lines(vs, iter(pstdin.take().splitlines()), args.n)
    else:
      print('Usage: tail [-n N | -c N] file [file...]', file=vs)
    return

  first = True
  for path in args.files:
    if len(args.files) > 1:
      if not first:
        print('', file=vs)
      print('==> {} <=='.format(path), file=vs)
    _tail_file(vs, path, args.n, args.c)
    first = False
