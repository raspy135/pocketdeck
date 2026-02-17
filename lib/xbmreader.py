import re
import re_findall
import pdeck
import array
import struct

v = pdeck.vscreen()

def read_bytes(regex, line):
  #ret = re_findall.findall(regex, line)
  #bline = line.encode('utf-8')
  ret = []
  i = 0
  while i < len(line):
    ch = line[i]
    if ch == 'x':
      num = line[i-1:i+3]
      b = int(num,16)
      # Swap the bit order
      b = ((b&0x80) >> 7) | ((b&0x40) >> 5) | ((b&0x20) >> 3) |((b&0x10) >> 1) | ((b&0x08) << 1) | ((b&0x04) << 3) | ((b&0x02) << 5) | ((b&0x01) << 7)
      #yield b.to_bytes(1,'little')  
      #print(b)
      yield b
      
      i += 5
    else:
      i += 1

def read_xbmr(filename):
  out = None #bytearray()
  idx = 0
  line_num = 0
  with open(filename, "rb") as file:
    content = file.read()
    
  mcontent = memoryview(content)
  header = struct.unpack("<hhhh", content)
  return (filename,  header[2], header[3], mcontent[8:], header[1])
  
def read(filename):
  out = None #bytearray()
  idx = 0
  line_num = 0
  with open(filename, "r") as file:
    content = file.read()
  #print(f'len = {len(content)}')
  regex = re.compile("[\r\n]+")
  lines = regex.split(content)
  regex_byte = re.compile("(0x..)")

  for line in lines:
    #v.print("Content {}: {}\n".format(str(line_num), line))
    if line_num == 0:
      result = re.search("width ([0-9]+)$", line)
      if result != None:
        width = int(result.group(1))
        #print(f"Width {width}\n")
        width_b = (width+7) // 8 * 8
    if line_num == 1:
      result = re.search("height ([0-9]+)$", line)
      if result != None:
        height = int(result.group(1))
        #print(f"Height {height}\n");
    if line_num == 2:
      result = re.search("\s([\w\-]+)_bits", line)
      if result != None:
        name = result.group(1)
        #print("Name {}\n".format(name))
        out = array.array('B', bytearray(width_b*height))
    if line_num > 2:
      nums = tuple(read_bytes(regex_byte, line))
      for num in nums:
        #print(f"idx,num = {idx},{num}")
        out[idx] = num
        idx += 1
    line_num += 1
  return (name,  width, height, memoryview(bytes(out)), 1)

def scale_one(one, scale):
  r = bytearray()
  if scale == 2:
    r.append(
          (one &0x80) + ((one & 0x80) >> 1)
         +((one&0x40) >> 1) + ((one&0x40) >> 2)
         +((one&0x20) >> 2) + ((one&0x20) >> 3)
         +((one&0x10) >> 3) + ((one&0x10) >> 4)
         )
    r.append(
         ((one&0x8) << 4) + ((one&0x8) << 3)
         +((one&0x4) << 3) + ((one&0x4) << 2)
         +((one&0x2) << 2) + ((one&0x2) << 1)
         +((one&0x1) << 1) + ((one&0x1))
         )
  return r
    
def scale(data, scale):
  out = bytearray()
  line = bytearray()  
  for idx,one in enumerate(data[3]):
    scaled = scale_one(one, scale)
    line.extend(scaled)
    if idx % (data[1]>>3) == ((data[1]>>3) - 1):
      out.extend(line)
      if scale == 2:
        out.extend(line)
      line = bytearray()
  return (data[0],data[1]*scale,data[2]*scale, memoryview(bytes(out)), data[4])


def gen_shift_images(data):
  out = bytearray()
  line = bytearray()  
  mask_list = ( 0x80, 0xc0, 0xe0, 0xf0, 0xf8, 0xfc, 0xfe )
  for shift in range(0,8):
    extra_data=0
    for idx,one in enumerate(data[3]):
      extra_mask = mask_list[shift - 1]
      shifted = (one << shift) | extra_data >> (8 - shift)
      extra_data = one & extra_mask
      line.append(shifted)
        
      if idx % (data[1]>>3) == ((data[1]>>3) - 1):
        line.append( extra_data >> (8 - shift))
        out.extend(line)
        line = bytearray()
        extra_data = 0
  return (data[0],data[1]+8,data[2], bytes(out))


