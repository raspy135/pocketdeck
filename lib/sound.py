from machine import Pin,I2C,I2S
import time
import pdeck
import array
import math
import dsp_utils
import pdeck_utils as pu
import audio

#pu.reimport('codec_config')
import codec_config

def main(vs, args):
  obj = codec_config.codec_config()
  audio.power(True)
  if args[1] == 'dacvol':
    vol = int(args[2])
    if vol < 0:
      vol = 256+vol
    obj.set_vol(vol)
    print("Volume changed", file = vs)
  elif args[1] == 'hpg':
    vol = int(args[2])
    obj.set_hpgain(vol)
    print("HPGain changed", file = vs)
  elif args[1] == 'lo':
    if len(args) == 2:
      ret = obj.get_lo()
      print(f"LO setting: {ret}", file = vs)
    else:
      val = int(args[2])
      obj.toggle_lo(False if val == 0 else True)
      print("LO setting changed", file = vs)
    
  elif args[1] == 'li':
    val = int(args[2])
    obj.toggle_li(False if val == 0 else True)
    print("LI setting changed", file = vs)

  elif args[1] == 'monvol':
    val = int(args[2])
    obj.set_input_mixer(val)
    print("Monitor volume changed", file = vs)

  elif args[1] == 'micg':
    vol = int(args[2])
    obj.set_micgain(vol)
    print("Mic gain changed", file = vs)
  elif args[1] == 'mong':
    vol = int(args[2])
    obj.set_monitorgain(vol)
    print("Monitor gain changed", file = vs)

  else:
    print("Available commands", file=vs)
    print("sound dacvol [vol]", file = vs)

