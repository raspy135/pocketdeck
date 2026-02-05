import pdeck
import os
def main(vs,args):
  try:
    os.mkdir(args[1])
  except FileNotFoundError:
    v.print("File not found\n")
  os.sync()
  print("Directry created", file = vs)

