import os

def check_src_dst_names(vs, src,dst, allow_dir = False):
  basename = src.rsplit('/',1)[-1]
  try:
    st = os.stat(src)
  except OSError as e:
    print("Source file is not correct", file=vs)
    return
    
  #0x4000 means directory
  src_st = st
  if bool(st[0]&0x4000) and not allow_dir:
    print("Source file is a directory", file=vs)
    return
    

  if dst[-1] =='/':
    dst = dst[:-1]
  try:
    st = os.stat(dst)
  except OSError as e:
    if e.errno == 22:
      print("Destination not found", vs = file)
  

  # If src is file and dst is not file, add basename
  if not bool(src_st[0]&0x4000) and bool(st[0]&0x4000):
    dst = dst + '/' + basename
  
  return (src,dst)
