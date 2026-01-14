import pdeck
import audio
import array
import time
import os
import pdeck_utils as pu

pu.reimport('wav_play')

def main(vs, args):
  tracknum = 0
  folder_name = 'rasmus'
    
  #audio.sample_rate(44100)
  #wp = wav_play("/sd/data/Project_12.wav")
  #wp = wav_play("/sd/data/tape3.wav")
  wp = wav_play.wav_play(20000)
  
  if len(args) >= 2:
    folder_name=args[1]
  if len(args) >= 3:
    tracknum=int(args[2])-1

  file_list = os.listdir("/sd/music/" + folder_name)
  print(file_list, file = vs)
  intr = False
  cur_track = tracknum
  
  while cur_track < len(file_list):  
    print(f"Playing track {cur_track+1}", file = vs)
    wp.open("/sd/music/" + folder_name + '/' + file_list[cur_track])
    wp.play()
    #time.sleep(1)
    pdeck.delay_tick(50)
    
    while(audio.stream_play()):
      pdeck.delay_tick(50)
      ret = vs.v.read_nb(1)
      if ret and ret[0] > 0:

        keys = ret[1].encode('ascii')
        #print(keys, file=vs)
        if keys == b'\x1b':
          seq = [ keys ]
        
          seq.append( vs.read(1).encode('ascii') )
          if seq[-1] == b'[':
            seq.append( vs.read(1).encode('ascii'))
          if seq[-1] >= b'0' and seq[-1] <= b'9':
            seq.append( vs.read(1).encode('ascii'))
          keys = b''.join(seq)
        print(keys)
        #intr = True
        # RIGHT
        if keys == b'\x1b[C':
          break
        # LEFT
        if keys == b'\x1b[D':
          cur_track -= 2
          break
        if keys == b'q' or keys == b'\b':
          intr = True
          break
    wp.stop()
    wp.close()
    cur_track += 1
    if cur_track < 0:
      cur_track = 0
    if intr:
      break
  audio.sample_rate(24000)
  print('Finished.',file=vs)


