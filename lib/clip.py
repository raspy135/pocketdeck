import pdeck


def main(vs, args):
  if len(args) < 2:
    print('Usage: clip filename', file=vs)
    return

  filename = args[1]
  data = pdeck.clipboard_paste()
  if data is None:
    data = ''

  with open(filename, 'w') as f:
    f.write(data)

  print('Saved clipboard to {}'.format(filename), file=vs)
