import pdeck
import os
import ls

def main(vs,args):
  if len(args) != 2:
    print("rm file", file = vs)
    return

  ret = ls.list_file(args[1])
  if ret:
    for item in ret[1]:
      fullpath = ret[0] + '/' + item
      st = os.stat(fullpath)
      if st[0]&0x4000 != 0:
        print(f'{fullpath} is a directly, skipping', file=vs)
        continue
      print(f'{ret[0]}/{item} ', file=vs)
      os.unlink(fullpath)

  os.sync()
  print("Deleted", file = vs)

