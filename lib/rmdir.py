import pdeck
import os
def main(vs,args):
  if len(args) != 2:
    print("usage: rmdir dir_name", file=vs)
    return
  try:
    os.rmdir(args[1])
  except OSError as e:
    print("Failed to remove", args[1], e, file=vs)
    return
  os.sync()
  print("Directory deleted", file=vs)
