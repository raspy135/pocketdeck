import ls
import pdeck

def main(vs, args):
  if len(args) == 1:
    print("Usage: cat file [file..]", file=vs)
    return

  args = args[1:]
  ls_list=[]
  for arg in args:
    ls_list.append(ls.list_file(arg))
  
  for argno,ls_item in enumerate(ls_list):
    if not ls_item:
      print(f"Error at '{args[argno]}'", file=vs)
      break
      
    for file in ls_item[1]:
      try:
        filename = ls_item[0] + '/' + file
        with open(filename,"r") as f:
          c = f.read()
          vs.write(c)
          vs.write("\n")
      except Exception as e:
        print(f"Error at '{args[argno]}'", file=vs)
        return
  

