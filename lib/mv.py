import pdeck
import os
import cpmv

def main(vs,args):
  if len(args) != 3:
    print("mv src dst", file = vs)
    return
  ret = cpmv.check_src_dst_names(vs, args[1], args[2], True)
  if not ret:
    return
  src, dst = ret
  print(f"{src} => {dst}", file=vs)
  os.rename(src, dst)    
  os.sync()
  print("Renamed", file = vs)

