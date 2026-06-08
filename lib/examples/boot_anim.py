# Boot splash animation.
#
# Dots crawl vertex-to-vertex along the edges of an isometric cube (no wireframe
# is drawn), moving like small living creatures, with smooth ease-in-out motion
# and simple collision avoidance (no two dots share a vertex).
#
# On the real device the boot splash runs in C (see the boot_anim code in
# components/display/displayapi.c) because MicroPython is saturated during boot
# and has no room to draw it. This Python version mirrors that algorithm so the
# web emulator can show the same splash, and serves as a readable reference.
# Keep the cube constants and dot count identical to the C version.

import time
import random
import anm

# Unit-cube vertices and the 3 neighbours of each (vertices differing in exactly
# one axis). Identical to boot_cube_pos / boot_cube_nbr in the C implementation.
CUBE_POS = (
  (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
  (-1, -1, 1),  (1, -1, 1),  (1, 1, 1),  (-1, 1, 1),
)
CUBE_NBR = (
  (1, 3, 4), (0, 2, 5), (1, 3, 6), (0, 2, 7),
  (0, 5, 7), (1, 4, 6), (2, 5, 7), (3, 4, 6),
)
N_DOTS = 5
DOT_RADIUS = 6


def _project():
  # Top-right 45 deg iso view centered at 200,120; vertical cube edges stay
  # vertical on screen. Matches the projection in display_boot_anim_start().
  vx = []
  vy = []
  for (x, y, z) in CUBE_POS:
    vx.append(200 + (x - z) * 55)
    vy.append(120 + (x + z) * 26 - y * 52)
  return vx, vy


class _Dot:
  def __init__(self, v):
    self.cur = v       # vertex the dot sits at / departed from
    self.tgt = v       # vertex it is heading to (== cur when resting)
    self.moving = False
    self.t = 0.0       # edge progress 0..1
    self.speed = random.uniform(0.6, 1.1)
    self.dwell = random.uniform(0.0, 300.0)


class BootAnim:
  def __init__(self, v):
    self.v = v
    self.vx, self.vy = _project()
    used = set()
    self.dots = []
    while len(self.dots) < N_DOTS:
      vtx = random.getrandbits(3)
      if vtx in used:
        continue
      used.add(vtx)
      self.dots.append(_Dot(vtx))
    self.last = time.ticks_ms()

  def _taken(self, vtx, skip):
    # Is vertex occupied or reserved by any dot other than `skip`?
    for i, d in enumerate(self.dots):
      if i == skip:
        continue
      if d.cur == vtx:
        return True
      if d.moving and d.tgt == vtx:
        return True
    return False

  def _step(self, now):
    dt = time.ticks_diff(now, self.last) / 1000.0
    self.last = now
    if dt < 0.0:
      dt = 0.0
    if dt > 0.05:
      dt = 0.05  # clamp after long stalls so dots don't jump
    dt_ms = dt * 1000.0
    for i, d in enumerate(self.dots):
      if d.moving:
        d.t += dt * d.speed
        if d.t >= 1.0:
          d.t = 0.0
          d.cur = d.tgt
          d.moving = False
          d.dwell = random.uniform(80.0, 400.0)
        continue
      # Resting: wait out the dwell, then leave for a free neighbour.
      if d.dwell > 0.0:
        d.dwell -= dt_ms
        continue
      cand = [n for n in CUBE_NBR[d.cur] if not self._taken(n, i)]
      if not cand:
        continue  # all neighbours busy: wait for one to free up
      d.tgt = cand[random.getrandbits(8) % len(cand)]
      d.moving = True
      d.t = 0.0
      d.speed = random.uniform(0.6, 1.1)

  def update(self, e):
    v = self.v
    self._step(time.ticks_ms())
    v.set_draw_color(0)
    v.draw_box(0, 0, 400, 240)
    v.set_draw_color(1)
    for d in self.dots:
      if d.moving:
        ec = anm.ease_in_out(d.t)
        x = self.vx[d.cur] + (self.vx[d.tgt] - self.vx[d.cur]) * ec
        y = self.vy[d.cur] + (self.vy[d.tgt] - self.vy[d.cur]) * ec
      else:
        x = self.vx[d.cur]
        y = self.vy[d.cur]
      v.draw_disc(int(x), int(y), DOT_RADIUS)
    v.finished()


def main(vs, args):
  v = vs.v
  anim = BootAnim(v)
  v.callback(anim.update)
  # Run until a key is pressed (or the screen is detached). Reads pump frames.
  while v.callback_exists():
    ch = vs.read(1)
    if ch:
      break
