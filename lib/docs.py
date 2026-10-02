import gpt
import argparse
import os
def main(vs, args_in):
  parser = argparse.ArgumentParser(vs=vs,
            description='Pocket Deck documentation AI search' )
  parser.add_argument('-j', '--jp',action='store_true',help='Answer in Japanese')
  parser.add_argument('-j', '--jp',action='store_true',help='Answer in Japanese')
  parser.add_argument('content', nargs='*',help='Content to ask')
  args = parser.parse_args(args_in[1:-1])
  dir_list=os.listdir('/sd/Documents/pd')
  file_list = []
  #for file in dir_list:
  #  if file[-3:] == '.md' and file != 'release_notes.md':
  #    file_list.append("pd/" + file)
  file_list = [ "pd/README.md", "pd/pem_readme.md", "pd/journal_readme.md","pd/music_readme.md","pd/ssh_scp_readme.md","pd/tasks_readme.md","pd/gpt_readme.md"]
      
  ex1 = "and answer in Japanese" if args.jp else  ""
  ex1 += " Answer short if possible."
  #print(file_list, file=vs)
  arg_list = ['gpt','-f']
  arg_list.extend(file_list)
  arg_list.append('-q')
  arg_list.extend(args.content)
  arg_list.extend(ex1)
  #print(arg_list, file=vs)
  gpt.main(vs,arg_list)


