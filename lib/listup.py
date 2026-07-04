import os
import pdeck


def main(vs, args):
  if len(args) != 2:
    print('Usage: listup filename', file=vs)
    return

  filename = args[1]

  try:
    os.stat(filename)
  except OSError:
    print('File not found: %s' % filename, file=vs)
    return

  try:
    pdeck.shared_filelist(filename)
    print('Listed: %s' % filename, file=vs)
  except Exception as e:
    print('Failed to list file: %s' % e, file=vs)
