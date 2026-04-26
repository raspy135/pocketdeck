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

  def skip_bytes(self, f, n):
    while n > 0:
      # MicroPython read might return less than requested or None/empty
      chunk = f.read(min(n, 1024))
      if not chunk: break
      n -= len(chunk)

  def skipChunk(self, f, chunk):
    chunkID = f.read(4)
    while chunkID != chunk:
      chunkSize = self.u4(f.read(4))
      print(f"SKIP header = {str(chunkID)}, {chunkSize}")
      self.skip_bytes(f, chunkSize)
      chunkID = f.read(4)
      if not chunkID: return None
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
    self.skip_bytes(f, self.h_fmt_chunkSize - 16)
    
    chunkID = self.skipChunk(f, b'data')
    self.h_chunkIDdata = chunkID
    self.h_data_chunkSize = self.u4(f.read(4))
    print(f"headerdata = {str(self.h_chunkIDdata)}, size={self.h_data_chunkSize}")


  #@micropython.native
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
      self.callback_lock=False
      return
    try:
      num_read = self.f.readinto(self.buf[index])
    except Exception as e:
      print(f"Stream Read Error: {e}")
      self.total_read = self.h_data_chunkSize
      self.callback_lock=False
      return
    #if self.stop_next:
    #  audio.stream_play(False)
    #  #return

    self.total_read += num_read

    if num_read < len(self.buf[index]) and self.isstreaming:
      print(f"total_read={self.total_read}")
      audio.stream_update_length(0, self.total_read >> (self.h_fmt_numOfChannels))
      #self.total_read = self.h_data_chunkSize
      #self.stop_next = True
      #return
      

    self.callback_lock=False

    #print(f"callback {index}")

  def get_position(self):
    bytes_per_sample = (self.h_fmt_bitsPerSample // 8) * self.h_fmt_numOfChannels
    return (audio.stream_position(0) + self.play_offset, self.h_data_chunkSize // bytes_per_sample)

  def open_stream(self, stream, isstreaming=True):
    self.isstreaming = isstreaming
    self.stop_next = False
    self.f = stream
    self.read_header(self.f)
    try:
      self.data_start = self.f.tell()
    except Exception as e:
      pass

    print(f" sample_rate {self.h_fmt_sampleRate}, bps {self.h_fmt_bitsPerSample}")
    self.total_read = 0
    
    print(self.h_data_chunkSize)
    # Calculate bytes per sample frame (channels * bytes_per_sample)
    bytes_per_sample = (self.h_fmt_bitsPerSample // 8) * self.h_fmt_numOfChannels


    num_samples = self.h_data_chunkSize // bytes_per_sample

    self.play_offset = 0
    
    self.total_read += self.f.readinto(self.buf[0])
    self.total_read += self.f.readinto(self.buf[1])
    
    audio.stream_setup(0, self.h_fmt_sampleRate, self.h_fmt_numOfChannels, num_samples, self.send_callback)

  def seek(self, pos):
    
    print(f"seek to {pos}")
    bytes_per_sample = (self.h_fmt_bitsPerSample // 8) * self.h_fmt_numOfChannels

    self.total_read = pos * bytes_per_sample
    self.play_offset = pos
    self.stop()

    num_samples = self.h_data_chunkSize // bytes_per_sample - pos
    
    self.f.seek(self.data_start + pos * bytes_per_sample,0)
    
    self.total_read += self.f.readinto(self.buf[0])
    self.total_read += self.f.readinto(self.buf[1])
    audio.stream_setup(0, self.h_fmt_sampleRate, self.h_fmt_numOfChannels, num_samples, self.send_callback)

  def open(self,filename):
    self.f = open(filename, 'rb')
    f_stat = os.stat(filename)
    
    self.open_stream(self.f, isstreaming=False)
    
    # Check actual file size to avoid huge headers from OpenAI
    #actual_data_size = f_stat[6] - self.f.tell()
    # Pre-fill first two buffers for immediate playback
    #print(actual_data_size)
    #if self.h_data_chunkSize > actual_data_size:
    #  self.h_data_chunkSize = actual_data_size
    #  bytes_per_sample = (self.h_fmt_bitsPerSample // 8) * self.h_fmt_numOfChannels
    #  num_samples = self.h_data_chunkSize // bytes_per_sample
    #  audio.stream_setup(0, self.h_fmt_sampleRate, self.h_fmt_numOfChannels, num_samples, self.send_callback)
    
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

