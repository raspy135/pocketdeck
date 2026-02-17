import gpt
import argparse

def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='Dictionary search powered by ChatGPT' )
  parser.add_argument('-j', '--jp',action='store_true',help='Answer in Japanese')
  args = parser.parse_args(args_in[1:-1])
  
  ex1 = "and answer in Japanese" if args.jp else  ""
  
  gpt.main(vs, ['gpt','-n',f'What does "{args_in[-1]}" mean? Answer in short {ex1}.'])


