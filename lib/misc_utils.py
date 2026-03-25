import esclib as ec
import pdeck_utils

def input(message):
  vs = pdeck_utils.vscreen_stream()
  return input_vs(vs, message)
  
def input_vs(vs, message):
  elib = ec.esclib()
  vs.v.print(message)
  out=''
  while True:
    key = vs.read(1).encode('utf-8')
    #print(key, file=vs)
    str = key.decode('utf-8')
    if key == b'\x08':
      out = out[:-1]
      vs.v.print(elib.cur_left(1))
      vs.v.print(elib.erase_to_end_of_current_line())
      continue
    vs.v.print(str)
    out += str
    if key == b'\x0d':
      print('', file=vs)
      break
  return out

