import pdeck
import pdeck_utils
import esclib as elib
import time
import array
import math
import random
import dsplib as dl
import audio
import wav_play


# ------------------------------------------------------------
# Invader game specification
# ------------------------------------------------------------
# - Modern invader-style game with 30~60 FPS target
# - Time-delta based physics
# - Two enemy types
# - Explosion effect on laser hit
# - Player hit effect on bullet hit
# - Enemy collision with player
# - Controls:
#   * Left/Right arrow: move
#   * A: shoot laser
#   * left mouse button: quit
# - Uses simple 3D polygons for galaxy background, explosions, and laser/bullet
# - Stage advances when all enemies are destroyed
# ------------------------------------------------------------

SCREEN_W = 400
SCREEN_H = 240

FPS_DT = 1.0 / 60.0
MAX_DT = 0.05

PLAYER_SPEED = 180.0
LASER_SPEED = 260.0
BULLET_SPEED = 120.0
ENEMY_BULLET_INTERVAL = 1.6

EXPLOSION_TIME = 0.45
INVULN_TIME = 1.0

GALAXY_CUBE_COUNT = 18
STARS_COUNT = 36

# Enemy movement tuning
ENEMY_SWAY_SPEED = 1.8
ENEMY_SWAY_AMOUNT = 10.0
ENEMY_DESCEND_STEP = 10.0
ENEMY_EDGE_MARGIN = 16

# Stage scaling
MAX_STAGE_COLS_BONUS = 2
MAX_STAGE_ROWS_BONUS = 2

# Power-up / item drop
ITEM_DROP_CHANCE = 0.20
ITEM_ROT_SPEED = 5.5
ITEM_TIME = 8.0
ITEM_RADIUS = 9.0

# Player power levels:
# 0 = 1-way, 1 = 2-way, 2 = 3-way, 3 = 6-way
PLAYER_POWER_MAX = 2
PLAYER_SHOOT_COOL = [0.14, 0.13, 0.11, 0.095]

# Sound
SND_FIRE = 0
SND_EXPLOSION = 1
SND_HIT = 2
SND_PLAYER_HIT = 3
SND_STAGE_CLEAR = 4
SND_ALIEN_MOVE = 5
SND_ALIEN_DROP = 6
SND_BOMB = 7
SND_ITEM = 8
SND_POWERUP = 9

# 3D cube geometry for background/explosion/lights
CUBE_VERTS = array.array('f', [
  -1, -1, -1,
   1, -1, -1,
   1,  1, -1,
  -1,  1, -1,
  -1, -1,  1,
   1, -1,  1,
   1,  1,  1,
  -1,  1,  1,
])

CUBE_INDICES = array.array('H', [
  0, 1, 2,  0, 2, 3,
  1, 5, 6,  1, 6, 2,
  5, 4, 7,  5, 7, 6,
  4, 0, 3,  4, 3, 7,
  3, 2, 6,  3, 6, 7,
  4, 5, 1,  4, 1, 0,
])

# Face normals for cube triangles
CUBE_NORMALS = array.array('f', [
  0, 0, -1,  0, 0, -1,
  1, 0,  0,  1, 0,  0,
  0, 0,  1,  0, 0,  1,
  -1, 0, 0, -1, 0, 0,
  0, 1,  0,  0, 1,  0,
  0, -1, 0,  0, -1, 0,
])

# Low-poly sphere-ish geometry for bomb effect
SPHERE_VERTS = array.array('f', [
  0.0, 1.0, 0.0,
  -0.55, 0.45, -0.45,
  0.55, 0.45, -0.45,
  0.55, 0.45, 0.45,
  -0.55, 0.45, 0.45,
  -0.45, -0.4, -0.35,
  0.45, -0.4, -0.35,
  0.45, -0.4, 0.35,
  -0.45, -0.4, 0.35,
  0.0, -0.85, 0.0,
])

SPHERE_INDICES = array.array('H', [
  0, 1, 2,
  0, 2, 3,
  0, 3, 4,
  0, 4, 1,
  1, 5, 6,
  2, 6, 7,
  3, 7, 8,
  4, 8, 5,
  1, 2, 6,
  2, 3, 7,
  3, 4, 8,
  4, 1, 5,
  5, 6, 9,
  6, 7, 9,
  7, 8, 9,
  8, 5, 9,
])

SPHERE_NORMALS = array.array('f', [
  0, 1, 0,
  0, 1, 0,
  0, 1, 0,
  0, 1, 0,
  0, 1, 0,
  -0.3, -0.7, -0.2,
  0.3, -0.7, -0.2,
  0.3, -0.7, 0.2,
  -0.3, -0.7, 0.2,
  0, -1, 0,
  -0.2, 0.3, -0.7,
  0.5, 0.3, -0.5,
  0.5, 0.3, 0.5,
  -0.5, 0.2, 0.5,
  -0.3, -0.8, 0.1,
  0.2, -0.7, -0.2,
  0.2, -0.7, 0.2,
  -0.2, -0.7, 0.2,
])

# Hex item geometry
HEX_GEOMS = {
  'verts' : array.array('f', [
    1.0, 0.0,
    0.5, 0.866,
    -0.5, 0.866,
    -1.0, 0.0,
    -0.5, -0.866,
    0.5, -0.866,
  ]),
  'indices': array.array('H', [
    0, 1, 2,
    0, 2, 3,
    0, 3, 4,
    0, 4, 5,
  ]),
  'face_indices': array.array('H', [0, 1, 2, 3]),
  'colors': array.array('f', [15] * 6),
  'out_poly': array.array('h', [0] * 4 * 6),
  'out_dither': array.array('b', [0] * 4),
}

# Player geometry by power level
PLAYER_POWER_GEOMS = [
  {
    'verts': array.array('f', [
      0.0, -1.2,
      -0.9, 0.9,
      0.9, 0.9,
    ]),
    'indices': array.array('H', [0, 1, 2]),
    'face_indices': array.array('H', [0]),
    'colors': array.array('f', [15] * 3),
    'out_poly': array.array('h', [0] * 1 * 6),
    'out_dither': array.array('b', [0] * 1),
  },
  {
    'verts': array.array('f', [
      0.0, -1.25,
      -0.95, 0.85,
      0.95, 0.85,
      -0.85, 0.25,
      0.85, 0.25,
    ]),
    'indices': array.array('H', [0, 1, 2, 1, 3, 4, 2, 4, 3]),
    'face_indices': array.array('H', [0, 1, 2]),
    'colors': array.array('f', [15] * 5),
    'out_poly': array.array('h', [0] * 3 * 6),
    'out_dither': array.array('b', [0] * 3),
  },
  {
    'verts': array.array('f', [
      0.0, -1.35,
      -1.0, 0.8,
      1.0, 0.8,
      -1.75, 0.15,
      0.0, 0.0,
      1.75, 0.15,
    ]),
    'face_indices': array.array('H', [0, 1, 2, 3]),
    'indices': array.array('H', [0, 1, 2, 1, 3, 4, 2, 4, 5, 3, 4, 5]),
    'colors': array.array('f', [15] * 6),
    'out_poly': array.array('h', [0] * 4 * 6),
    'out_dither': array.array('b', [0] * 4),
  },
  {
    'verts': array.array('f', [
      0.0, -1.35,
      -1.1, 0.7,
      1.1, 0.7,
      -0.9, -0.15,
      -0.35, 0.25,
      0.35, 0.25,
      0.9, -0.15,
    ]),
    'face_indices': array.array('H', [0, 1, 2, 3, 4, 5, 6]),
    'indices': array.array('H', [
      0, 1, 2,
      1, 3, 4,
      2, 4, 6,
      3, 4, 5,
      4, 5, 6,
      1, 4, 3,
      2, 6, 5,
    ]),
    'colors': array.array('f', [15] * 7),
    'out_poly': array.array('h', [0] * 7 * 6),
    'out_dither': array.array('b', [0] * 7),
  },
]

def clamp(v, lo, hi):
  if v < lo:
    return lo
  if v > hi:
    return hi
  return v

def rect_hit(ax, ay, aw, ah, bx, by, bw, bh):
  return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)

def make_square_wave(table_size=256):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    phase = i / table_size
    frame[i] = 18000 if phase < 0.3 else -18000
  return [frame]

def make_triangle_wave(table_size=256):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    phase = (i / table_size) * 2 * math.pi
    val = 2 * abs(phase / math.pi - 1) - 1
    frame[i] = int(val * 20000)
  return [frame]

def make_noise_wave(table_size=256):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    frame[i] = int(random.uniform(-1, 1) * 14000)
  return [frame]

class InvaderGame:
  def __init__(self, vs, wavetable=None):
    self.vs = vs
    self.v = vs.v
    self.wt = wavetable
    self.exited = False
    self.last_us = time.ticks_us()
    self.accum = 0.0

    self.state = "title"
    self.stage = 1
    self.score = 0
    self.lives = 3

    self.player_x = SCREEN_W * 0.5
    self.player_y = SCREEN_H - 24
    self.player_w = 28
    self.player_h = 12
    self.player_cool = 0.0
    self.invuln = 0.0
    self.player_power = 0
    self.player_power_anim = 0.0

    self.lasers = []
    self.enemy_bullets = []
    self.explosions = []
    self.bombs = []
    self.items = []
    self.enemies = []
    self.enemy_fire_timer = 0.0

    self.keys_prev = b""
    self.quit_requested = False

    self.formation_dir = 1
    self.formation_phase = 0.0
    self.formation_sway = 0.0
    self.formation_drop = 0.0
    self.formation_bounds = [0.0, 0.0, 0.0, 0.0]
    self.special_move_timer = 4.0
    self.special_move_kind = 0

    self.sound_enabled = False
    self._init_sound()

    self.bgm = None
    self.bgm_playing = False
    self._init_bgm()

    self.matrix = array.array('f', [0.0] * 16)
    self.matrix2 = array.array('f', [0.0] * 16)
    self.matrix3 = array.array('f', [0.0] * 16)
    self.matrix2d = array.array('f', [0.0] * 9)
    self.rot = array.array('f', [0.0, 0.0, 0.0])
    self.pos = array.array('f', [0.0, 0.0, 0.0])
    self.scale = array.array('f', [1.0, 1.0, 1.0])
    self.light = array.array('f', [0.3, 0.6, -1.0])
    self.rot2d = array.array('f', [0.0, 0.0])
    self.pos2d = array.array('f', [0.0, 0.0])
    self.scale2d = array.array('f', [1.0, 1.0])
    self.num_faces = len(CUBE_INDICES) // 3
    self.num_verts = len(CUBE_VERTS) // 3

    self.out_poly = array.array('h', [0] * (self.num_faces * 6))
    self.out_dither = array.array('b', [0] * self.num_faces)
    self.face_indices = array.array('H', list(range(self.num_faces)))
    self.depths = array.array('i', [0] * self.num_faces)
    self.temp_verts = array.array('f', [0.0] * (self.num_verts * 3))
    self.temp_norms = array.array('f', [0.0] * (self.num_faces * 3))

    self.sphere_out_poly = array.array('h', [0] * (len(SPHERE_INDICES) // 3 * 6))
    self.sphere_out_dither = array.array('b', [0] * (len(SPHERE_INDICES) // 3))
    self.sphere_face_indices = array.array('H', list(range(len(SPHERE_INDICES) // 3)))
    self.sphere_depths = array.array('i', [0] * (len(SPHERE_INDICES) // 3))
    self.sphere_temp_verts = array.array('f', [0.0] * (len(SPHERE_VERTS) // 3 * 3))
    self.sphere_temp_norms = array.array('f', [0.0] * (len(SPHERE_INDICES) // 3 * 3))

    self.galaxy = []
    self.stars = []
    self._init_background()
    self._init_stage()

  def _init_sound(self):
    try:
      audio.sample_rate(24000)
      self.sound_enabled = True
    except Exception as e:
      print("audio init failed:", e)
      self.sound_enabled = False

    self.sound = None
    if self.sound_enabled:
      try:
        self.sound = audio.wavetable(5)
        self.sound.__enter__()
        self.sound.set_wavetable(0, make_square_wave(256))
        self.sound.copy_table(3, 0)
        self.sound.set_wavetable(1, make_triangle_wave(256))
        self.sound.set_wavetable(2, make_noise_wave(256))
        self.sound.copy_table(4, 2)
        self.sound.set_adsr(0, 2, 380, 0.0, 0.05)
        self.sound.set_adsr(1, 1, 120, 0.0, 0.08)
        self.sound.set_adsr(2, 1, 40, 0.0, 0.08)
        self.sound.set_adsr(4, 1, 40, 0.3, 0.43)
        self.sound.set_adsr(3, 1, 180, 0.0, 0.15)
      except Exception as e:
        print("wavetable init failed:", e)
        self.sound_enabled = False
        self.sound = None

  def _init_bgm(self):
    try:
      self.bgm = wav_play.wav_play(10000)
      self.bgm.open('/sd/lib/data/invader.wav')
      #self.bgm_playing = True
      #self.bgm.play()
    except Exception as e:
      print("bgm init failed:", e)
      self.bgm = None
      self.bgm_playing = False

  def _update_bgm(self):
    if self.bgm is None:
      return
    try:
      if self.bgm_playing and not audio.stream_play():
        self.bgm.seek(0)
        self.bgm.play()
    except Exception:
      pass

  def _play_sound(self, kind):
    if not self.sound_enabled or self.sound is None:
      return
    try:
      if kind == SND_FIRE:
        self.sound.frequency(0, 720)
        self.sound.volume(0, 0.15)
        self.sound.pitch(0, 1.0)
        self.sound.pitch(0, 0.8, 100)
        self.sound.note_on(0)
      elif kind == SND_EXPLOSION:
        self.sound.frequency(2, 120)
        self.sound.volume(2, 0.5)
        self.sound.note_on(2)
        self.sound.note_off(2, "+0.12s")
      elif kind == SND_HIT:
        self.sound.frequency(1, 240)
        self.sound.volume(1, 0.5)
        self.sound.note_on(1)
        self.sound.note_off(1, "+0.06s")
      elif kind == SND_PLAYER_HIT:
        self.sound.frequency(4, 80)
        self.sound.volume(4, 0.6)
        self.sound.note_on(4)
        self.sound.note_off(4, "+0.38s")
      elif kind == SND_STAGE_CLEAR:
        self.sound.frequency(1, 440)
        self.sound.volume(1, 0.6)
        self.sound.note_on(1)
        self.sound.note_off(1, "+0.22s")
        self.sound.frequency(1, 440 * 1.3, "+0.23s")
        self.sound.note_on(1, "+0.23s")
        self.sound.note_off(1, "+0.44s")
        self.sound.frequency(1, 440 * 1.3 * 1.3, "+0.45s")
        self.sound.note_on(1, "+0.45s")
        self.sound.note_off(1, "+0.66s")
      elif kind == SND_ALIEN_MOVE:
        self.sound.frequency(3, 660)
        self.sound.volume(3, 0.25)
        self.sound.note_on(3)
        self.sound.note_off(3, "+0.03s")
      elif kind == SND_ALIEN_DROP:
        self.sound.frequency(1, 180)
        self.sound.volume(1, 0.45)
        self.sound.note_on(1)
        self.sound.note_off(1, "+0.05s")
      elif kind == SND_BOMB:
        self.sound.frequency(2, 95)
        self.sound.volume(2, 0.3)
        self.sound.note_on(2)
        self.sound.note_off(2, "+0.14s")
      elif kind == SND_ITEM:
        self.sound.frequency(3, 200)
        self.sound.pitch(3, 1)
        self.sound.volume(3, 0.55)
        self.sound.pitch(3, 1.5, 200)
        self.sound.note_on(3)
        self.sound.note_off(3, "+0.35s")
      elif kind == SND_POWERUP:
        self.sound.frequency(1, 520)
        self.sound.volume(1, 0.9)
        self.sound.note_on(1)
        self.sound.note_off(1, "+0.18s")
        self.sound.frequency(1, 1040, "+0.45s")
        self.sound.note_on(1, "+0.46s")
        self.sound.note_off(1, "+0.7s")
    except Exception:
      pass

  def _init_background(self):
    self.galaxy = []
    for i in range(GALAXY_CUBE_COUNT):
      self.galaxy.append({
        'x': random.uniform(-240, 240),
        'y': random.uniform(-150, 150),
        'z': random.uniform(180, 700),
        's': random.uniform(2, 12),
        'vx': random.uniform(-6, 6),
        'vy': random.uniform(-4, 4),
        'vz': random.uniform(-25, -8) * 3,
        'rx': random.uniform(0, math.pi * 2),
        'ry': random.uniform(0, math.pi * 2),
        'rz': random.uniform(0, math.pi * 2),
      })
    self.stars = []
    for i in range(STARS_COUNT):
      self.stars.append({
        'x': random.uniform(0, SCREEN_W),
        'y': random.uniform(0, SCREEN_H),
        's': random.uniform(0.8, 2.3),
        'v': random.uniform(10, 40),
      })

  def _make_alien(self, x, y, etype):
    hp = 1 if etype == 1 else 2
    if self.stage >= 3 and etype == 2:
      hp = 3
    return {
      'x': x, 'y': y, 'base_x': x, 'base_y': y,
      'w': 22 if etype == 1 else 24,
      'h': 16 if etype == 1 else 18,
      'type': etype, 'hp': hp, 'phase': random.uniform(0, math.pi * 2),
      'vx': 0.0, 'vy': 0.0, 'special': 0, 'special_t': 0,
      'fade': 0.0, 'dead': False, 'spawn_t': 0.0, 'die_t': 0.0, 'alive': True,
    }

  def _init_stage(self):
    self.enemies = []
    rows = min(4, 3 + min(self.stage // 3, MAX_STAGE_ROWS_BONUS))
    cols = min(7, 4 + min(self.stage // 4, MAX_STAGE_COLS_BONUS))
    base_x = 48
    base_y = 42
    gap_x = 42
    gap_y = 26
    for r in range(rows):
      for c in range(cols):
        etype = 1 if (r + c) % 2 == 0 else 2
        e = self._make_alien(base_x + c * gap_x, base_y + r * gap_y, etype)
        e['spawn_t'] = 0.0
        self.enemies.append(e)
    self.formation_dir = 1
    self.formation_phase = 0.0
    self.formation_sway = 0.0
    self.formation_drop = 0.0
    self.enemy_fire_timer = 0.4 / (self.stage * 0.5)
    self.special_move_timer = random.uniform(3.0, 6.0)
    self._recalc_enemy_bounds()

  def _recalc_enemy_bounds(self):
    if not self.enemies:
      self.formation_bounds = [0, 0, 0, 0]
      return
    minx = 9999
    miny = 9999
    maxx = -9999
    maxy = -9999
    for e in self.enemies:
      if e.get('alive', True) and e['special'] == 0.0:
        minx = min(minx, e['x'])
        miny = min(miny, e['y'])
        maxx = max(maxx, e['x'] + e['w'])
        maxy = max(maxy, e['y'] + e['h'])
    self.formation_bounds = [minx, miny, maxx, maxy]

  def reset_game(self):
    self.stage = 1
    self.score = 0
    self.lives = 3
    self.player_x = SCREEN_W * 0.5
    self.player_cool = 0.0
    self.invuln = 1.0
    self.player_power = 0
    self.player_power_anim = 0.0
    self.lasers = []
    self.enemy_bullets = []
    self.explosions = []
    self.bombs = []
    self.items = []
    self._init_background()
    self._init_stage()
    self.state = "play"
    if self.bgm:
      self.bgm.seek(0)
      self.bgm_playing = True
      self.bgm.play()

  def spawn_explosion(self, x, y, kind=0):
    self.explosions.append({
      'x': x, 'y': y, 't': 0.0, 'kind': kind,
      's': random.uniform(10, 18) if kind == 0 else random.uniform(14, 24),
    })

  def spawn_bomb(self, x, y, size=1.0, last=False):
    self.bombs.append({
      'x': x - 200, 'y': y - 50, 't': 0.0, 's': 14.0 * size, 'last': last,
      'spin': random.uniform(0, math.pi * 2), 'vx': random.uniform(-14, 14),
      'vy': random.uniform(-18, -8), 'z': 100.0,
    })
    self._play_sound(SND_BOMB)

  def spawn_item(self, x, y):
    self.items.append({
      'x': x, 'y': y, 't': 0.0, 'spin': random.uniform(0, math.pi * 2),
      'vx': random.uniform(-20, 20), 'vy': random.uniform(25, 45), 'z': 80.0,
    })
    self._play_sound(SND_ITEM)

  def shoot_laser(self):
    if self.player_cool > 0.0:
      return
    power = self.player_power
    self.player_cool = PLAYER_SHOOT_COOL[power]
    if power == 0:
      self.lasers.append({'x': self.player_x - 2, 'y': self.player_y - 10, 'w': 4, 'h': 10, 'vy': -LASER_SPEED})
    elif power == 1:
      self.lasers.append({'x': self.player_x - 10, 'y': self.player_y - 10, 'w': 4, 'h': 10, 'vy': -LASER_SPEED})
      self.lasers.append({'x': self.player_x + 6, 'y': self.player_y - 10, 'w': 4, 'h': 10, 'vy': -LASER_SPEED})
    elif power == 2:
      self.lasers.append({'x': self.player_x - 2, 'y': self.player_y - 10, 'w': 4, 'h': 10, 'vy': -LASER_SPEED})
      self.lasers.append({'x': self.player_x - 12, 'y': self.player_y - 8, 'w': 4, 'h': 10, 'vy': -LASER_SPEED * 0.96})
      self.lasers.append({'x': self.player_x + 8, 'y': self.player_y - 8, 'w': 4, 'h': 10, 'vy': -LASER_SPEED * 0.96})
    else:
      for dx in (-16, -8, 0, 8, 16, 0):
        self.lasers.append({'x': self.player_x + dx - 2, 'y': self.player_y - 10, 'w': 4, 'h': 10, 'vy': -LASER_SPEED})
    self._play_sound(SND_FIRE)

  def enemy_fire(self):
    if not self.enemies:
      return
    e = random.choice(self.enemies)
    stage_bonus = min(self.stage * 0.03, 0.35)
    speed = BULLET_SPEED + random.uniform(-20, 20) + self.stage * 4.0
    if random.random() < stage_bonus:
      speed += 30.0
    self.enemy_bullets.append({
      'x': e['x'] + e['w'] * 0.5 - 2,
      'y': e['y'] + e['h'],
      'w': 3, 'h': 9, 'vy': speed,
    })
    self._play_sound(SND_HIT)

  def _make_classic_alien(self, x, y, e, fade=0.0):
    w = e['w']
    h = e['h']
    cx = int(x + w * 0.5)
    cy = int(y + h * 0.5)
    fade = 1 - fade
    dith = 4 + int((1.0 - clamp(fade, 0.0, 1.0)) * 12)
    if e['type'] == 2:
      dith = max(4, dith - 2)
    self.v.set_dither(dith)
    self.v.draw_box(cx - 6, cy - 4, 12, 8)
    self.v.draw_box(cx - 10, cy - 2, 4, 4)
    self.v.draw_box(cx + 6, cy - 2, 4, 4)
    self.v.draw_box(cx - 8, cy + 3, 5, 5)
    self.v.draw_box(cx + 3, cy + 3, 5, 5)
    self.v.draw_box(cx - 13, cy - 2, 3, 3)
    self.v.draw_box(cx + 10, cy - 2, 3, 3)
    self.v.draw_line(cx - 11, cy + 8, cx - 15, cy + 12)
    self.v.draw_line(cx + 11, cy + 8, cx + 15, cy + 12)
    if e['type'] == 2:
      self.v.set_dither(max(4, dith - 2))
      self.v.draw_box(cx - 2, cy - 1, 4, 2)
      self.v.draw_box(cx - 14, cy + 1, 2, 2)
      self.v.draw_box(cx + 12, cy + 1, 2, 2)

  def _handle_input(self):
    keys = self.v.get_tp_keys()
    left = keys[5] & 0x40
    right = keys[5] & 0x04
    shoot = keys[6] & 0x01
    quit_btn = keys[3] & 0x01
    start_btn = keys[3] & 0x02

    if self.state == "title" or self.state == 'gameover':
      if start_btn:
        self.reset_game()
      if quit_btn:
        self.quit_requested = True
        print('quit')
      self.keys_prev = keys
      return

    if quit_btn:
      self.quit_requested = True

    move = 0.0
    if left:
      move -= 1.0
    if right:
      move += 1.0
    self.player_x += move * PLAYER_SPEED * self.dt

    if shoot and not (self.keys_prev):
      self.shoot_laser()

    self.keys_prev = shoot

  def _update_background(self):
    for s in self.stars:
      s['y'] += s['v'] * self.dt
      if s['y'] > SCREEN_H:
        s['y'] = 0
        s['x'] = random.uniform(0, SCREEN_W)
    for g in self.galaxy:
      g['x'] += g['vx'] * self.dt
      g['y'] += g['vy'] * self.dt
      g['z'] += g['vz'] * self.dt
      g['rx'] += 0.8 * self.dt
      g['ry'] += 0.6 * self.dt
      g['rz'] += 0.4 * self.dt
      if g['z'] < 60:
        g['z'] = random.uniform(420, 760)
        g['x'] = random.uniform(-280, 280)
        g['y'] = random.uniform(-180, 180)
        while abs(g['x']) < 90 or abs(g['y']) < 90:
          g['x'] = random.uniform(-240, 240)
          g['y'] = random.uniform(-150, 150)

  def _update_enemies(self):
    if not self.enemies:
      return

    self.formation_phase += self.dt * ENEMY_SWAY_SPEED
    self.formation_sway = math.sin(self.formation_phase) * ENEMY_SWAY_AMOUNT
    speed = 18.0 + self.stage * 3.0
    dx = self.formation_dir * speed * self.dt

    self._recalc_enemy_bounds()
    minx, miny, maxx, maxy = self.formation_bounds
    next_minx = minx + dx
    next_maxx = maxx + dx

    hit_left = next_minx < ENEMY_EDGE_MARGIN
    hit_right = next_maxx > SCREEN_W - ENEMY_EDGE_MARGIN

    if hit_left or hit_right:
      self.formation_dir *= -1
      self.formation_drop += ENEMY_DESCEND_STEP
      self._play_sound(SND_ALIEN_DROP)

      if hit_left:
        correction = ENEMY_EDGE_MARGIN - minx
      else:
        correction = (SCREEN_W - ENEMY_EDGE_MARGIN) - maxx

      for e in self.enemies:
        e['x'] += correction
        e['base_x'] += correction
        e['y'] += ENEMY_DESCEND_STEP
        e['base_y'] += ENEMY_DESCEND_STEP
    else:
      for e in self.enemies:
        e['x'] += dx
        e['base_x'] += dx

    self.special_move_timer -= self.dt
    trigger_special = False
    if self.special_move_timer <= 0.0 and self.enemies:
      trigger_special = True
      self.special_move_timer = random.uniform(4.5, 8.0)
      self.special_move_kind = random.randint(0, 1)

    for e in self.enemies[:]:
      if e.get('alive', True):
        e['spawn_t'] = min(e.get('spawn_t', 0.0) + self.dt, 1.0)
        e['phase'] += self.dt * (2.5 + 0.4 * self.stage)
        e['fade'] = clamp(e.get('fade', 0.0) + self.dt * 2.5, 0.0, 1.0)
        if trigger_special and random.random() < 0.12:
          e['special'] = 1.0
          e['special_t'] = 0.0
        if e['special'] > 0.0:
          e['special_t'] += self.dt
          t = e['special_t']
          r = 32.0 if e['type'] == 1 else 40.0
          r = r * t if t < 2 else r * (4 - t)
          cx = e['base_x']
          cy = e['base_y']
          e['x'] = cx + math.cos(t * 3.0) * r
          e['y'] = cy + math.sin(t * 3.0) * r
          if t > 4:
            e['special'] = 0.0
            e['x'] = e['base_x']
            e['y'] = e['base_y']
        else:
          e['x'] = e['base_x']
          e['y'] = e['base_y']
      else:
        e['die_t'] += self.dt
        e['fade'] = clamp(1.0 - e['die_t'] * 4.0, 0.0, 1.0)
        e['spawn_t'] = 0.0
    self._recalc_enemy_bounds()

  def _check_enemy_player_collision(self):
    if self.invuln > 0.0:
      return
    px = self.player_x - self.player_w * 0.5
    py = self.player_y - self.player_h * 0.5
    for e in self.enemies:
      if not e.get('alive', True):
        continue
      if e['y'] + e['h'] < self.player_y:
        continue
      if rect_hit(px, py, self.player_w, self.player_h, e['x'], e['y'], e['w'], e['h']):
        self.spawn_explosion(self.player_x, self.player_y, 1)
        self._play_sound(SND_PLAYER_HIT)
        self.lives -= 1
        self.player_power = 0
        self.invuln = INVULN_TIME
        if self.lives <= 0:
          self.state = "gameover"
        return

  def _check_enemy_invasion_gameover(self):
    if not self.enemies:
      return
    for e in self.enemies:
      if not e.get('alive', True) or e['special'] != 0:
        continue
      if e['y'] + e['h'] >= self.player_y - 4:
        self.spawn_explosion(self.player_x, self.player_y, 1)
        self._play_sound(SND_PLAYER_HIT)
        return True
    return False

  def _update_items(self):
    for it in self.items[:]:
      it['t'] += self.dt
      it['x'] += it['vx'] * self.dt
      it['y'] += it['vy'] * self.dt
      it['vy'] += 8.0 * self.dt
      if it['t'] >= ITEM_TIME or it['y'] > SCREEN_H + 20:
        self.items.remove(it)
        continue
      if rect_hit(
        it['x'] - ITEM_RADIUS, it['y'] - ITEM_RADIUS, ITEM_RADIUS * 2, ITEM_RADIUS * 2,
        self.player_x - self.player_w * 0.5, self.player_y - self.player_h * 0.5, self.player_w, self.player_h
      ):
        self.items.remove(it)
        if self.player_power < PLAYER_POWER_MAX:
          self.player_power += 1
        else:
          self.score += 200
        self.player_power_anim = 1.0
        self._play_sound(SND_POWERUP)

  def _update_physics(self):
    if self.state != "play":
      return
    self.player_x = clamp(self.player_x, 16, SCREEN_W - 16)
    if self.player_cool > 0.0:
      self.player_cool -= self.dt
    if self.invuln > 0.0:
      self.invuln -= self.dt
    if self.player_power_anim > 0.0:
      self.player_power_anim = max(0.0, self.player_power_anim - self.dt * 2.5)

    for l in self.lasers[:]:
      l['y'] += l['vy'] * self.dt
      if l['y'] < -20:
        self.lasers.remove(l)

    for b in self.enemy_bullets[:]:
      b['y'] += b['vy'] * self.dt
      if b['y'] > SCREEN_H + 20:
        self.enemy_bullets.remove(b)

    self._update_enemies()

    self.enemy_fire_timer -= self.dt
    if self.enemy_fire_timer <= 0.0:
      self.enemy_fire()
      interval_scale = max(0.35, 1.0 - self.stage * 0.06)
      self.enemy_fire_timer = ENEMY_BULLET_INTERVAL * interval_scale

    for exp in self.explosions[:]:
      exp['t'] += self.dt
      if exp['t'] >= EXPLOSION_TIME:
        self.explosions.remove(exp)

    for bomb in self.bombs[:]:
      bomb['t'] += self.dt
      bomb['x'] += bomb['vx'] * self.dt
      bomb['y'] += bomb['vy'] * self.dt
      bomb['vy'] += 28.0 * self.dt
      if bomb['t'] >= 0.8:
        self.bombs.remove(bomb)

    for l in self.lasers[:]:
      lr = (l['x'], l['y'], l['w'], l['h'])
      hit = False
      for e in self.enemies[:]:
        if not e.get('alive', True):
          continue
        if rect_hit(lr[0], lr[1], lr[2], lr[3], e['x'], e['y'], e['w'], e['h']):
          self.lasers.remove(l)
          e['hp'] -= 1
          self.spawn_explosion(e['x'] + e['w'] * 0.5, e['y'] + e['h'] * 0.5, 0)
          self._play_sound(SND_EXPLOSION)
          if e['hp'] <= 0 and e.get('alive', True):
            self.score += 100 if e['type'] == 1 else 200
            e['alive'] = False
            e['die_t'] = 0.0
            e['fade'] = 1.0
            if random.random() < ITEM_DROP_CHANCE:
              self.spawn_item(e['x'] + e['w'] * 0.5, e['y'] + e['h'] * 0.5)
            self.spawn_bomb(
              e['x'] + e['w'] * 0.5, e['y'] + e['h'] * 0.5,
              size=1.0, last=(len([x for x in self.enemies if x.get('alive', True)]) == 1)
            )
            self._play_sound(SND_HIT)
          hit = True
          break
      if hit:
        continue

    if self.invuln <= 0.0:
      for b in self.enemy_bullets[:]:
        if rect_hit(
          b['x'], b['y'], b['w'], b['h'],
          self.player_x - self.player_w * 0.5, self.player_y - self.player_h * 0.5,
          self.player_w, self.player_h
        ):
          self.enemy_bullets.remove(b)
          self.spawn_explosion(self.player_x, self.player_y, 1)
          self._play_sound(SND_PLAYER_HIT)
          self.lives -= 1
          self.player_power = 0
          self.invuln = INVULN_TIME
          if self.lives <= 0:
            self.state = "gameover"
          break

    self._check_enemy_player_collision()
    invaded = self._check_enemy_invasion_gameover()
    if invaded:
      self.state = "gameover"
      return

    self._update_items()

    self.enemies = [e for e in self.enemies if e.get('alive', True) or e.get('fade', 1.0) > 0.02]
    if not [e for e in self.enemies if e.get('alive', True)] and self.state == "play":
      self._play_sound(SND_STAGE_CLEAR)
      self.stage += 1
      self._init_stage()

  def _draw_background(self):
    self.v.set_dither(16)
    self.v.set_draw_color(1)
    for s in self.stars:
      self.v.draw_pixel(int(s['x']), int(s['y']))
    self.v.set_dither(8)
    for g in self.galaxy:
      self.rot[0], self.rot[1], self.rot[2] = g['rx'], g['ry'], g['rz']
      self.pos[0], self.pos[1], self.pos[2] = g['x'], g['y'], g['z']
      self.scale[0], self.scale[1], self.scale[2] = g['s'], g['s'], g['s']
      dl.set_transform_matrix_4x4(self.matrix, self.rot, self.pos, self.scale)
      dl.project_3d_indexed(
        self.matrix, CUBE_VERTS, CUBE_INDICES, CUBE_NORMALS, self.light,
        self.num_faces, self.num_verts, 120.0, SCREEN_W * 0.5, SCREEN_H * 0.5,
        self.out_poly, self.out_dither, self.depths, self.temp_verts, self.temp_norms
      )
      indices = self.face_indices
      dl.sort_indices(indices, self.depths)
      self.v.draw_3d_faces(self.out_poly, indices, self.out_dither)

  def _draw_player(self):
    if self.invuln > 0.0 and int(self.invuln * 20) % 2 == 0:
      return
    power = self.player_power
    geom = PLAYER_POWER_GEOMS[power]
    x = self.player_x
    y = self.player_y
    scale = 10.0 + self.player_power_anim * 2.0
    if power == 3:
      scale += 1.5 * math.sin(self.player_power_anim * 12.0)
    self.rot[2] = 0.0
    self.pos2d[0], self.pos2d[1] = x - 200, y - 120
    self.scale2d[0] = scale
    self.scale2d[1] = scale
    dl.set_transform_matrix_3x3(self.matrix2d, self.rot[2], self.pos2d, self.scale2d)
    dl.project_2d_indexed(
      self.matrix2d, geom['verts'], geom['indices'], geom['colors'], 8.0,
      len(geom['indices']) // 3, len(geom['verts']) // 2, 200, 120,
      geom['out_poly'], geom['out_dither'], self.temp_verts
    )
    self.v.draw_2d_faces(geom['out_poly'], geom['face_indices'], geom['out_dither'])

  def _draw_enemies(self):
    for e in self.enemies:
      if not e.get('alive', True) and e.get('fade', 0.0) <= 0.02:
        continue
      fade = e.get('fade', 1.0)
      sx = e['x']
      sy = e['y']
      if not e.get('alive', True):
        sy = e['y'] - e.get('die_t', 0.0) * 6.0
      self._make_classic_alien(sx, sy, e, fade=fade)

  def _draw_lasers(self):
    self.v.set_dither(16)
    for l in self.lasers:
      self.v.draw_box(int(l['x']), int(l['y']), l['w'], l['h'])
    for b in self.enemy_bullets:
      self.v.set_dither(16)
      self.v.set_draw_color(0)
      self.v.draw_box(int(b['x']-2), int(b['y']-2), b['w']+4, b['h']+4)
      self.v.set_draw_color(1)
      self.v.set_dither(8)
      self.v.draw_box(int(b['x']+1), int(b['y']-6), b['w']-1, 6)
      self.v.set_dither(16)
      self.v.draw_box(int(b['x']), int(b['y']), b['w'], b['h'])

  def _draw_explosions(self):
    for exp in self.explosions:
      p = exp['t'] / EXPLOSION_TIME
      r = int(exp['s'] * (0.4 + p * 1.8))
      alpha = 16 - int(14 * p)
      if alpha < 1:
        alpha = 1
      self.v.set_dither(alpha)
      self.v.draw_circle(int(exp['x']), int(exp['y']), max(2, r), 0)
      self.v.draw_circle(int(exp['x']), int(exp['y']), max(1, r // 2), 0)
      self.v.draw_line(int(exp['x']) - r, int(exp['y']), int(exp['x']) + r, int(exp['y']))
      self.v.draw_line(int(exp['x']), int(exp['y']) - r, int(exp['x']), int(exp['y']) + r)

  def _draw_items(self):
    for it in self.items:
      scale = 7.0 + math.sin(it['t'] * 8.0) * 1.2
      geom = HEX_GEOMS
      rot = it['spin'] + it['t'] * ITEM_ROT_SPEED
      self.pos2d[0], self.pos2d[1] = it['x'] - 200, it['y'] - 120
      self.scale2d[0], self.scale2d[1] = scale, scale
      dl.set_transform_matrix_3x3(self.matrix2d, rot, self.pos2d, self.scale2d)
      dl.project_2d_indexed(
        self.matrix2d, geom['verts'], geom['indices'], geom['colors'], 8.0,
        len(geom['indices']) // 3, len(geom['verts']) // 2, 200, 120,
        geom['out_poly'], geom['out_dither'], self.temp_verts
      )
      self.v.draw_2d_faces(geom['out_poly'], geom['face_indices'], geom['out_dither'])

  def _draw_bombs(self):
    for bomb in self.bombs:
      p = clamp(bomb['t'] / 0.8, 0.0, 1.0)
      size = bomb['s'] * (0.75 + p * 1.2)
      fade = int(16 - p * 12)
      if bomb['last']:
        size *= 1.15
        fade = max(4, fade - 2)
      self.rot[0] = bomb['spin'] + p * 2.0
      self.rot[1] = bomb['spin'] * 0.7 + p * 1.4
      self.rot[2] = bomb['spin'] * 1.3
      self.pos[0], self.pos[1], self.pos[2] = bomb['x'], bomb['y'], bomb['z']
      self.scale[0] = size
      self.scale[1] = size
      self.scale[2] = size
      dl.set_transform_matrix_4x4(self.matrix2, self.rot, self.pos, self.scale)
      dl.project_3d_indexed(
        self.matrix2, SPHERE_VERTS, SPHERE_INDICES, SPHERE_NORMALS, self.light,
        len(SPHERE_INDICES) // 3, len(SPHERE_VERTS) // 3, 85.0, SCREEN_W * 0.5, SCREEN_H * 0.5,
        self.sphere_out_poly, self.sphere_out_dither, self.sphere_depths, self.sphere_temp_verts, self.sphere_temp_norms
      )
      for i in range(len(self.sphere_out_dither)):
        self.sphere_out_dither[i] = max(4, fade - (i % 4))
      dl.sort_indices(self.sphere_face_indices, self.sphere_depths)
      self.v.set_dither(max(4, fade))
      self.v.draw_3d_faces(self.sphere_out_poly, self.sphere_face_indices, self.sphere_out_dither)
      if bomb['last']:
        self.v.set_dither(4)
        self.v.draw_circle(int(bomb['x']), int(bomb['y']), int(size * 0.8), 0)
        self.v.draw_line(int(bomb['x']) - int(size), int(bomb['y']), int(bomb['x']) + int(size), int(bomb['y']))
        self.v.draw_line(int(bomb['x']), int(bomb['y']) - int(size), int(bomb['x']), int(bomb['y']) + int(size))

  def _draw_hud(self):
    self.v.set_dither(16)
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(100, 16, "SCORE:")
    self.v.draw_str(154, 16, str(self.score))
    self.v.draw_str(220, 16, "STAGE:")
    self.v.draw_str(274, 16, str(self.stage))
    self.v.draw_str(324, 16, "LIVES:")
    self.v.draw_str(378, 16, str(self.lives))

  def _draw_overlay(self):
    if self.state == "title":
      self.v.set_dither(16)
      self.v.set_font("u8g2_font_profont29_mf")
      self.v.draw_str(72, 90, "PD INVADeR")
      self.v.set_font("u8g2_font_profont15_mf")
      self.v.draw_str(74, 120, "R bottom: start   L bottom: quit")
    elif self.state == "gameover":
      self.v.set_dither(16)
      self.v.set_font("u8g2_font_profont29_mf")
      self.v.draw_str(56, 90, f"GAME OVER: {self.score}")
      self.v.set_font("u8g2_font_profont15_mf")
      self.v.draw_str(56, 120, "Right bottom btn: restart   Left bottom btn: quit")

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return
    now = time.ticks_us()
    dt_us = time.ticks_diff(now, self.last_us)
    self.last_us = now
    self.dt = dt_us / 1000000.0
    if self.dt > MAX_DT:
      self.dt = MAX_DT
    self._handle_input()
    if self.quit_requested:
      if self.bgm is not None:
        try:
          self.bgm.stop()
          self.bgm.close()
        except Exception:
          pass
      if self.sound is not None:
        try:
          self.sound.__exit__(None, None, None)
        except Exception:
          pass
      self.exited = True
      self.v.finished()
      return
    self._update_background()
    self._update_bgm()
    if self.state == "play":
      self._update_physics()
    self.v.set_draw_color(1)
    self._draw_background()
    if self.state == "play":
      self._draw_enemies()
      self._draw_explosions()
      self._draw_items()
      self._draw_bombs()
      self._draw_lasers()
      self._draw_player()
      self._draw_hud()
    else:
      self._draw_overlay()
    self.v.finished()

def main(vs, args):
  org_inv = pdeck.screen_invert()
  if org_inv:
    pdeck.screen_invert(False)

  el = elib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  game = InvaderGame(vs)
  v.callback(game.update)

  while True:
    k = v.read_nb(1)
    if game.exited:
      while True:
        k = v.read_nb(1)
        if k[0] == 0:
          break
      break
    time.sleep(0.1)

  v.callback(None)
  v.print(el.display_mode(True))
  pdeck.screen_invert(org_inv)
  print("finished.", file=vs)

