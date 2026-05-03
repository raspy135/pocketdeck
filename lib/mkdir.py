import pdeck
import os
def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

def main(vs,args):
  if len(args) != 2:
    print("Usage: mkdir folder_name", file=vs)
    return
  try:
    if file_exists(args[1]):
      print(f"{args[1]} Exists", file=vs)
    else:
      os.mkdir(args[1])
      print("Directry created", file = vs)
  except Exception as e:
    print("Error in makedir", file=vs)
  os.sync()

