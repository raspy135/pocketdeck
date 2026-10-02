import pdeck
import audio
import array
import time
import pdeck_utils as pu
import codec_config
import wav_play
import argparse
import math
import esclib as elib
import anm

_CHARS = '▁▂▃▄▅▆▇█'
_BAR_WIDTH = 24
_PEAK_HOLD_MS = 2000
_MON_BUFSIZE = 4800  # ~50ms at 24000Hz stereo → ~20 VU updates/sec


class LevelMeter:

  def __init__(self, vs):
    self.vs = vs
    self.el = elib.esclib()
    self.peak_norm = 0.0
    self.peak_time = time.ticks_ms()
    self._decay_anm = None
    vs.write('\r\n')

  def update(self, level_raw):
    norm = math.sqrt(min(level_raw / 32767.0, 1.0))
    now = time.ticks_ms()

    if norm >= self.peak_norm:
      self.peak_norm = norm
      self.peak_time = now
      self._decay_anm = None
    else:
      held = time.ticks_diff(now, self.peak_time)
      if held > _PEAK_HOLD_MS:
        if self._decay_anm is None:
          self._decay_anm = anm.anm_object(600, {'val': (anm.ease_out, self.peak_norm, 0.0)})
        t = time.ticks_diff(now, self._decay_anm.start_t) / 600.0
        self._decay_anm.internal_seek(min(t, 1.0))
        self.peak_norm = max(norm, self._decay_anm.val)

    nc = len(_CHARS)
    total = _BAR_WIDTH * nc
    filled = int(norm * total)
    peak_pos = int(self.peak_norm * total)

    bar = []
    for i in range(_BAR_WIDTH):
      cs = i * nc
      steps = filled - cs
      if steps <= 0:
        bar.append(' ')
      elif steps >= nc:
        bar.append(_CHARS[-1])
      else:
        bar.append(_CHARS[steps - 1])

    if peak_pos > 0:
      peak_cell = min(peak_pos // nc, _BAR_WIDTH - 1)
      if bar[peak_cell] == ' ':
        bar[peak_cell] = '▌'

    el = self.el
    self.vs.write(
      el.cur_up(1) + '\r[' + ''.join(bar) + ']' +
      el.erase_to_end_of_current_line() + '\r\n'
    )


class stream_record:

  def __init__(self, filename, stream, bufsize=200000):
    self.filename = filename
    self.last_index = 1
    self.vs = stream
    self.total_read = 0
    self.buf = []
    self.buf.append(memoryview(bytearray(bufsize)))
    self.buf.append(memoryview(bytearray(bufsize)))
    self.time_silent = 0
    self.f = None
    self.last_level = 0

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
    self.chunkfmt[1] = 16
    self.chunkfmt[2] = 1 + (num_channel << 16)
    self.chunkfmt[3] = sample_rate
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

  @micropython.viper
  def compute_peak(self, buf_in, buflen: int) -> int:
    buf = ptr16(buf_in)
    peak: int = 0
    i: int = 0
    while i < buflen:
      data: int = buf[i]
      if data >= 0x8000:
        data = 0x10000 - data
      if data > peak:
        peak = data
      i += 4
    return peak

  def recv_callback(self, index):
    self.last_index = index
    readsize = len(self.buf[index])
    self.last_level = self.compute_peak(self.buf[index], readsize >> 1)
    if self.f is not None:
      self.f.write(memoryview(self.buf[index]))
      self.total_read += readsize

  def start_monitor(self, num_channels=2):
    self.last_level = 0
    audio.stream_setup(1, audio.sample_rate(), num_channels, 999999999, self.recv_callback)
    audio.stream_setdata(1, 0, self.buf[0])
    audio.stream_setdata(1, 1, self.buf[1])
    audio.stream_record(True)

  def stop_monitor(self):
    audio.stream_record(False)

  def record(self, filename, maxsample, num_channels=2):
    self.total_read = 0
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

    num_samples = audio.stream_position(1)
    print(f"num_samples = {num_samples}, total_read = {self.total_read}")

    bytes_per_sample = 2 * self.num_channels
    remaining = (num_samples * bytes_per_sample) - self.total_read
    if remaining > 0:
      self.f.write(self.buf[1 - self.last_index][:remaining])

    self.chunkdata[1] = (num_samples * 16 * self.num_channels) // 8
    self.f.seek(0)
    self.f.write(bytes(self.chunkRIFF))
    self.f.write(bytes(self.chunkfmt))
    self.f.write(bytes(self.chunkdata))
    self.f.close()


def main(vs, args_in):

  cc = codec_config.codec_config()
  parser = argparse.ArgumentParser(vs=vs, description='Sound recorder')
  parser.add_argument('-s', '--sample_rate', action='store', default='24000', help='Sample rate')
  parser.add_argument('-l', '--length', action='store', default='3600', help='Length in second, you can also specify by minutes like 100m')
  parser.add_argument('-c', '--channel', action='store', default='2', help='Channel')
  parser.add_argument('-m', '--monitor', action='store_true', help='Input monitoring')
  parser.add_argument('filename', default='/sd/work/rec.wav', nargs='?', help='Filename to record')

  args = parser.parse_args(args_in[1:])
  filename = args.filename
  num_channels = int(args.channel)
  sample_rate = int(args.sample_rate)
  length = int(args.length) if args.length[-1] != 'm' else int(args.length[:-1]) * 60

  monitoring = args.monitor
  if monitoring:
    cc.set_input_mixer(15)
  else:
    cc.set_input_mixer(0x28)

  audio.sample_rate(sample_rate)
  rec_bufsize = _MON_BUFSIZE if monitoring else 150000
  rec = stream_record('dummy', vs, rec_bufsize)

  meter = None
  if monitoring:
    print("Adjust input volume. Press any key to start recording.", file=vs)
    rec.start_monitor(num_channels)
    meter = LevelMeter(vs)
    while True:
      pdeck.delay_tick(15)
      meter.update(rec.last_level)
      ret = vs.v.read_nb(1)
      if ret and ret[0] > 0:
        break
    rec.stop_monitor()

  print(f"Recording to {filename}, press q to stop recording", file=vs)
  if monitoring:
    rec_bufsize = 150000
    rec = stream_record('dummy', vs, rec_bufsize)
    

  time.sleep(0.2)
  rec.record(filename, sample_rate * length, num_channels)

  while audio.stream_record():
    pdeck.delay_tick(20)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      keys = ret[1].encode('ascii')
      if keys == b'q':
        break
    if meter:
      meter.update(rec.last_level)

  rec.stop()
  cc.set_input_mixer(0x28)

  print(f"Recording saved to {filename}. The filename was copied to clipboard.", file=vs)
  
  pdeck.clipboard_copy(filename)
  return

  wp = wav_play.wav_play()
  wp.open(filename)
  wp.play()
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      keys = ret[1].encode('ascii')
      if keys == b'q':
        break
  wp.stop()
