import pdeck
import audio
import array
import time
import pdeck_utils as pu
import codec_config
import wav_play
import argparse

#SAMPLE_RATE = 24000

class stream_record:

  def __init__(self, filename, stream, bufsize = 200000):
    self.filename = filename
    self.last_index = 1
    self.vs = stream
    #self.open(filename)
    self.total_read = 0
    self.buf = []    
    self.buf.append(memoryview(bytearray(bufsize)))
    self.buf.append(memoryview(bytearray(bufsize)))
    self.time_silent = 0
    
  def u4(self, data):
    return array.array('I', data)[0]
  def u2(self, data):
    return array.array('H', data)[0]

  def gen_header(self, num_channel, sample_rate, bitspersample, num_samples):
    self.chunkRIFF = array.array('I', bytearray(4*3))
    self.chunkRIFF[0] = self.u4(b'RIFF')
    self.chunkRIFF[1] = 4
    self.chunkRIFF[2] = self.u4(b'WAVE')

    self.chunkfmt = array.array('I', bytearray(4*6))
    self.chunkfmt[0] = self.u4(b'fmt ')
    self.chunkfmt[1] = 16 # Chunk size
    self.chunkfmt[2] = 1 + (num_channel << 16)# 1 means PCM
    self.chunkfmt[3] = sample_rate # Sample rate
    self.chunkfmt[4] = (sample_rate * bitspersample * num_channel) // 8
    self.chunkfmt[5] = (bitspersample * num_channel) // 8 + (bitspersample << 16)
    
    self.chunkdata = array.array('I', bytearray(4*2))
    self.chunkdata[0] = self.u4(b'data')
    self.chunkdata[1] = (num_samples * bitspersample * num_channel) // 8

  @micropython.viper
  def check_silent(self, buf_in, buflen:int, max_level:int, threshold_length:int, skip_sample:int) -> int:
    buf = ptr16(buf_in) 
    count:int = 0
    i = 0
    while i < buflen:
      data:int = buf[i]
      if data >= 0x8000:
        pass
      else:
        if data > max_level:
          count = 0
          i += skip_sample
          continue
      count += 1
      if count >= threshold_length:
        return 1
      i += skip_sample

    return 0
    
  def recv_callback(self, index):
    self.last_index = index
    readsize = len(self.buf[index])
   
    #silent = self.check_silent(self.buf[index], readsize, 1000, 8000, 4)
    #if silent and (self.time_silent&1) == 1:
    #  self.time_silent += 1
    #  print(f'silent {self.time_silent}')

    #if not silent and (self.time_silent&1) == 0:
    #  self.time_silent += 1
    #  print(f'silent {self.time_silent}')

    #self.f.write(self.buf[index][:readsize])
    self.f.write(memoryview(self.buf[index]))
    self.total_read += readsize
    #print(f"callback {index}")

  def record(self, filename, maxsample, num_channels=2):
    self.total_read = 0
    #print(f"len = {len(self.buf[0]) >> 2}")
    self.num_channels = num_channels
    numsample = maxsample
    audio.stream_setup(1, audio.sample_rate(), self.num_channels, numsample, self.recv_callback)
    audio.stream_setdata(1, 0, self.buf[0])
    audio.stream_setdata(1, 1, self.buf[1])
    
    self.f = open(filename, 'wb')
    self.gen_header(self.num_channels, audio.sample_rate(), 16, numsample)
    self.f.write(bytes(self.chunkRIFF))
    self.f.write(bytes(self.chunkfmt))
    self.f.write(bytes(self.chunkdata))
    audio.stream_record(True)

  def stop(self):
    audio.stream_record(False)
    
    # Get where it was stopped
    num_samples = audio.stream_position(1)
    print(f"num_samples = {num_samples}, total_read = {self.total_read}") 
    
    #Write remaining data
    bytes_per_sample = 2 * self.num_channels
    remaining = (num_samples * bytes_per_sample) - self.total_read
    if remaining > 0:
      self.f.write(self.buf[1 - self.last_index][:remaining])
    
    #Rewrite the header
    self.chunkdata[1] = (num_samples * 16 * self.num_channels) // 8
    self.f.seek(0)
    self.f.write(bytes(self.chunkRIFF)) 
    self.f.write(bytes(self.chunkfmt))
    self.f.write(bytes(self.chunkdata))
    self.f.close()
 
def main(vs, args_in):
  
  cc = codec_config.codec_config()
  filename = "/sd/work/rec.wav"
  parser = argparse.ArgumentParser(
            description='Sound recorder' )
  parser.add_argument('-s', '--sample_rate',action='store', default='24000', help='Sample rate')
  parser.add_argument('-l', '--length',action='store', default='3600', help='Length in second, you can also specify by minutes like 100m')
  parser.add_argument('-c', '--channel',action='store', default='2', help='Channel')
  parser.add_argument('-m', '--monitor',action='store_true', help='Input monitoring')
  parser.add_argument('filename',default='/sd/work/rec.wav', nargs='?', help='Filename to record')
  
  args = parser.parse_args(args_in[1:])

  filename = args.filename
  
  #print("turn on input monitoring? y or n", file=vs)
  #answer = vs.read(1)
  monitoring = False
  if args.monitor:
    cc.set_input_mixer(15)
    monitoring = True
  else:
    cc.set_input_mixer(0x28) #mute

  if monitoring:
    print("Adjust input volume. Press any key to start recording,", file=vs)
    vs.read(1)

  print(f"Recording to {filename}, press q to stop recording", file=vs)
  
  sample_rate = int(args.sample_rate)
  
  audio.sample_rate(sample_rate)

  rec = stream_record('dummy',vs, 150000)
  print("recording", file = vs)
  time.sleep(0.2)
  # Set one hour as maximum recording time
  
  length = int(args.length) if args.length[-1] != 'm' else int(args.length[:-1])*60
  rec.record(filename, sample_rate * length, int(args.channel))
  while(audio.stream_record()):
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      keys = ret[1].encode('ascii')
      if keys == b'q':
        break
    
  rec.stop()
  #return
    
  cc.set_input_mixer(0x28) #mute monitor
  
  print(f"Recording saved to {filename}, playing", file = vs)
  wp = wav_play.wav_play()
  wp.open(filename)
  wp.play()
  while(audio.stream_play()):
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      keys = ret[1].encode('ascii')
      if keys == b'q':
        break
  wp.stop()


