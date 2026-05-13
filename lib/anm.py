import math
import time

def linear(t): return t
def ease_in(t): return t * t
def ease_out(t): return t * (2.0 - t)
def ease_in_out(t, m=0.5):
  if t < m:
    return t * t * (0.5 / (m * m)) if m > 0 else 0.5
  else:
    t2 = 1.0 - t
    m2 = 1.0 - m
    return 1.0 - t2 * t2 * (0.5 / (m2 * m2)) if m2 > 0 else 0.5

def ease_out_in(t, m=0.5):
  if t < m:
    t2 = t / m if m > 0 else 0.0
    return (t2 * (2.0 - t2)) * m
  else:
    t2 = (t - m) / (1.0 - m) if m < 1.0 else 1.0
    return m + (t2 * t2) * (1.0 - m)
def spring(t, b=3.0, d=5.0): 
  # Quick, bouncy overshoot function (CSS style)
  return 1.0 - math.cos(t * math.pi * b) * math.exp(-t * d)
def jump(t): return 1.0 if t >= 1.0 else 0.0

class anm_object:
  linear = staticmethod(linear)
  ease_in = staticmethod(ease_in)
  ease_out = staticmethod(ease_out)
  ease_in_out = staticmethod(ease_in_out)
  ease_out_in = staticmethod(ease_out_in)
  spring = staticmethod(spring)
  jump = staticmethod(jump)

  def __init__(self, duration_ms, props, loop=False, auto_unregister=False):
    self.duration_ms = duration_ms
    self.props = props
    self.loop = loop
    self.auto_unregister = auto_unregister
    self.current_time = 0.0
    self.start_t = time.ticks_ms()
    self.internal_seek(0.0)

  def seek(self, norm_t):
    self.start_t = time.ticks_ms() - int(norm_t * self.duration_ms)
    self.internal_seek(norm_t)

  def internal_seek(self, norm_t):
    self.elapsed_time = norm_t
    if self.loop:
      norm_t = norm_t % 1.0
    else:
      if norm_t < 0.0: norm_t = 0.0
      if norm_t > 1.0: norm_t = 1.0
    if self.current_time == 1.0 and norm_t == 1.0:
      return
    self.current_time = norm_t
      
    for k, v in self.props.items():
      func = v[0]
      keyframes = v[1:]
      num_frames = len(keyframes)
      
      if num_frames == 0:
        continue
      if num_frames == 1:
        setattr(self, k, keyframes[0])
        continue
        
      e_t = func(norm_t)
      segments = num_frames - 1
      scaled_t = e_t * segments
      
      index = int(math.floor(scaled_t))
      
      if index < 0:
        index = 0
      elif index >= segments:
        index = segments - 1
        
      segment_t = scaled_t - index
      
      v0 = keyframes[index]
      v1 = keyframes[index + 1]
      
      val = v0 + (v1 - v0) * segment_t
      setattr(self, k, val)

  def get_time(self):
    return self.current_time

  def get_elapsed(self):
    return self.elapsed_time
    
class anm_sequencer:
  def __init__(self):
    self.anms = {}
    self.last_t = time.ticks_ms()
    
  def update(self, t_ms):
    self.last_t = t_ms
    # List conversion to allow safe deletion during iteration
    for key, obj in list(self.anms.items()):
      local_t = t_ms - obj.start_t
      if obj.duration_ms <= 0:
        norm_t = 1.0
      else:
        norm_t = local_t / obj.duration_ms
      obj.internal_seek(norm_t)
      
      if norm_t >= 1.0 and obj.auto_unregister:
        self.unregister(key)

  def register(self, key, obj, seek_to = 0.0):
    self.anms[key] = obj
    obj.key = key
    obj.seek(seek_to)
    
  def unregister(self, key):
    if key in self.anms:
      del self.anms[key]

  def get_obj(self, key):
    if key in self.anms:
      return self.anms[key]
    return None

  def __iter__(self):
    for obj in self.anms.values():
      yield obj
