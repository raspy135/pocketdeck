import pdeck
import os
import re
import argparse
import time

def is_int(s):
  try:
    int(s)
    return True
  except ValueError:
    return False

def _is_dir(path):
    try:
        st = os.stat(path)
        return (st[0] & 0x4000) != 0  # stat.S_IFDIR (MicroPython uses bitmask)
    except OSError:
        return False

def list_file(q, vs=None):
  filename = ''
  if q[-1] == '/' and len(q) > 1:
    q = q[:-1]
  dirname = q

  ret = None

  if _is_dir(q):
    ret = os.listdir(q)
        
  if ret == None:
    split_folders = q.split('/')
    #if count(split_folders) == 1:
    #  q = 
    filename = split_folders[-1]
    split_folders = split_folders[0:-1]
    print(split_folders)
    print(filename)
    if len(split_folders) == 0:
      q = '.'
    #elif split_folders[0] == '':
    #  q = '/' + '/'.join(split_folders)
    else:
      q = '/'.join(split_folders)
    try:
      print(q)
      dirname = q
      ret = os.listdir(q)
    except Exception as e2:
      print("Directory not found")
      return

  if filename == '':
    filename = '^.*'
  else:
    filename = '^' + filename.replace('.','\.').replace('*','.*') + '$'
    
  #print(f'regex = {filename}', file=vs)
  pat = re.compile(filename)
  
  out = [ dirname ]
  filelist = []
  for file in ret:
    match = pat.search(file)
    if match:
      filelist.append(file)
  if len(filelist) == 0:
    return None

  return [ dirname, filelist ]
  
def main(vs,args_in):
  parser = argparse.ArgumentParser(
            description='list file')
  parser.add_argument('-c', '--clip',action='store',help='Copy specified index filename to clipboard. -1 means the last one', default='-1000')
  parser.add_argument('-l', '--list',action='store_true', help='list files')
  parser.add_argument('path',nargs='?', help='Path', default = '.')

  args = parser.parse_args(args_in[1:])
  
  q = args.path #args[1]
    
  ret = list_file(q)
  if not ret:
    print('No matched files', file=vs)
    return
    
  filelist = ret[1]
  print(f'File in {ret[0]}:', file=vs)
  
  for i, item in enumerate(filelist):
    if args.list:
      st = os.stat(ret[0] + "/" + item)
      t = time.localtime(st[7])
      print(f'{i}: {'[Dir]' if st[0]&0x4000 != 0 else ''} {item} {st[6]:,} {t[0]}/{t[1]}/{t[2]}', file=vs)
    else:
      print(f'{item} ', end='', file=vs)

  if is_int(args.clip):
    file_index = int(args.clip)
    if file_index != -1000:
      print('', file=vs)
      try:
        filename = filelist[file_index]
      except IndexError as e:
        print(f"Index {file_index} was out of range.", file=vs)
        return
      filename = ret[0] + '/' + filename
      pdeck.clipboard_copy(filename)
      print(f'{filename} was copied to clipboard', file = vs)
  
  print('', file=vs)
  
  
