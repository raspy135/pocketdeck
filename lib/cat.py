import pdeck

def main(vs, args):
  v = vs.v
  # v.print(args[1])
  try:
    with open(args[1],"r") as f:
      c = f.read()
      v.print(c)
      v.print("\n")
  except FileNotFoundError:
    v.print("File not found\n")

