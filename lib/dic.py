import gpt
import argparse


def main(vs, args_in):
  parser = argparse.ArgumentParser(vs=vs,
            description='Dictionary search powered by ChatGPT')
  parser.add_argument('-j', '--jp', action='store_true', help='Answer in Japanese')
  parser.add_argument('-m', '--model', action='store', default=None, help='Model to use: a name from /config/gpt.json, or a raw model id. Default: the registry default.')
  parser.add_argument('-nf', '--no-format', action='store_true', help='do not format text (No bold)')
  parser.add_argument('word', nargs='?', help='Word to look up')

  try:
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return

  if not args.word:
    print("usage: dic [-j] [-m MODEL] [-nf] word", file=vs)
    return

  ex1 = "and answer in Japanese" if args.jp else ""

  cmd = ['gpt']
  if args.model:
    cmd += ['-m', args.model]
  if args.no_format:
    cmd += ['-nf']
  cmd += ['-na', '-s', '-n', f'What does "{args.word}" mean? Answer in short {ex1}.']
  gpt.main(vs, cmd)
