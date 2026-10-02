import argparse

def _unescape(s):
  # Interpret backslash escape sequences like echo -e on Unix.
  out = []
  i = 0
  while i < len(s):
    c = s[i]
    if c == '\\' and i + 1 < len(s):
      n = s[i + 1]
      if n == 'n':
        out.append('\n')
      elif n == 't':
        out.append('\t')
      elif n == 'r':
        out.append('\r')
      elif n == 'a':
        out.append('\a')
      elif n == 'b':
        out.append('\b')
      elif n == 'f':
        out.append('\f')
      elif n == 'v':
        out.append('\v')
      elif n == '\\':
        out.append('\\')
      elif n == '0':
        # \0NNN octal character code (1-3 octal digits)
        j = i + 2
        digits = ''
        while j < len(s) and len(digits) < 3 and '0' <= s[j] <= '7':
          digits += s[j]
          j += 1
        if digits:
          out.append(chr(int(digits, 8)))
          i = j - 1
        else:
          out.append('\\')
      else:
        out.append('\\')
        out.append(n)
      i += 2
    else:
      out.append(c)
      i += 1
  return ''.join(out)

def main(vs, args_in):
  parser = argparse.ArgumentParser(vs=vs,
            description='display a line of text')
  parser.add_argument('-n', action='store_true', help='do not output the trailing newline')
  parser.add_argument('-e', action='store_true', help='enable interpretation of backslash escapes')
  parser.add_argument('-E', action='store_true', help='disable interpretation of backslash escapes (default)')
  parser.add_argument('text', nargs='*', help='text to output')

  args = parser.parse_args(args_in[1:])

  s = ' '.join(args.text)
  if args.e:
    s = _unescape(s)

  end = '' if args.n else '\n'
  print(s, end=end, file=vs)
