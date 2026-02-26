import pdeck
import audio
import array
import time
import pdeck_utils as pu
import codec_config
import wav_play

SAMPLE_RATE = 24000

class stream_record:
  def __init__(self, filename, stream):
    self.filename = filename
    self.last_index = 1
    self.vs = stream
    #self.open(filename)
    self.total_read = 0
    self.buf = []    
    self.buf.append(memoryview(bytearray(200000)))
    self.buf.append(memoryview(bytearray(200000)))
    #self.buf.append(memoryview(bytearray(50000)))
    #self.buf.append(memoryview(bytearray(50000)))
    
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
  def check_clip(self, buf_in, buflen:int) -> int:
    buf = ptr16(buf_in) 
    for i in range(0, buflen,100):
      data:int = buf[i]
      if data >= 0x8000:
        data &= 0x7fff
        if data < 0x10:
          return 1
      else:
        if data > 0x7ff0:
          return data
    return 0
    
  def recv_callback(self, index):
    self.last_index = index
    readsize = len(self.buf[index])

    clip = self.check_clip(self.buf[index], readsize)
    #if clip != 0:
    #  print(f"level clipped {clip}", file=self.vs)
      
    #self.f.write(self.buf[index][:readsize])
    self.f.write(memoryview(self.buf[index]))
    self.total_read += readsize
    #print(f"callback {index}")

  def record(self, filename, maxsample):
    self.total_read = 0
    #print(f"len = {len(self.buf[0]) >> 2}")
    numsample = maxsample
    audio.stream_setup(1, SAMPLE_RATE , 2, numsample,self.recv_callback)
    audio.stream_setdata(1, 0, self.buf[0])
    audio.stream_setdata(1, 1, self.buf[1])
    
    self.f = open(filename, 'wb')
    self.gen_header(2, SAMPLE_RATE , 16, numsample)
    self.f.write(bytes(self.chunkRIFF))
    self.f.write(bytes(self.chunkfmt))
    self.f.write(bytes(self.chunkdata))
    print(bytes(self.chunkRIFF))
    print(bytes(self.chunkfmt))
    audio.stream_record(True)

  def stop(self):
    audio.stream_record(False)
    
    # Get where it was stopped
    num_samples = audio.stream_position(1)
    print(f"num_samples = {num_samples}, total_read = {self.total_read}") 
    
    #Write remaining data
    if (num_samples << 2) - self.total_read > 0:
      self.f.write(self.buf[1 - self.last_index][:((num_samples << 2) - self.total_read)])
    
    #Rewrite the header
    self.chunkdata[1] = (num_samples * 16*2) // 8
    self.f.seek(0)
    self.f.write(bytes(self.chunkRIFF)) 
    self.f.write(bytes(self.chunkfmt))
    self.f.write(bytes(self.chunkdata))
    self.f.close()
 
def main(vs, args):
  cc = codec_config.codec_config()
  filename = "/sd/work/rec.wav"
  if len(args) == 2:
    filename = args[1]
  print("turn on input monitoring? y or n", file=vs)
  answer = vs.read(1)
  monitoring = False
  if answer == 'y':
    cc.set_input_mixer(15)
    monitoring = True
  else:
    cc.set_input_mixer(0x28) #mute

  if monitoring:
    print("Adjust input volume. Press any key to start recording,", file=vs)
    vs.read(1)

  print(f"Recording to {filename}, press q to stop recording", file=vs)
  #audio.sample_rate(44100)
  audio.sample_rate(SAMPLE_RATE)
  #audio.sample_rate(24000)
  rec = stream_record('dummy',vs)
  print("recording", file = vs)
  rec.record(filename, SAMPLE_RATE * 60*5)
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


