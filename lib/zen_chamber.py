import esclib
import pdeck
import time
import math
import audio
import array
import random
import dsplib
import pie
from pie import PieWavetable, PieMixer, PieEcho, PieRouter, PieCompressor

# 2D Zen Chamber Demo (v1.1)
# Features: 2D physics, harmonic polyphony, interactive gravity

def generate_sine(size):
  data = bytearray(size * 2)
  for i in range(size):
    val = int(24000 * math.sin(2 * math.pi * i / size))
    data[2*i] = val & 0xFF
    data[2*i+1] = (val >> 8) & 0xFF
  return data

def generate_saw(size):
  data = bytearray(size * 2)
  for i in range(size):
    val = int(24000 * (i / size * 2 - 1))
    data[2*i] = val & 0xFF
    data[2*i+1] = (val >> 8) & 0xFF
  return data

class ZenParticle:
  def __init__(self, x, y, vx, vy, mass=1.0, octave=0, osc_idx=0, color=1):
    self.x = x
    self.y = y
    self.vx = vx
    self.vy = vy
    self.mass = mass
    self.octave = octave # Per-particle octave shift
    self.osc_idx = osc_idx # Tied oscillator channel
    self.radius = int(5 + self.mass * 8)
    self.bounce = random.uniform(0.9, 1.0)
    self.trail_len = random.randint(5, 12)
    self.angle = random.uniform(0, 2 * math.pi)
    self.rot_speed = random.uniform(-0.02, 0.02)
    self.history = []
    self.color = color
    self.last_hit_time = 0

  def update(self, gravity, dt, damping=0.995):
    # Apply physics with delta-time (dt) and mass sensitivity
    self.vx += (gravity[0] / self.mass) * dt
    self.vy += (gravity[1] / self.mass) * dt
    
    # Rotation
    self.angle += self.rot_speed * dt
    
    # Velocity clamping
    mv = 10.0
    self.vx = max(-mv, min(mv, self.vx))
    self.vy = max(-mv, min(mv, self.vy))
    
    self.x += self.vx * dt
    self.y += self.vy * dt
    
    # Add subtle Brownian jitter
    self.vx += random.uniform(-0.02, 0.02) * dt
    self.vy += random.uniform(-0.02, 0.02) * dt
    
    # Friction (scaled by dt)
    fric_factor = math.pow(damping, max(0.0, min(10.0, dt)))
    self.vx *= fric_factor
    self.vy *= fric_factor
    
    # Save history for trails
    self.history.append((self.x, self.y))
    if len(self.history) > self.trail_len:
      self.history.pop(0)
      
    hit = False
    # Left/Right
    if self.x < self.radius:
      self.x = self.radius
      self.vx *= -self.bounce
      hit = True
    elif self.x > 400 - self.radius:
      self.x = 400 - self.radius
      self.vx *= -self.bounce
      hit = True
      
    # Top/Bottom
    if self.y < self.radius:
      self.y = self.radius
      self.vy *= -self.bounce
      hit = True
    elif self.y > 240 - self.radius:
      self.y = 240 - self.radius
      self.vy *= -self.bounce
      hit = True
      
    if hit:
      self.last_hit_time = time.ticks_ms()
      
    return hit

class ZenChamber:
  def __init__(self, vs, echo, synth, mixer, router,comp):
    self.vs = vs
    self.v = vs.v
    
    # Simulation State
    self.particles = [
      ZenParticle(200, 120, 5, 2, 1.5, -1, 0, 1), # Bass particle (Osc 0)
      ZenParticle(200, 120, -3, 6, 0.8, 1, 1, 2)   # Lead particle (Osc 1)
    ]
    self.gravity = [0.0, 0.04]
    self.border_pulse = 0
    self.key_offset = 0 # Root transposition in semitones
    self.btn_state = 0 # Debounce
    self.current_tick = time.ticks_us()
    self.last_tick = self.current_tick
    
    # Musical Scales
    self.scales = [
      ("PENTA", [60, 62, 64, 67, 69, 72, 74, 76, 79, 81]),
      ("H-MINOR", [60, 62, 63, 65, 67, 68, 71, 72, 74, 75])
    ]
    self.scale_idx = 0 # Start with Harmonic Minor
    
    # Blue-ish Persistence: 12,000 byte buffer for 400x240 XBM (50 bytes per row)
    self.frame_capture = bytearray(12000)
    for i in range(12000): self.frame_capture[i] = 0
    
    # Audio Setup
    self.router = router
    self.echo = echo
    self.synth = synth
    self.mixer = mixer
    self.comp = comp
    
    self.router.add(self.synth)
    self.router.add(self.echo)
    self.router.add(self.mixer)
    
    self.echo.set_type("ping_pong")
    self.echo.set_params(time_ms=150, feedback=0.2)
    
    # Init Wavetables
    sine = generate_sine(256)
    saw = generate_saw(256)
    
    # Explicitly set wavetable per oscillator for maximum reliability
    for i in range(4):
      self.synth.dev.set_wavetable(i, [sine, saw])
      self.synth.dev.set_adsr(i, 2, 4000, 0.05, 1)
      self.synth.dev.volume(i, 0.3)
    
    self.comp.set_params(1.4,2.0)
    #self.synth.volume(0.8)

  def process_audio_trigger(self, dt):
    # Audio Trigger System
    for p in self.particles:
      if p.update(self.gravity, dt):
        # Current Scale Mapping with per-particle Octave
        scale_name, scale_notes = self.scales[self.scale_idx]
        idx = int((p.y / 240.0) * (len(scale_notes)-1))
        # Base note + Particle-specific Octave + Global Key Transposition
        note = scale_notes[max(0, min(len(scale_notes)-1, idx))] + (p.octave * 12) + self.key_offset
        
        speed = math.sqrt(p.vx**2 + p.vy**2)
        #vol = min(0.9, speed / 8.0)
        
        # Play blip with per-particle oscillator and dynamic volume
        decay = 40 + random.randint(-10,60)
        #self.synth.dev.set_adsr(p.osc_idx, 2, decay, 0.1, 120)
        #self.synth.dev.volume(p.osc_idx, vol)
        
        #print("Hit! P:", p.osc_idx, "Note:", note, "Vol:", vol)
        
        self.synth.play(p.osc_idx, note)
        self.border_pulse = 12 # Pulse border on hit
        # Visual rotation "kick" on hit - Reduced magnitude
        p.rot_speed = random.uniform(-0.2, 0.2)
      
  def set_morph(self, val):
    # Smoothly morph from Sine (0.0) to Saw (1.0)
    # val comes from Slider (0-255)
    morph_factor = min(1.0, max(0.0, val / 255.0))
    self.synth.morph(morph_factor)

  def process_collisions(self, dt):
    # Inter-particle repulsion (Soft Collision)
    for i in range(len(self.particles)):
      for j in range(i + 1, len(self.particles)):
        p1 = self.particles[i]
        p2 = self.particles[j]
        
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        dist_sq = dx*dx + dy*dy
        min_dist = p1.radius + p2.radius
        
        if dist_sq < min_dist * min_dist and dist_sq > 0.01:
          dist = math.sqrt(dist_sq)
          # Push force proportional to overlap
          force = (min_dist - dist) * 0.05 * dt
          nx = dx / dist
          ny = dy / dist
          
          p1.vx -= nx * force / p1.mass
          p1.vy -= ny * force / p1.mass
          p2.vx += nx * force / p2.mass
          p2.vy += ny * force / p2.mass

  def handle_input(self, tp):
    if tp is None: return
    
    # Exit on 'Bottom Right' button (tp[6] bit 0)
    # Check if tp has at least 7 bytes
    if len(tp) >= 7 and tp[3] & 2 != 0:
      self.v.callback(None)
      self.v.finished()
      return

    # Scale control (A/B buttons: tp[6] bit 0/1, X: bit 2)
    # Circle of Fifths transposition & Scale Mode toggle
    current_btns = tp[6] & 0x07
    if current_btns != self.btn_state:
      if current_btns & 0x01 == 0x01: # A button (Clockwise: +7 semitones)
        self.key_offset = (self.key_offset + 7) % 12
      if current_btns & 0x02 == 0x02: # B button (Counter-Clockwise: -7 semitones)
        self.key_offset = (self.key_offset - 7) % 12
      if current_btns & 0x03 == 0x03: # A+B button (Toggle Scale Mode)
        self.scale_idx = (self.scale_idx + 1) % len(self.scales)
      self.btn_state = current_btns

    # Gravity control (Touchpad) - Reduced sensitivity
    if tp[1] != 0xFF and tp[2] != 0xFF:
      self.gravity[0] = (tp[2] - 50) / 500.0
      self.gravity[1] = (tp[1] - 40) / 400.0
    
    # Simulation energy & Morph (Slider)
    if tp[0] != 0xFF:
      # Slider controls both energy and sonic morphing
      self.set_morph(tp[0])
      if tp[0] > 10:
        for p in self.particles:
          p.vx *= 1.05
          p.vy *= 1.05
    
    # Particle count (Dial)
    if tp[4] != 0xFF:
      target_count = 1 + (tp[4] // 30)
      while len(self.particles) < target_count and len(self.particles) < 8:
        # Smart Oscillator Assignment: Try to get a free channel first
        used_oscs = {p.osc_idx for p in self.particles}
        free_oscs = [i for i in range(4) if i not in used_oscs]
        
        if free_oscs:
          osc = free_oscs[0]
        else:
          osc = random.randint(0, 3)
          
        # Randomize new particles: higher mass nodes lean towards bass
        m = random.uniform(0.5, 3.0)
        o = 0 if m < 1.0 else -int(1)
        col = 1 if o < 0 else 2
        self.particles.append(ZenParticle(200, 120, 2, 2, m, o, osc, col))
      while len(self.particles) > target_count and len(self.particles) > 1:
        self.particles.pop()

  def draw_chamber(self):
    self.v.set_draw_color(1)
    self.v.set_dither(16)
    # Static outer frame
    self.v.draw_frame(0, 0, 400, 240)
    
    if self.border_pulse > 0:
      self.v.set_draw_color(2) # XOR for pulse
      b = self.border_pulse
      self.v.draw_box(0, 0, 400, b)
      self.v.draw_box(0, 240-b, 400, b)
      self.v.draw_box(0, 0, b, 240)
      self.v.draw_box(400-b, 0, b, 240)
      self.border_pulse -= 1
    self.v.set_dither(16)

  def draw_particles(self):
    self.v.set_draw_color(2) # XOR for particles
    
    # Pre-allocate matrices for dsplib (3 points x 2 coords)
    # Equilateral triangle coords [x1, y1, x2, y2, x3, y3]
    pts_rel = array.array('f', [0.0, 1.0, -0.866, -0.5, 0.866, -0.5]) 
    rot_mat = array.array('f', [0.0] * 4)
    pts_rot = array.array('f', [0.0] * 6)
    poly_buf = array.array('h', [0] * 6)

    for p in self.particles:
      s = p.radius
      # Core (Rotating Triangle)
      cosa = math.cos(p.angle)
      sina = math.sin(p.angle)
      
      # Update rotation matrix
      rot_mat[0] = cosa; rot_mat[1] = -sina
      rot_mat[2] = sina; rot_mat[3] = cosa
      
      # Use dsplib for rotation: pts_rot = pts_rel * rot_mat
      dsplib.matrix_mul_f32(pts_rel, rot_mat, 3, 2, 2, pts_rot)
      
      # Prepare polygon buffer: [x1, x2, x3, y1, y2, y3]
      poly_buf[0] = int(p.x + pts_rot[0] * s)
      poly_buf[1] = int(p.x + pts_rot[2] * s)
      poly_buf[2] = int(p.x + pts_rot[4] * s)
      poly_buf[3] = int(p.y + pts_rot[1] * s)
      poly_buf[4] = int(p.y + pts_rot[3] * s)
      poly_buf[5] = int(p.y + pts_rot[5] * s)
      
      self.v.set_dither(16)
      self.v.draw_polygon(poly_buf)
      
      # Hit Flash (Outer dithered triangle)
      if time.ticks_diff(time.ticks_ms(), p.last_hit_time) < 100:
        self.v.set_dither(8)
        poly_buf[0] = int(p.x + pts_rot[0] * (s+4))
        poly_buf[1] = int(p.x + pts_rot[2] * (s+4))
        poly_buf[2] = int(p.x + pts_rot[4] * (s+4))
        poly_buf[3] = int(p.y + pts_rot[1] * (s+4))
        poly_buf[4] = int(p.y + pts_rot[3] * (s+4))
        poly_buf[5] = int(p.y + pts_rot[5] * (s+4))
        self.v.draw_polygon(poly_buf)
        
    self.v.set_dither(16)

  def draw_ui(self):
    self.v.set_draw_color(1)
    self.v.set_dither(16)
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(10, 20, "ZEN CHAMBER")
    self.v.draw_str(10, 34, "Bottom-right button: quit")
    self.v.draw_str(10, 46, "D-pad: Spawn particles")
    self.v.draw_str(10, 58, "Touchpad: Gravity")
    self.v.draw_str(10, 70, "A,B: Scale")
    self.v.draw_str(10, 82, "Slider: energy")
    self.v.draw_str(10, 230, f"G: {self.gravity[0]*100:.1f}, {self.gravity[1]*100:.1f}")
    
    self.draw_key_circle(200, 45, 35)
    
    self.v.draw_str(300, 230, f"PARTICLES: {len(self.particles)}")

  def draw_key_circle(self, cx, cy, r):
    keys = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    # Circle of Fifths order for visualization
    # 0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5
    cof_order = [0, 7, 2, 9, 4, 11, 6, 1, 8, 3, 10, 5]
    
    self.v.set_draw_color(1)
    # Draw current key & scale name in center
    scale_name, _ = self.scales[self.scale_idx]
    current_key = keys[self.key_offset % 12]
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(cx - 15, cy - 2, scale_name)
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(cx - 5, cy + 12, current_key)
    
    # Draw nodes in circle
    for i in range(12):
      angle = (i * 30 - 90) * (math.pi / 180.0)
      px = int(cx + math.cos(angle) * r)
      py = int(cy + math.sin(angle) * r)
      
      key_idx = cof_order[i]
      if key_idx == self.key_offset % 12:
        self.v.set_draw_color(2) # XOR highlight
        self.v.draw_disc(px, py, 4, 15)
        self.v.set_draw_color(1)
      else:
        self.v.draw_disc(px, py, 1, 15)

  def update(self, e):
    
    # 1. Draw Blue-ish Persistence (Decaying history)
    # Drift the "ether" in the direction of gravity
    dx = int(self.gravity[0] * 30)
    dy = int(self.gravity[1] * 30)
    #self.v.set_draw_color(1)
    
    self.current_tick = time.ticks_us()
    self.time_diff = time.ticks_diff(self.current_tick, self.last_tick) / 10000.0
    self.last_tick = self.current_tick
    
    self.handle_input(self.v.get_tp_keys())
    self.process_audio_trigger(self.time_diff)
    self.process_collisions(self.time_diff)
    
    # 2. Draw World State
    self.v.set_dither(16)
    self.draw_chamber()

    self.v.switch_buffer(1)
    self.v.clear_buffer()
    if self.border_pulse > 6:
      self.v.draw_xbm(dx, dy, 400, 240, self.frame_capture)
    else:
      self.v.clear_buffer()
    self.draw_particles()
    self.v.capture_as_xbm(0, 0, 400, 240, self.frame_capture)
    self.v.switch_buffer(0)
    # 3. Capture for Next Frame persistence
    self.v.draw_xbm(0, 0, 400, 240, self.frame_capture)

    # 4. Draw UI (Top layer, no persistence)
    self.draw_ui()
    self.v.finished()

def main(vs, args):
  v = vs.v
  el = esclib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  
  audio.power(True)
  audio.sample_rate(24000)
  with PieEcho(1000) as echo, PieWavetable(4) as synth, PieMixer() as mixer, PieRouter() as router, PieCompressor() as comp:
    demo = ZenChamber(vs, echo, synth, mixer, router, comp)
    v.callback(demo.update)
    
    try:
      while True:
        # Get random key state to reset key buffer
        v.get_key_state(0x50)
        time.sleep(0.1)
        if not v.callback_exists():
          break
    except KeyboardInterrupt:
      pass
    finally:
      v.callback(None)
      v.print(el.display_mode(True))

if __name__ == "__main__":
  from pdeck import VirtualScreen
  main(VirtualScreen(), None)
