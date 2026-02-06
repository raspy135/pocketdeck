import pdeck
import audio
import array
import time
import os
import _thread

class wav_play:
  def __init__(self, bufsize = 100000):
    #self.filename = filename
    self.callback_lock = False
    self.buf = []    
    self.buf.append(memoryview(bytearray(bufsize)))
    self.buf.append(memoryview(bytearray(bufsize)))
    #self.open(filename)
    

  def u4(self, data):
    return array.array('I', data)[0]
  def u2(self, data):
    return array.array('H', data)[0]

  def skipChunk(self, f, chunk):
    chunkID = f.read(4)
    while chunkID != chunk:
      chunkSize = self.u4(f.read(4))
      print(f"SKIP header = {str(chunkID)}, {chunkSize}")
      f.seek(chunkSize, 1)
      chunkID = f.read(4)
    return chunk
    
  def read_header(self, f):
    self.h_chunkIDRIFF = f.read(4)
    print(f"headerRIFF = {str(self.h_chunkIDRIFF)}")
    self.h_riff_chunkSize = self.u4(f.read(4))
    self.h_riff_format = f.read(4)
    

    chunkID = self.skipChunk(f, b'fmt ')
    self.h_chunkIDfmt = chunkID
    
    self.h_fmt_chunkSize = self.u4(f.read(4))
    print(f"headerfmt = {str(self.h_chunkIDfmt)}, size={self.h_fmt_chunkSize}")
    self.h_fmt_audioFormat = self.u2(f.read(2))
    self.h_fmt_numOfChannels = self.u2(f.read(2))
    self.h_fmt_sampleRate = self.u4(f.read(4))
    self.h_fmt_byteRate = f.read(4)
    self.h_fmt_blockAligh = f.read(2)
    self.h_fmt_bitsPerSample = self.u2(f.read(2))
    f.seek(self.h_fmt_chunkSize - 16, 1)
    
    chunkID = self.skipChunk(f, b'data')
    self.h_chunkIDdata = chunkID
    self.h_data_chunkSize = self.u4(f.read(4))
    print(f"headerdata = {str(self.h_chunkIDdata)}, size={self.h_data_chunkSize}")


  @micropython.native
  def send_callback(self, index):
    #print(f"index {index} , {len(self.buf[index])}")
    num_try = 2
    while self.callback_lock:
      pdeck.delay_tick(10)
      num_try -= 1
      if num_try == 0:
        # Giving up 
        return
    
    self.callback_lock=True

    if self.total_read >= self.h_data_chunkSize:
      return
    self.total_read += self.f.readinto(self.buf[index])

    self.callback_lock=False

    #print(f"callback {index}")

  def get_position(self):
    return (audio.stream_position(0), self.h_data_chunkSize>>2)

  def open(self,filename):
      
    self.f = open(filename, 'rb')
    self.header = self.read_header(self.f)
    print(f" sample_rate {self.h_fmt_sampleRate}, bps {self.h_fmt_bitsPerSample}")
    self.total_read = 0
    numread = self.f.readinto(self.buf[0])
    numread = self.f.readinto(self.buf[1])
      
    print(self.h_data_chunkSize)
    audio.stream_setup(0, 48000, 2, self.h_data_chunkSize >> 2, self.send_callback)
    
  def play(self):
    audio.sample_rate(self.h_fmt_sampleRate)
    audio.stream_setdata(0, 0, self.buf[0])
    audio.stream_setdata(0, 1, self.buf[1])
    audio.stream_play(True)

  def stop(self):
    audio.stream_play(False)
  def close(self):
    audio.stream_setup(0, 0, 0, 0)
    self.f.close()

