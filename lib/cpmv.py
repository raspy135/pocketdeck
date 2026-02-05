import os

def check_src_dst_names(vs, src,dst):
  basename = src.rsplit('/',1)[-1]
    
  try:
    st = os.stat(src)
  except OSError as e:
    print("Source file is not correct", file=vs)
    return
    
  #0x4000 means directory
  if bool(st[0]&0x4000):
    print("Source file is a directory", file=vs)
    return
    

  if dst[-1] =='/':
    dst = dst[:-1]
  try:
    st = os.stat(dst)
  except OSError as e:
    if e.errno == 22:
      print("Destination not found", vs = file)
  

  #0x4000 means directory
  if bool(st[0]&0x4000):
    dst = dst + '/' + basename
  
  return (src,dst)
