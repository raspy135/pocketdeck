import math
import array

pi = 3.14126536

dc = { \
  "/ (2 * 3.1415926536)" : 1.0 / (2 * 3.1415926536),
  "0.5 * pi" : (0.5 * pi)
}


sin_tablesize:int = 1024
sin_table = array.array('f', bytearray(4*sin_tablesize))

tablemask:int = 0x3ff
fp_sin_table = array.array('i',bytearray(sin_tablesize*4))

def gen_sin():
  for i in range(sin_tablesize):
      sin_table.append(math.sin(i * (2*pi/sin_tablesize)))

def gen_fp_sin(shift):
  for i in range(sin_tablesize):
      fp_sin_table[i] = (int((1 << shift) * math.sin(i * (2*pi/sin_tablesize))))
      
def sin(angle):
  index = int(angle * (sin_tablesize * 0.1591583))
  while True:
    if index < 0:
      index += sin_tablesize
    elif index >= sin_tablesize:
      index -= sin_tablesize
    else:
      break
  return sin_table[index]    

def cos(angle):
  return sin(angle + dc['0.5 * pi'])


def fp_cos(angle: object) -> int:
  index: int = int((angle + dc['0.5 * pi']) * (sin_tablesize * 0.1591583))
  return fp_sin_d(index)  
  
def fp_sin(angle: object) -> int:
  index: int = int(angle * (sin_tablesize * 0.1591583))
  return fp_sin_d(index)  


@micropython.viper
def fp_sin_d(index: int) -> int:
  ts: int = int(sin_tablesize)
  table: ptr32 = ptr32(fp_sin_table)
  index &= int(tablemask)
  return table[index]

#@micropython.native
#def fp_cos(angle):
#  return fp_sin(angle + dc['0.5 * pi'])

