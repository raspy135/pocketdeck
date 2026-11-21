# Generates lib/data/chop_demo.wav — the take `chop` loads when started with
# no file: six synthesized drum hits spread across the stereo field, then a
# vowel-sweep drone for the wavetable to read. 24 kHz, 16-bit, stereo, 3 s.
#
# Run from the repo root:  python -B utils/gen_chop_demo.py
import math, random, struct, wave

RATE = 24000
N = RATE * 3
L = [0.0] * N
R = [0.0] * N
rnd = random.Random(7)

def put(t, sig, pan):
  # pan: -1 left .. 1 right (equal power)
  a = (pan + 1) * math.pi / 4
  gl, gr = math.cos(a), math.sin(a)
  o = int(t * RATE)
  for i, s in enumerate(sig):
    if o + i < N:
      L[o + i] += s * gl
      R[o + i] += s * gr

def kick():
  out, ph = [], 0.0
  for i in range(5000):
    ph += 2 * math.pi * (45 + 140 * math.exp(-i / 500)) / RATE
    out.append(math.sin(ph) * math.exp(-i / 1700))
  return out

def snare():
  return [(0.75 * rnd.uniform(-1, 1) * math.exp(-i / 900) +
           0.5 * math.sin(2 * math.pi * 190 * i / RATE) * math.exp(-i / 500)) for i in range(4500)]

def hat(decay, n):
  # high-passed noise: difference of successive samples
  out, prev = [], 0.0
  for i in range(n):
    x = rnd.uniform(-1, 1)
    out.append((x - prev) * 0.9 * math.exp(-i / decay))
    prev = x
  return out

def blip():
  # FM tom
  return [math.sin(2 * math.pi * 220 * i / RATE + 3 * math.exp(-i / 400) * math.sin(2 * math.pi * 330 * i / RATE))
          * math.exp(-i / 1400) for i in range(4500)]

def clap():
  out = []
  for i in range(4500):
    burst = sum(math.exp(-((i - d) % 100000) / 120) for d in (0, 260, 520) if i >= d)
    out.append(rnd.uniform(-1, 1) * min(1.0, burst) * math.exp(-i / 1500) * 0.8)
  return out

def drone(detune):
  # 93.75 Hz = exactly one cycle per 256-sample wavetable frame at 24 kHz.
  # 40 harmonics under a formant that sweeps 300 -> 2600 Hz ("oo-ah-ee").
  f0 = 93.75 * detune
  n = int(1.15 * RATE)
  out = []
  for i in range(n):
    t = i / n
    fc = 300 * (2600 / 300) ** t
    s = 0.0
    for h in range(1, 41):
      f = f0 * h
      s += (0.25 / h + math.exp(-((f - fc) / (220 + fc * 0.15)) ** 2)) * math.sin(2 * math.pi * f * i / RATE)
    out.append(s * 0.3 * min(1.0, i / 200) * min(1.0, (n - i) / 1500))
  return out

put(0.05, kick(), 0.0)
put(0.35, snare(), 0.25)
put(0.62, hat(250, 1500), -0.7)
put(0.85, hat(1400, 5000), 0.7)
put(1.12, blip(), -0.4)
put(1.40, clap(), 0.4)
put(1.75, drone(1.0), -1.0)      # the two detuned copies beat against each other
put(1.75, drone(1.004), 1.0)     # across the stereo field

pk = max(max(map(abs, L)), max(map(abs, R)))
g = 30000 / pk
frames = bytearray()
for l, r in zip(L, R):
  frames += struct.pack('<hh', int(l * g), int(r * g))
with wave.open('lib/data/chop_demo.wav', 'wb') as w:
  w.setnchannels(2)
  w.setsampwidth(2)
  w.setframerate(RATE)
  w.writeframes(bytes(frames))
print('wrote lib/data/chop_demo.wav', len(frames), 'bytes')
