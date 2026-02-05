import pdeck
import os


def main(vs,args):
  if len(args) != 2:
    q = '.'
  else:
    q = args[1]
    
  try:
    os.chdir(q)
  except Exception as e:
    if hasattr(e, 'errno') and e.errno == 2:
      print('Directory not found', file = vs)
      return
    print('Error')
    return
  
  curdir = os.getcwd()

  print(f'Directory switched to {curdir}', file=vs)
  

