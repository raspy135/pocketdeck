
import audio
import time
import _thread
from wav_loader import WavLoader


NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

def midi_to_hz(midi):
  """Converts a MIDI note number to Frequency (Hz)."""
  return 440.0 * (2.0 ** ((midi - 69) / 12.0))

def note_to_freq(note):
  """Converts strictly note strings (e.g. 'C4') to Hz. Preserves numbers."""
  if not isinstance(note, str):
    return note
  
  try:
    # Handle notes like "C4", "A#5"
    octave = int(note[-1])
    name = note[:-1].upper()
    if name.endswith('B'): # Flat
      n_idx = NOTES.index(name[0]) - 1
      if n_idx < 0: n_idx = 11; octave -= 1
      name = NOTES[n_idx]
    n = NOTES.index(name)
    midi = 12 * (octave + 1) + n
    return midi_to_hz(midi)
  except (ValueError, IndexError, TypeError):
    return None

CHORDS = {
  "maj7": [0, 4, 7, 11],
  "maj": [0, 4, 7],
  "major": [0, 4, 7],
  "m": [0, 3, 7],
  "min": [0, 3, 7],
  "dim": [0, 3, 6],
  "aug": [0, 4, 8],
  "sev": [0, 4, 7, 10],
  "7": [0, 4, 7, 10],
  "min7": [0, 3, 7, 10],
  "m7": [0, 3, 7, 10],
  "6": [0, 4, 7, 9],
  "m6": [0, 3, 7, 9],
  "dim7": [0, 3, 6, 9],
  "sus2": [0, 2, 7],
  "sus4": [0, 5, 7],
  "9": [0, 4, 7, 10, 14],
  "add9": [0, 4, 7, 14],
  "dom9": [0, 4, 7, 10, 14]
}

SCALES = {
  "maj": [0, 2, 4, 5, 7, 9, 11],
  "m": [0, 2, 3, 5, 7, 8, 10],
  "pent_maj": [0, 2, 4, 7, 9],
  "pent_m": [0, 3, 5, 7, 10],
  "chrom": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
}

def parse_scale(s):
  """Parses strings like 'Cmajor' or 'Dbminor' into (root_midi, scale_intervals)."""
  if not isinstance(s, str): return None
  s = s.lower()
  root = None
  scale_type = None
  
  # Try to find root note
  # Handle notes like 'eb', 'c#', 'c' manually 
  if len(s) == 0 or not ('a' <= s[0] <= 'g'): return None
  
  root_name = s[0]
  if len(s) > 1 and s[1] in ('#', 'b'):
    root_name += s[1]
  
  scale_type = s[len(root_name):]
  root_name = root_name.upper()
  
  # Convert names like 'EB' to 'D#'
  octave = 4
  if root_name.endswith('B'): # Flat
    n_idx = NOTES.index(root_name[0]) - 1
    if n_idx < 0: n_idx = 11; octave -= 1
    root_name = NOTES[n_idx]
    
  if root_name not in NOTES: return None
  root = root_name.lower()
  
  if root is None: return None
  
  # Normalize aliases
  if scale_type == "major": scale_type = "maj"
  if scale_type == "minor": scale_type = "m"
  if not scale_type: scale_type = "maj"
  if scale_type == "pentatonic_major": scale_type = "pent_maj"
  if scale_type == "pentatonic_minor": scale_type = "pent_m"
  if scale_type == "chromatic": scale_type = "chrom"
  
  intervals = SCALES.get(scale_type)
  if intervals is None: return None
  
  # Calculate root midi (default C4)
  octave = 4
  n_idx = NOTES.index(root.upper())
  root_midi = 12 * (octave + 1) + n_idx
  return (root_midi, intervals)

# Sort chord names by length (longest first) to avoid '7' hitting before 'maj7'
CHORD_NAMES = sorted(CHORDS.keys(), key=len, reverse=True)

def chord_to_freqs(c_str):
  # 1. Try as a pure note first (e.g. 'C4', 'Eb5').
  # If it matches a known note exactly with an octave, we treat it as a note.
  # This avoids interpreting 'C7' (note C in octave 7) as a chord by mistake.
  res = note_to_freq(c_str)
  if res is not None:
    return [res]
    
  # 2. Try as a chord (matches suffixes like '7', 'm', 'maj')
  inv = 0
  input_str = c_str.lower()
  if ":" in input_str:
    parts = input_str.split(":")
    input_str = parts[0]
    try: inv = int(parts[1])
    except: pass
    
  for c_name in CHORD_NAMES:
    if input_str.endswith(c_name):
      intervals = CHORDS[c_name]
      root_note = input_str[:-len(c_name)]
      if not root_note: root_note = "c4" # Default fallback
      
      try:
        # Extract octave if present (e.g. 'c4' or 'c')
        if root_note[-1].isdigit():
          octave = int(root_note[-1])
          name = root_note[:-1].upper()
        else:
          octave = 4 # Default octave
          name = root_note.upper()
          
        if name.endswith('B'): # Flat
          n_idx = NOTES.index(name[0]) - 1
          if n_idx < 0: n_idx = 11; octave -= 1
          name = NOTES[n_idx]
        n = NOTES.index(name)
        root_midi = 12 * (octave + 1) + n
        
        midi_notes = [root_midi + i for i in intervals]
        # Inversion logic: rotate lowest/highest note
        if inv > 0:
          for _ in range(inv):
            midi_notes.sort()
            midi_notes[0] += 12
        elif inv < 0:
          for _ in range(abs(inv)):
            midi_notes.sort()
            midi_notes[-1] -= 12
        
        return [midi_to_hz(m) for m in midi_notes]
      except (ValueError, IndexError, KeyError):
        pass

  return []



def parse_mini(s, preprocess=None):
  """
  Parses a mini-notation string into a nested list structure.
  """
  s = s.replace("[", " [ ").replace("]", " ] ").replace("<", " < ").replace(">", " > ").replace(",", " , ").replace("@"," @").replace("*"," *").replace("/"," /")
  tokens = s.split()
  
  def build_tree(tokens):
    stack = [[]]
    for t in tokens:
      if t == "[":
        new_group = []
        stack[-1].append(new_group)
        stack.append(new_group)
      elif t == "<":
        new_group = []
        stack[-1].append({"type": "alternation", "data": new_group})
        stack.append(new_group)
      elif t in ("]", ">"):
        if len(stack) > 1: stack.pop()
      elif t == ",":
        stack[-1].append(",")
      elif t.startswith("/"):
        if stack[-1]:
          prev = stack[-1].pop()
          num = float(t[1:]) if len(t) > 1 else 2.0
          stack[-1].append({"val": prev, "speed": num})
      elif t.startswith("*"):
        if stack[-1]:
          prev = stack[-1].pop()
          num = float(t[1:]) if len(t) > 1 else 2.0
          stack[-1].append({"val": prev, "speed": 1.0/num})
      elif t.startswith("@"):
        if stack[-1]:
          prev = stack[-1].pop()
          num = float(t[1:]) if len(t) > 1 else 1.0
          stack[-1].append({"val": prev, "weight": num})
      else:
        # 0. Handle rests explicitly before numeric parsing
        if t in ("~", "."):
          val = t
        else:
          # 1. Parse into best data type (int, float, or string)
          try:
            val = int(t)
          except ValueError:
            try:
              # Special case: don't let note strings like 'E3' or 'e3' parse as hex/floats
              if len(t) <= 3 and t[0].upper() in NOTES:
                raise ValueError("Note detected")
              val = float(t)
            except ValueError:
              val = t

        # 2/3. Baking & Automation Priority
        baked = None
        if preprocess and isinstance(val, str) and val not in ("~", "."):
          baked = preprocess(val)
          
        if baked:
          val = tuple(baked) if isinstance(baked, (list, tuple)) else baked
        elif isinstance(val, str) and ":" in val:
          parts = val.split(":")
          cmd = parts[0]
          try:
            v = float(parts[1]) if len(parts) > 1 else 0.0
            trans = int(parts[2]) if len(parts) > 2 else 0
            val = {"type": "control", "cmd": cmd, "val": v, "trans": trans}
          except (ValueError, IndexError):
            pass # Keep as string for now
            
        stack[-1].append(val)
    return stack[0]

  tree = build_tree(tokens)
  
  def post_process(item):
    if isinstance(item, list):
      # Process children first
      processed_items = [post_process(i) for i in item]
      if "," in processed_items:
        layers = []
        curr = []
        for p in processed_items:
          if p == ",":
            if curr: layers.append(curr if len(curr) > 1 else curr[0])
            curr = []
          else:
            curr.append(p)
        if curr: layers.append(curr if len(curr) > 1 else curr[0])
        return {"type": "layers", "data": layers}
      return processed_items
    if isinstance(item, dict):
      if item.get("type") == "alternation":
        item["data"] = [post_process(i) for i in item["data"]]
        return item
      if "data" in item: item["data"] = post_process(item["data"])
      if "val" in item: item["val"] = post_process(item["val"])
      return item
    return item

  return post_process(tree)


class Pattern:
  
  @classmethod
  def create(cls, data, preprocess = None):
    ret = cls(data, preprocess)
    if ret._data == None:
      return None
    return ret

  def __init__(self, data, preprocess=None):
    self._str = data if isinstance(data, str) else None
    try:
      self._data = parse_mini(data, preprocess) if isinstance(data, str) else data
    except Exception as e:
      print(f"Parse error : {self._str}")
      self._data = None
      return
    self._preprocess = preprocess # Store for potentially rebinding later
    self._speed = 1.0
    self._clip = 0.9
    self._strum = 0.0
    self._scale = None
    self._transpose = 0
    self._cache = {}
    self._p = None

  def print_str(self):
    return self._str
    
  def clear_cache(self):
    self._cache = {}
    self._p = None
    
  def fast(self, n): 
    self._speed *= n
    self.clear_cache()
    return self
    
  def slow(self, n): 
    self._speed /= n
    self.clear_cache()
    return self

  def clip(self, n):
    if isinstance(n, str):
      self._clip = Pattern.create(n)
    else:
      self._clip = n
    self.clear_cache()
    return self

  def strum(self, amount):
    if isinstance(amount, str):
      self._strum = Pattern.create(amount)
    else:
      self._strum = amount
    self.clear_cache()
    return self

  def scale(self, s):
    if isinstance(s, str) and (" " in s.strip() or "<" in s or "[" in s):
      self._scale = Pattern.create(s)
    else:
      self._scale = s # Might be 'Cmajor' or None
    self.clear_cache()
    return self

  def transpose(self, n):
    if isinstance(n, str):
      self._transpose = Pattern.create(n)
    else:
      self._transpose = n
    self.clear_cache()
    return self

  def _get_val(self, param, offset, cycle, default):
    if isinstance(param, Pattern):
      # Parameter patterns are sampled at the given offset within the cycle
      evs = param.get_events(cycle)
      for o, d, v in evs:
        if offset >= o and offset < o + d:
          return v
      return default
    return param

  def _gcd(self, a, b):
    a, b = int(a * 1000 + 0.5), int(b * 1000 + 0.5)
    while b:
      a, b = b, a % b
    return a / 1000.0

  def _lcm(self, a, b):
    if a == 0 or b == 0: return 0
    return abs(a * b) / self._gcd(a, b)

  def get_period(self, data):
    """Calculates the inherent phrase length in cycles, including parameter patterns."""
    p = self._get_period_raw(data)
    if isinstance(self._clip, Pattern):
      p = self._lcm(p, self._clip.get_period(self._clip._data))
    if isinstance(self._strum, Pattern):
      p = self._lcm(p, self._strum.get_period(self._strum._data))
    if isinstance(self._scale, Pattern):
      p = self._lcm(p, self._scale.get_period(self._scale._data))
    if isinstance(self._transpose, Pattern):
      p = self._lcm(p, self._transpose.get_period(self._transpose._data))
    return p

  def _get_period_raw(self, data):
    """Calculates the data's inherent phrase length."""
    if isinstance(data, dict):
      t = data.get("type")
      if t == "layers":
        res = 1.0
        for i in data["data"]: res = self._lcm(res, self._get_period_raw(i))
        return res
      if t == "alternation":
        n = len(data["data"])
        l = 1.0
        for i in data["data"]: l = self._lcm(l, self._get_period_raw(i))
        return n * l
      if "val" in data and "speed" in data:
        p_val = self._get_period_raw(data["val"])
        s = data["speed"]
        return p_val * s if s > 1.0 else p_val
      if "val" in data and "weight" in data:
        return self._get_period_raw(data["val"])
    if isinstance(data, list):
      res = 1.0
      for i in data: res = self._lcm(res, self._get_period_raw(i))
      return res
    return 1.0

  def _normalize(self, data, offset=0.0, duration=1.0, visit_index=0, phrase_cycle=0):
    """Recursive Selector engine: generates events for exactly one cycle."""
    events = []
    
    if isinstance(data, dict):
      t = data.get("type")
      if t == "layers":
        strum_val = self._get_val(self._strum, offset, phrase_cycle, 0.0)
        n = len(data["data"])
        for i, layer in enumerate(data["data"]):
          if strum_val >= 0:
            delay = i * strum_val
          else:
            delay = (n - 1 - i) * abs(strum_val)
          events.extend(self._normalize(layer, offset + delay, duration, visit_index, phrase_cycle))
        return events
      
      if t == "alternation":
        items = data["data"]
        n = len(items)
        idx = int(visit_index % n)
        return self._normalize(items[idx], offset, duration, int(visit_index // n), phrase_cycle)

      if "val" in data and "speed" in data:
        v, s = data["val"], data["speed"]
        if s >= 1.0: # Stretching / Selector
          if isinstance(v, list):
            n = len(v)
            num_per_cycle = n / s
            page = int(visit_index % s)
            start = int(page * num_per_cycle + 0.001)
            end = int((page + 1) * num_per_cycle + 0.001)
            return self._normalize(v[start:end], offset, duration, int(visit_index // s), phrase_cycle)
          else:
            if int(visit_index % s) == 0:
              return self._normalize(v, offset, duration, int(visit_index // s), phrase_cycle)
            return []
        else: # Repeating *n
          num = int(1/s + 0.1)
          sub_dur = duration / num
          for r in range(num):
             events.extend(self._normalize(v, offset + r * sub_dur, sub_dur, visit_index * num + r, phrase_cycle))
          return events
      
      if "val" in data and "weight" in data:
        return self._normalize(data["val"], offset, duration, visit_index, phrase_cycle)

    if isinstance(data, list):
      tw = sum(i.get("weight", 1.0) if isinstance(i, dict) else 1.0 for i in data)
      curr_off = offset
      for item in data:
        w = item.get("weight", 1.0) if isinstance(item, dict) else 1.0
        item_dur = (w / tw) * duration
        val = item
        if isinstance(item, dict) and "weight" in item and "speed" not in item and "type" not in item:
          val = item.get("val", item)
        events.extend(self._normalize(val, curr_off, item_dur, visit_index, phrase_cycle))
        curr_off += item_dur
      return events
    
    # Chord Handle: Simultaneous notes baked as a tuple
    if isinstance(data, tuple):
      # tuple(is_control, ...) case handled below by control check
      if not (len(data) == 4 and data[0] is True):
        strum_val = self._get_val(self._strum, offset, phrase_cycle, 0.0)
        n = len(data)
        for i, part in enumerate(data):
          if strum_val >= 0:
            delay = i * strum_val
          else:
            delay = (n - 1 - i) * abs(strum_val)
          events.extend(self._normalize(part, offset + delay, duration, visit_index, phrase_cycle))
        return events

    # Atomic Note/Chord/Sample/Control
    if data in ("~", "."): return []
    if isinstance(data, dict) and data.get("type") == "control":
      return [(offset, duration, (True, data["cmd"], data["val"], data["trans"]))]
    
    # Transpose and Scale Mapping for relative integers
    mapped_by_scale = False
    if isinstance(data, (int, float)):
      transpose_val = self._get_val(self._transpose, offset, phrase_cycle, 0)
      if transpose_val != 0:
        if isinstance(data, int):
          data += int(transpose_val)
        else:
          # Transpose frequency: f * 2^(n/12)
          data *= (2.0 ** (transpose_val / 12.0))
      
      if isinstance(data, int) and self._scale is not None:
        s_val = self._get_val(self._scale, offset, phrase_cycle, None)
        if s_val:
          s_info = parse_scale(s_val)
          if s_info:
            root_midi, intervals = s_info
            n = len(intervals)
            midi = root_midi + (data // n) * 12 + intervals[data % n]
            data = midi_to_hz(midi)
            mapped_by_scale = True

    # Pre-baked value (Hz or ID) or raw number
    if data is not None:
      # ONLY preprocess if it's an int (MIDI/ID) and not already handled by scale.
      # Skip floats as they are assumed to be already-calculated frequencies.
      if not mapped_by_scale and isinstance(data, int) and self._preprocess:
        baked = self._preprocess(data)
        data = tuple(baked) if isinstance(baked, (list, tuple)) else baked

      clip_val = self._get_val(self._clip, offset, phrase_cycle, 0.9)
      dur_raw = duration * clip_val
      events.append((offset, dur_raw, data))
    return events

  def get_events(self, cycle=0):
    if self._p is None:
      self._p = self.get_period(self._data)
      if self._p < 1: self._p = 1
    
    # Cache key: absolute cycle modulo the pattern period
    ckey = int(cycle % self._p)
    
    if ckey in self._cache:
      events = self._cache[ckey]
    else:
      events = self._normalize(self._data, 0.0, 1.0, cycle, cycle)
      self._cache[ckey] = events
      
    if not events: return []
    res = []
    for o, d, v in events:
      # Map pattern time to sequencer cycles
      res.append((o / self._speed, d / self._speed, v))
    return res

class PieSampler:
  def __init__(self, slots):
    self.dev = audio.sampler(slots)
    self._ctx = None
    self._max_samples = slots

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

  def load_wav(self, slot, filename, sample_rate=None, channels=None):
    """Loads a WAV file into a sampler slot. channels=None for auto-detection."""
    from wav_loader import load_wav
    data, ch = load_wav(filename, sample_rate=sample_rate, channels=channels)
    
    if data:
      self.load(slot, data, ch)
      return len(data)
    return 0

  def load(self, slot, data, channel=1):
    self.dev.set_sample(slot, data, channel)

  def volume(self, val, transition_ms=0, execute_at=0):
    for i in range(self._max_samples): 
      self.dev.volume(i, val, transition_ms, execute_at)

  def play(self, slot, loop=False, execute_at=0):
    self.dev.play(slot, loop, execute_at)

  def stop(self, slot, fadeout_ms=0, execute_at=0):
    self.dev.stop(slot, fadeout_ms, execute_at)

  def stop_all(self):
    self.dev.stop_all()

  def detach(self, state=True):
    self.dev.detach(state)

  def trigger(self, value, execute_at, duration):
    # For sampler, 'value' is the sample index
    if isinstance(value, (list, tuple)) and len(value) > 0:
      value = value[0]
    try:
      slot = int(value)
      self.dev.play(slot, False, execute_at)
    except (ValueError, TypeError):
      pass

  def dispatch(self, cmd, val, trans, tick):
    if cmd.startswith("vol"):
      idx = cmd[3:]
      if idx == "_":
        self.volume(val, trans, tick)
      else:
        self.dev.volume(int(idx), val, trans, tick)

class PieWavetable:
  def __init__(self, oscillators):
    self.dev = audio.wavetable(oscillators)
    self._ctx = None
    self._max_osc = oscillators
    self._osc_free_at = [0] * oscillators
    self.transition_ms = 0

  def morph(self, val, transition_ms=0, execute_at=0):
    for i in range(self._max_osc):
      self.dev.morph(i, val, transition_ms, execute_at)

  def volume(self, val, transition_ms=0, execute_at=0):
    for i in range(self._max_osc):
      self.dev.volume(i, val, transition_ms, execute_at)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    for i in range(self._max_osc):
      self.dev.frequency(i, 440.0)
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

  def set_table(self, slot, frames):
    if slot == "_":
      for i in range(self._max_osc):
        self.dev.set_wavetable(i, frames)
    else:
      self.dev.set_wavetable(slot, frames)

  def load_wavetable(self, slot, filename, stride=1, max_frames=256, frame_size=2048):
    """Loads a wavetable file."""
    loader = WavLoader()
    with open(filename, 'rb') as f:
      loader.open(f)
      frames = loader.load_frames(f, frame_size=frame_size, stride=stride, max_frames=max_frames)
    
    if frames:
      self.dev.set_wavetable(slot, frames)
      return len(frames)
    return 0

  def copy_table(self, dest_slot, src_slot):
    """Shares wavetable data from one slot to another (memory efficient)."""
    self.dev.copy_table(dest_slot, src_slot)

  def _preprocess(self, val):
    """Converts strings or MIDI numbers to Hz."""
    if isinstance(val, str):
      res = chord_to_freqs(val)
      return res if res else None
    if isinstance(val, (int, float)):
      return [midi_to_hz(val)]
    return None

  def play(self, slot, freq, execute_at=0):
    freq = self._preprocess(freq)
    if isinstance(freq, list) and len(freq) > 0:
      freq = freq[0]
    self.dev.pitch(slot, freq / 440.0, 0, execute_at)
    self.dev.note_on(slot, execute_at)
    self._osc_free_at[slot] = 0x7FFFFFFF 

  def stop(self, slot, execute_at=0):
    self.dev.note_off(slot, execute_at)
    self._osc_free_at[slot] = execute_at

  def stop_all(self):
    self.dev.stop_all()

  def detach(self, state=True):
    self.dev.detach(state)

  def pitch_transition(self, transition_ms):
    self.transition_ms = transition_ms

  def trigger(self, freq, execute_at, duration):
    target_osc = -1
    for i in range(self._max_osc):
      if self._osc_free_at[i] <= execute_at:
        target_osc = i
        break
    if target_osc == -1:
      earliest_free_tick = min(self._osc_free_at)
      target_osc = self._osc_free_at.index(earliest_free_tick)
    
    if isinstance(freq, (list, tuple)) and len(freq) > 0:
      freq = freq[0]
    self.dev.pitch(target_osc, freq / 440.0, self.transition_ms, execute_at)
    self.dev.note_on(target_osc, execute_at)
    self.dev.note_off(target_osc, duration)
    self._osc_free_at[target_osc] = duration

  def dispatch(self, cmd, val, trans, tick):
    if cmd.startswith("vol"):
      idx = cmd[3:]
      if idx == "_":
        self.volume(val, trans, tick)
      else:
        self.dev.volume(int(idx), val, trans, tick)
    elif cmd.startswith("mrp"):
      idx = cmd[3:]
      if idx == "_":
        self.morph(val, trans, tick)
      else:
        self.dev.morph(int(idx), val, trans, tick)

class PieFilter:
  def __init__(self):
    self.dev = audio.filter()
    self._ctx = None

  def set_type(self, type_str):
    self.dev.set_type(type_str)

  def set_params(self, cutoff, q=0.707, transition_ms=0, execute_at=0):
    self.dev.set_params(cutoff, q, transition_ms, execute_at)

  def detach(self, state=True):
    self.dev.detach(state)

  def enable(self):
    self.dev.active(True)

  def disable(self):
    self.dev.active(False)

  def q(self, val, transition_ms=0, execute_at=0):
    self.dev.set_params(-1, val, transition_ms, execute_at)

  def _preprocess(self, val):
    """Converts strings/MIDI to Hz for filter cutoff."""
    if isinstance(val, str):
      return chord_to_freqs(val)
    if isinstance(val, (int, float)):
      return [midi_to_hz(val)]
    return val

  def trigger(self, value, execute_at, duration):
    # If value is from Pattern, it might be a list (from chord_to_freqs)
    if isinstance(value, (list, tuple)) and len(value) > 0:
      value = value[0]
    self.dev.set_params(value, -1, 0, execute_at)

  def dispatch(self, cmd, val, trans, tick):
    if cmd == "q":
      self.dev.set_params(-1, val, trans, tick)
    elif cmd == "freq" or cmd == "cutoff":
      self.dev.set_params(val, -1, trans, tick)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

class PieCompressor:
  def __init__(self):
    self.dev = audio.compressor()
    self._ctx = None

  def set_params(self, gain, reduction, transition_ms=0, execute_at=0):
    self.dev.set_params(gain, reduction, transition_ms, execute_at)

  def detach(self, state=True):
    self.dev.detach(state)

  def enable(self):
    self.dev.active(True)

  def disable(self):
    self.dev.active(False)

  def gain(self, val, transition_ms=0, execute_at=0):
    self.dev.set_params(val, -1, transition_ms, execute_at)

  def reduction(self, val, transition_ms=0, execute_at=0):
    self.dev.set_params(-1, val, transition_ms, execute_at)

  def trigger(self, value, execute_at, duration):
    # If value is from Pattern, it might be a list
    if isinstance(value, (list, tuple)) and len(value) > 0:
      value = value[0]
    self.dev.set_params(value, -1, 0, execute_at)

  def dispatch(self, cmd, val, trans, tick):
    if cmd == "red" or cmd == "reduction":
      self.dev.set_params(-1, val, trans, tick)
    elif cmd == "gain" or cmd == "vol":
      self.dev.set_params(val, -1, trans, tick)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

class PieMixer:
  def __init__(self):
    self.dev = audio.mixer()
    self._ctx = None

  def set_params(self, volume, pan, transition_ms=0, execute_at=0):
    self.dev.set_params(volume, pan, transition_ms, execute_at)

  def detach(self, state=True):
    self.dev.detach(state)


  def trigger(self, value, execute_at, duration):
    # Default 'play' for mixer is volume
    self.dev.set_params(value, -10.0, 0, execute_at)

  def dispatch(self, cmd, val, trans, tick):
    if cmd == "pan":
      self.dev.set_params(-1.0, val, trans, tick)
    elif cmd == "vol" or cmd == "volume":
      self.dev.set_params(val, -10.0, trans, tick)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

class PieEcho:
  def __init__(self, max_ms=1500):
    self.dev = audio.echo(max_ms)
    self._ctx = None

  def set_params(self, time_ms, feedback, transition_ms=0, execute_at=0):
    self.dev.set_params(time_ms, feedback, transition_ms, execute_at)

  def detach(self, state=True):
    self.dev.detach(state)

  def enable(self):
    self.dev.active(True)

  def disable(self):
    self.dev.active(False)

  def set_type(self, type_str):
    if type_str == "stereo":
      self.dev.set_type(audio.ECHO_STEREO)
    elif type_str == "ping_pong":
      self.dev.set_type(audio.ECHO_PINGPONG)


  def trigger(self, value, execute_at, duration):
    # Default 'play' for delay is time_ms
    self.dev.set_params(value, -1, 0, execute_at)

  def dispatch(self, cmd, val, trans, tick):
    if cmd == "fb" or cmd == "feedback":
      self.dev.set_params(-1, val, trans, tick)
    elif cmd == "time" or cmd == "ms":
      self.dev.set_params(val, -1, trans, tick)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

class PieReverb:
  def __init__(self):
    self.dev = audio.reverb()
    self._ctx = None

  def set_params(self, room_size=0.5, brightness=0.5, predelay_ms=0.0, mix=0.5, transition_ms=0, execute_at=0):
    self.dev.set_params(room_size, brightness, predelay_ms, mix, transition_ms, execute_at)

  def detach(self, state=True):
    self.dev.detach(state)

  def enable(self):
    self.dev.active(True)

  def disable(self):
    self.dev.active(False)

  def room(self, val, transition_ms=0, execute_at=0):
    self.set_params(room_size=val, transition_ms=transition_ms, execute_at=execute_at)
  
  def brightness(self, val, transition_ms=0, execute_at=0):
    self.set_params(brightness=val, transition_ms=transition_ms, execute_at=execute_at)

  def predelay(self, val, transition_ms=0, execute_at=0):
    self.set_params(predelay_ms=val, transition_ms=transition_ms, execute_at=execute_at)

  def mix(self, val, transition_ms=0, execute_at=0):
    self.set_params(mix=val, transition_ms=transition_ms, execute_at=execute_at)

  def trigger(self, value, execute_at, duration):
    # Default 'play' for reverb is room_size
    self.set_params(room_size=value, transition_ms=0, execute_at=execute_at)

  def dispatch(self, cmd, val, trans, tick):
    if cmd == "room" or cmd == "size":
      self.room(val, trans, tick)
    elif cmd == "brightness" or cmd == "damp":
      self.brightness(val, trans, tick)
    elif cmd == "predelay":
      self.predelay(val, trans, tick)
    elif cmd == "mix":
      self.mix(val, trans, tick)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

class PieRouter:
  def __init__(self):
    self.dev = audio.router()
    self._ctx = None

  def add(self, module, execute_at=0):
    if hasattr(module, "dev"):
      self.dev.add(module.dev, execute_at)
    else:
      self.dev.add(module, execute_at)

  def clear(self, execute_at=0):
    self.dev.clear(execute_at)

  def clear_events(self):
    self.dev.clear_events()

  def detach(self, state=True):
    self.dev.detach(state)

  def __enter__(self):
    self._ctx = self.dev.__enter__()
    return self

  def __exit__(self, *args):
    self.dev.__exit__(*args)

class Pie:
  def __init__(self, bpm=120, startup_delay_ms=100):
    self.bpm = bpm
    self.startup_delay_ms = startup_delay_ms
    self.patterns = [] # List of (Instrument, Pattern)
    self._running = False
    self._sample_rate = audio.sample_rate()
    self._cycle_duration_samples = int(self._sample_rate * 60 / bpm * 4)
    self._base_tick = 0

  def __enter__(self):
    self.start()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.stop()

  @property
  def playing_cycle(self):
    """Returns the real-time cycle index currently being heard or processed."""
    if not self._running: return 0
    return (audio.get_current_tick() - self._base_tick) / self._cycle_duration_samples

  def get_tick_from_cycle(self, cycle):
    """Converts a sequencer cycle index to an audio tick (sample count)."""
    return self._base_tick + int(cycle * self._cycle_duration_samples)

  def pattern(self, instrument, data):
    """Creates a Pattern object linked to an instrument's preprocessing."""
    preprocess = None
    if hasattr(instrument, "_preprocess"):
      preprocess = instrument._preprocess
    return Pattern.create(data, preprocess)

  def add(self, instrument, pattern):
    if isinstance(pattern, str):
      preprocess = None
      if hasattr(instrument, "_preprocess"):
        preprocess = instrument._preprocess
      pattern = Pattern.create(pattern, preprocess)
      if pattern == None:
        return
    elif not isinstance(pattern, Pattern):
      pattern = Pattern.create(pattern)
      if pattern == None:
        return
    self.patterns.append((instrument, pattern))
    return len(self.patterns) - 1

  def remove(self, index):
    if index < len(self.patterns):
      del self.patterns[index]
    return index

  def update(self, index, pattern):
    if index < len(self.patterns):
      inst = self.patterns[index][0]
      if isinstance(pattern, str):
        preprocess = None
        if hasattr(inst, "_preprocess"):
          preprocess = inst._preprocess
        pattern = Pattern.create(pattern, preprocess=preprocess)
        if pattern == None:
          return
      elif not isinstance(pattern, Pattern):
        pattern = Pattern.create(pattern)
        if pattern == None:
          return
      else:
        # Fresh cache for manually updated Pattern objects
        pattern.clear_cache()
      self.patterns[index] = (inst, pattern)
      return index
    return -1

  def clear(self):
    self.patterns = []

  def process_event(self):
    current_tick = audio.get_current_tick()
    if self._scheduled_until_tick < current_tick:
      self._scheduled_until_tick = current_tick
      
    while self._scheduled_until_tick < current_tick + self._lookahead_samples:
      cycle_start_tick = self._scheduled_until_tick
      cycle_idx = (cycle_start_tick - self._base_tick) // self._cycle_duration_samples
      
      for inst, pat in self.patterns:
        events = pat.get_events(cycle_idx)
        for offset, duration, value in events:
          if value is None: continue
          event_tick = cycle_start_tick + int(offset * self._cycle_duration_samples)
          duration_tick = event_tick + int(duration * self._cycle_duration_samples)
          if event_tick >= current_tick:
            
            try:
              # Support cmd:val:trans automation
              if isinstance(value, tuple) and value[0] is True:
                _, cmd, val, trans = value
                if hasattr(inst, "dispatch"):
                  inst.dispatch(cmd, val, trans, event_tick)
                elif hasattr(inst, cmd):
                  getattr(inst, cmd)(val, trans, event_tick)
                continue
              # Unify playback for Sampler & Wavetable
              inst.trigger(value, event_tick, duration_tick)
            except Exception as e:
              print(f"Playback error: {e} at:{pat.print_str()}, events={events}")
              continue
      self._scheduled_until_tick += self._cycle_duration_samples

  def start(self):
    if self._running: return
    self._is_interactive_read = False
    self._sample_rate = audio.sample_rate() # Ensure rate is current
    self._base_tick = audio.get_current_tick() + (self._sample_rate * self.startup_delay_ms // 1000)
    self._running = True
    self._scheduled_until_tick = self._base_tick
    self._lookahead_samples = self._cycle_duration_samples * 1

  def stop(self):
    self._running = False
    
  def process_interactive(self, filename, loc):
    cycle = self.playing_cycle
    if cycle-int(cycle) > 0.3:
      if self._is_interactive_read:
        return
      self._is_interactive_read = True
      with open(filename,"r") as f:
        d = f.read()
        exec(d, {}, loc)
    else:
     self._is_interactive_read = False

