import array
import struct
import micropython
import audio

def load_wav(filename, sample_rate=None, channels=None):
  if sample_rate is None:
    sample_rate = audio.sample_rate()
      
  loader = WavLoader()
  data = None
  with open(filename, 'rb') as f:
    loader.open(f)
    if channels is None:
      channels = loader.channels
    data = loader.load_all(f, target_rate=sample_rate, target_channels=channels)
    
  return (data, channels)

class WavLoader:
  def __init__(self):
    self.reset()
    
  def reset(self):
    self.sample_rate = 0
    self.channels = 0
    self.bits_per_sample = 0
    self.format_tag = 0
    self.data_size = 0
    self.data_start = 0

  def _u32(self, b):
    return struct.unpack('<I', b)[0]

  def _u16(self, b):
    return struct.unpack('<H', b)[0]

  def open(self, f):
    self.reset()
    if f.read(4) != b'RIFF': raise ValueError("Not a RIFF file")
    f.read(4)
    if f.read(4) != b'WAVE': raise ValueError("Not a WAVE file")

    while True:
      chunk_id = f.read(4)
      if not chunk_id: break
      chunk_size = self._u32(f.read(4))
      if chunk_id == b'fmt ':
        self.format_tag = self._u16(f.read(2))
        self.channels = self._u16(f.read(2))
        self.sample_rate = self._u32(f.read(4))
        f.read(6)
        self.bits_per_sample = self._u16(f.read(2))
        if chunk_size > 16: f.seek(chunk_size - 16, 1)
      elif chunk_id == b'data':
        self.data_size = chunk_size
        self.data_start = f.tell()
        break
      else:
        f.seek(chunk_size, 1)
    if not self.data_start: raise ValueError("No data chunk found")
    return self

  def load_all(self, f, target_rate=None, target_channels=None):
    if target_channels is None: target_channels = self.channels
    f.seek(self.data_start)
    raw = f.read(self.data_size)
    if not raw: return array.array('h')
    data = self._convert_to_16bit(raw, target_channels)
    if target_rate and target_rate != self.sample_rate:
      return self._resample(data, self.sample_rate, target_rate, target_channels)
    return data

  @micropython.native
  def _resample(self, data, source_rate, target_rate, channels):
    """Native-optimized resampler. More stable with types than Viper."""
    source_frames = int(len(data) // channels)
    target_frames = int(source_frames * target_rate // source_rate)
    out = array.array('h', [0] * (target_frames * channels))
    ratio = float(source_rate) / float(target_rate)
    data_len = len(data)

    for i in range(target_frames):
      pos = i * ratio
      idx = int(pos)
      frac = pos - idx
      base_out = i * channels
      base_in = idx * channels
      for c in range(channels):
        s0_idx = base_in + c
        s1_idx = s0_idx + channels
        if s1_idx < data_len:
          s0 = data[s0_idx]
          s1 = data[s1_idx]
          out[base_out + c] = int(s0 + frac * (s1 - s0))
        elif s0_idx < data_len:
          out[base_out + c] = data[s0_idx]
    return out

  def _convert_to_16bit(self, raw, target_channels=1):
    src_ch = self.channels
    bps = self.bits_per_sample
    if self.format_tag == 1: # PCM
      if bps == 16:
        n_frames = len(raw) // (2 * src_ch)
        out = array.array('h', [0] * (n_frames * target_channels))
        self._fast_remix_16(raw, out, int(src_ch), int(target_channels), int(n_frames))
        return out
      elif bps == 32:
        n_frames = len(raw) // (4 * src_ch)
        out = array.array('h', [0] * (n_frames * target_channels))
        self._fast_convert_32_to_16(raw, out, int(src_ch), int(target_channels), int(n_frames))
        return out
      elif bps == 24:
        n_frames = len(raw) // (3 * src_ch)
        out = array.array('h', [0] * (n_frames * target_channels))
        self._fast_convert_24_to_16(raw, out, int(src_ch), int(target_channels), int(n_frames))
        return out
    elif self.format_tag == 3: # Float 32
      if bps == 32:
        src_data = array.array('f', raw)
        n_frames = len(src_data) // src_ch
        out = array.array('h', [0] * (n_frames * target_channels))
        self._fast_convert_float_to_16(src_data, out, int(src_ch), int(target_channels), int(n_frames))
        return out
    return array.array('h')

  @micropython.native
  def _fast_convert_float_to_16(self, src, dst, src_ch, dst_ch, n_frames):
    for i in range(n_frames):
      if src_ch == 1:
        v = int(src[i] * 32767)
        if dst_ch == 1: dst[i] = v
        else: dst[i*2] = v; dst[i*2+1] = v
      else:
        if dst_ch == 1: dst[i] = int((src[i*2] + src[i*2+1]) * 16383)
        else:
          dst[i*2] = int(src[i*2] * 32767)
          dst[i*2+1] = int(src[i*2+1] * 32767)

  @micropython.native
  def _fast_convert_32_to_16(self, src, dst, src_ch, dst_ch, n_frames):
    # Use standard array indexing in Native mode for safety
    p_src = array.array('i', src) 
    for i in range(n_frames):
      if src_ch == 1:
        v = p_src[i] >> 16
        if dst_ch == 1: dst[i] = v
        else: dst[i*2] = v; dst[i*2+1] = v
      else:
        v_l = p_src[i*2] >> 16
        v_r = p_src[i*2+1] >> 16
        if dst_ch == 1: dst[i] = (v_l + v_r) >> 1
        else: dst[i*2] = v_l; dst[i*2+1] = v_r

  @micropython.native
  def _fast_convert_24_to_16(self, src, dst, src_ch, dst_ch, n_frames):
    for i in range(n_frames):
      if src_ch == 1:
        idx = i * 3
        v = int(src[idx+1]) | (int(src[idx+2]) << 8)
        if v > 32767: v -= 65536
        if dst_ch == 1: dst[i] = v
        else: dst[i*2] = v; dst[i*2+1] = v
      else:
        idx_l = i * 6
        v_l = int(src[idx_l+1]) | (int(src[idx_l+2]) << 8)
        if v_l > 32767: v_l -= 65536
        idx_r = i * 6 + 3
        v_r = int(src[idx_r+1]) | (int(src[idx_r+2]) << 8)
        if v_r > 32767: v_r -= 65536
        if dst_ch == 1: dst[i] = (v_l + v_r) >> 1
        else: dst[i*2] = v_l; dst[i*2+1] = v_r

  @micropython.native
  def _fast_remix_16(self, src, dst, src_ch, dst_ch, n_frames):
    p_src = array.array('h', src)
    for i in range(n_frames):
      if src_ch == 1:
        v = p_src[i]
        if dst_ch == 1: dst[i] = v
        else: dst[i*2] = v; dst[i*2+1] = v
      else:
        v_l = int(p_src[i*2])
        v_r = int(p_src[i*2+1])
        if dst_ch == 1: dst[i] = (v_l + v_r) >> 1
        else: dst[i*2] = v_l; dst[i*2+1] = v_r

  def load_frames(self, f, frame_size=2048, stride=1, max_frames=256):
    f.seek(self.data_start)
    bytes_per_sample = self.bits_per_sample // 8
    frame_bytes = frame_size * self.channels * bytes_per_sample
    frames = []
    total_frames = self.data_size // frame_bytes
    for i in range(0, total_frames, stride):
      if len(frames) >= max_frames: break
      f.seek(self.data_start + i * frame_bytes)
      raw = f.read(frame_size * self.channels * bytes_per_sample)
      if not raw: break
      frames.append(self._convert_to_16bit(raw, 1))
    return frames
