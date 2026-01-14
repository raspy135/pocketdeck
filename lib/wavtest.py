import pdeck
import audio
import array
import time

import wav_play

def main(vs, args):
  wp = wav_play.wav_play(args[1])
  #time.sleep(10)
  wp.play()
  while(audio.stream_play()):
    pdeck.delay_tick(50)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break 
  wp.stop()
  wp.close()
