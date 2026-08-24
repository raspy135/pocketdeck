import argparse


def _normalize_args(args):
  # Traditional form: 'head -50 file' means 'head -n 50 file'.
  out = []
  prev = None
  for a in args:
    if a[:1] == '-' and a[1:].isdigit() and prev not in ('-n', '-c'):
      out.append('-n')
      out.append(a[1:])
    else:
      out.append(a)
    prev = a
  return out


def _decode(data):
  # Trim a trailing partial UTF-8 sequence left by a byte-count cut.
  for trim in range(4):
    try:
      return (data[:-trim] if trim else data).decode('utf-8')
    except UnicodeError:
      pass
  return ''.join(chr(b) for b in data)


def _head_bytes(vs, data, n):
  vs.write(_decode(data[:n]))
  return 0


def _head_lines(vs, lines, n):
  count = 0
  for line in lines:
    print(line.rstrip('\n'), file=vs)
    count += 1
    if count >= n:
      break
  return 0


def _head_file(vs, path, n, nbytes):
  try:
    if nbytes is not None:
      with open(path, 'rb') as f:
        return _head_bytes(vs, f.read(nbytes), nbytes)
    with open(path, 'r') as f:
      return _head_lines(vs, f, n)
  except OSError as e:
    print('head: cannot open {}: {}'.format(path, e), file=vs)
    return 1


def main(vs, args_in):
  parser = argparse.ArgumentParser(description='print first lines of files')
  parser.add_argument('-n', type=int, default=10, help='number of lines')
  parser.add_argument('-c', type=int, default=None, help='number of bytes')
  parser.add_argument('files', nargs='*', help='file paths')

  try:
    args = parser.parse_args(_normalize_args(args_in[1:]))
  except SystemExit:
    return

  # No file (or '-'): read piped stdin if the shell provided any.
  if not args.files or args.files == ['-']:
    import pstdin
    if pstdin.has():
      if args.c is not None:
        _head_bytes(vs, pstdin.take().encode('utf-8'), args.c)
      else:
        _head_lines(vs, iter(pstdin.take().splitlines()), args.n)
    else:
      print('Usage: head [-n N | -c N] file [file...]', file=vs)
    return

  first = True
  for path in args.files:
    if len(args.files) > 1:
      if not first:
        print('', file=vs)
      print('==> {} <=='.format(path), file=vs)
    _head_file(vs, path, args.n, args.c)
    first = False
