import esclib
import pdeck
import time
import math
import audio
import array
import random
from pie import Pie, PieWavetable

def generate_sine(size):
  data = bytearray(size * 2)
  for i in range(size):
    val = int(24000 * math.sin(2 * math.pi * i / size))
    data[2*i] = val & 0xFF
    data[2*i+1] = (val >> 8) & 0xFF
  return data

def main(vs, args):
  
  p = Pie(bpm=120)
  with PieWavetable(1) as synth:
    sine = generate_sine(256)
    synth.dev.set_wavetable(0, [sine])
    synth.dev.volume(0, 0.6)
    
    p.add(synth, p.pattern(synth, "c4").clip("1.0"))
    
    with p:
      while True:
        p.process_event()
        time.sleep(0.1)
        key = vs.v.read_nb(1)
        if key and key[0] > 0:
          break
    

