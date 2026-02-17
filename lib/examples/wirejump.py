import pdeck
import xbmreader
import esclib
import time
import overlay
import array
import math
import random

GAME_NAME = "WireJump"

def create_triangle(table_size):
  frame = array.array('h', bytearray(table_size * 2))
  for i in range(table_size):
    phase = (i / table_size) * 2 * math.pi
    val = 2 * abs(phase / math.pi - 1) - 1
    frame[i] = int(val * 20000)
  return [frame]


def draw_line_clamped(v, x0, y0, x1, y1, max_x, max_y):
  if x0 < 0: x0 = 0
  if y0 < 0: y0 = 0
  if x1 < 0: x1 = 0
  if y1 < 0: y1 = 0
  if x0 > max_x: x0 = max_x
  if y0 > max_y: y0 = max_y
  if x1 > max_x: x1 = max_x
  if y1 > max_y: y1 = max_y
  v.draw_line(int(x0), int(y0), int(x1), int(y1))


def draw_wire_box(v, x0, y0, w, h, t, phase, max_x, max_y):
  if t <= 0:
    return
  x0 = int(x0)
  y0 = int(y0)
  w = int(w)
  h = int(h)
  if w <= 0 or h <= 0:
    return
  x1 = x0 + w
  y1 = y0 + h
  if t >= 1.0:
    draw_line_clamped(v, x0, y0, x1, y0, max_x, max_y)
    draw_line_clamped(v, x1, y0, x1, y1, max_x, max_y)
    draw_line_clamped(v, x1, y1, x0, y1, max_x, max_y)
    draw_line_clamped(v, x0, y1, x0, y0, max_x, max_y)
    return

  # Center-out frame growth to avoid long single-edge lines.
  cx = x0 + (w // 2)
  cy = y0 + (h // 2)
  hw = int((w * 0.5) * t)
  hh = int((h * 0.5) * t)
  if hw < 1 and hh < 1:
    return

  left = cx - hw
  right = cx + hw
  top = cy - hh
  bottom = cy + hh

  draw_line_clamped(v, left, top, right, top, max_x, max_y)
  draw_line_clamped(v, left, bottom, right, bottom, max_x, max_y)
  draw_line_clamped(v, left, top, left, bottom, max_x, max_y)
  draw_line_clamped(v, right, top, right, bottom, max_x, max_y)


class Obstacle:
  def __init__(self, x, y, w, h):
    self.x = x
    self.y = y
    self.w = w
    self.h = h
    self.points = array.array('h', bytearray(2 * 8))
    self.build = 0.0
    self.is_ground = False
    self.animated = False
    self.falling = False
    self.fall_v = 0.0
    self.stay = False

  def update_points(self, screen_y):
    x0 = self.x
    x1 = self.x + self.w
    y0 = screen_y
    y1 = screen_y + self.h
    pts = self.points
    pts[0] = x0
    pts[1] = x1
    pts[2] = x1
    pts[3] = x0
    pts[4] = y0
    pts[5] = y0
    pts[6] = y1
    pts[7] = y1
    return pts


class WireJumpGame:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.isExit = False

    self.ghost1 = xbmreader.read("/sd/data/ghost1.xbm")
    self.ghost1 = xbmreader.scale(self.ghost1, 2)
    self.player_w = self.ghost1[1]
    self.player_h = self.ghost1[2]
    self.screen_w = 400
    self.screen_h = 240
    self.ground_y = 200
    self.player_x = 60
    self.player_y = 140
    self.vel_x = 0.0
    self.vel_y = 0.0
    self.on_ground = True
    self.current_platform = None
    self.scroll_y = 0.0
    self.scroll_speed = 80.0
    self.gravity = 700.0
    self.last_ms = time.ticks_ms()

    self.lane_w = 100
    self.lanes = [20, 150, 280]
    self.prev_lane_idx = 1
    self.lane_jitter = 18
    self.next_spawn_y = -40
    self.obstacles = []
    self.safe_time_ms = 2000
    self.spawn_min_gap = 50
    self.spawn_max_gap = 80
    self.scroll_speed_min = 45.0
    self.scroll_speed = self.scroll_speed_min
    self.spawn_easy_count = 14
    self.spawn_lead = 60
    self.jump_speed = -420.0
    self.gravity = 1050.0
    self.coyote_time_ms = 120
    self.coyote_timer_ms = 0
    self.max_speed_ground = 220.0
    self.max_speed_air = 140.0
    self.anim_phase = 0.0
    self.spawn_counter = 0
    self.safe_every = 6
    self.bg_scroll = 0.0
    self.bg_margin = 80
    self.bg_boxes = []
    self.init_background()

    ground = Obstacle(0, self.ground_y, self.screen_w, 24)
    ground.is_ground = True
    ground.build = 1.0
    ground.falling = False
    ground.fall_v = 0.0
    self.obstacles.append(ground)
    self.next_spawn_y = 140
    self.player_y = self.ground_y - self.player_h
    self.on_ground = True
    self.current_platform = ground
    for _ in range(32):
      self._spawn_obstacle()

  def _spawn_obstacle(self):
    self.spawn_counter += 1
    force_safe = (self.spawn_counter % self.safe_every) == 0
    if len(self.obstacles) <= self.spawn_easy_count:
      lane_x = self.lanes[self.prev_lane_idx] + random.randint(-self.lane_jitter, self.lane_jitter)
      w = self.lane_w + 60
      h = 16
      gap = self.spawn_max_gap
    else:
      if force_safe:
        lane_idx = 1
        w = self.lane_w + 70
        h = 16
        gap = self.spawn_max_gap
      else:
        if random.random() < 0.6:
          lane_idx = 1
        else:
          step = random.choice([-1, 0, 1])
          lane_idx = self.prev_lane_idx + step
          if lane_idx < 0:
            lane_idx = 0
          if lane_idx > 2:
            lane_idx = 2
        w = self.lane_w + 10
        h = random.randint(16, 28)
        gap = random.randint(self.spawn_min_gap, self.spawn_max_gap)
      lane_x = self.lanes[lane_idx] + random.randint(-self.lane_jitter, self.lane_jitter)
      self.prev_lane_idx = lane_idx
    obs = Obstacle(lane_x, self.next_spawn_y, w, h)
    obs.build = 0.0
    obs.animated = False
    obs.falling = False
    obs.fall_v = 0.0
    obs.stay = force_safe
    self.obstacles.append(obs)
    self.next_spawn_y -= gap

  def _reset_game(self):
    self.player_x = 60
    self.player_y = self.ground_y - self.player_h
    self.vel_x = 0.0
    self.vel_y = 0.0
    self.on_ground = True
    self.current_platform = None
    self.scroll_y = 0.0
    self.next_spawn_y = -40
    self.obstacles = []
    self.safe_time_ms = 2000
    self.scroll_speed = self.scroll_speed_min
    self.spawn_min_gap = 50
    self.spawn_max_gap = 80
    self.spawn_easy_count = 14
    self.spawn_counter = 0
    self.prev_lane_idx = 1
    self.coyote_timer_ms = 0
    ground = Obstacle(0, self.ground_y, self.screen_w, 24)
    ground.is_ground = True
    ground.build = 1.0
    ground.falling = False
    ground.fall_v = 0.0
    self.obstacles.append(ground)
    self.next_spawn_y = 140
    self.player_y = self.ground_y - self.player_h
    self.on_ground = True
    self.current_platform = ground
    for _ in range(32):
      self._spawn_obstacle()

  def handle_key_event(self, dt_ms):
    dt = dt_ms / 1000.0
    side_accel = 3200.0
    air_accel = 1800.0
    max_speed = self.max_speed_ground if self.on_ground else self.max_speed_air
    if self.v.get_key_state(0x50) == 1:
      self.vel_x -= (side_accel if self.on_ground else air_accel) * dt
    if self.v.get_key_state(0x4f) == 1:
      self.vel_x += (side_accel if self.on_ground else air_accel) * dt
    if self.vel_x > max_speed:
      self.vel_x = max_speed
    elif self.vel_x < -max_speed:
      self.vel_x = -max_speed
    tpkey = self.v.get_tp_keys()
    if tpkey and tpkey[3] & 0x2 != 0:
      self.isExit = True

    if self.v.get_key_state(0x28) == 1 and self.on_ground:
      self.vel_y = self.jump_speed
      self.on_ground = False
      self.coyote_timer_ms = 0
      if self.current_platform and not self.current_platform.is_ground and not self.current_platform.stay:
        self.current_platform.falling = True

  def update(self, e):
    overlay.show_fps(self.v)
    now = time.ticks_ms()
    dt_ms = time.ticks_diff(now, self.last_ms)
    if dt_ms < 0:
      dt_ms = 0
    self.last_ms = now
    dt = dt_ms / 1000.0
    self.handle_key_event(dt_ms)

    if self.safe_time_ms > 0:
      self.safe_time_ms -= dt_ms
      if self.safe_time_ms < 0:
        self.safe_time_ms = 0
      t = 1.0 - (self.safe_time_ms / 2000.0)
      self.scroll_speed = self.scroll_speed_min + (80.0 - self.scroll_speed_min) * t

    self.draw_background(dt)

    self.anim_phase += dt * 1.2
    was_on_ground = self.on_ground
    self.scroll_y += self.scroll_speed * dt
    if was_on_ground:
      self.player_y += self.scroll_speed * dt
    self.vel_y += self.gravity * dt
    self.player_x += self.vel_x * dt
    self.player_y += self.vel_y * dt

    for obs in self.obstacles:
      if obs.falling and not obs.is_ground:
        obs.fall_v += 1200.0 * dt
        obs.y += obs.fall_v * dt

    if self.player_x < 0:
      self.player_x = 0
      self.vel_x = 0.0
    if self.player_x > self.screen_w - self.player_w:
      self.player_x = self.screen_w - self.player_w
      self.vel_x = 0.0

    if self.on_ground:
      self.vel_x *= 0.85
      if abs(self.vel_x) < 10:
        self.vel_x = 0.0

    px0 = self.player_x
    px1 = self.player_x + self.player_w

    # Landing on platforms (top-only collision while falling or sticking)
    self.on_ground = False
    feet = self.player_y + self.player_h
    best_top = None
    best_top_obs = None
    if self.vel_y >= 0 or was_on_ground:
      for obs in self.obstacles:
        oy = obs.y + self.scroll_y
        if oy < -40 or oy > self.screen_h + 40:
          continue
        ox0 = obs.x
        ox1 = obs.x + obs.w
        top = oy
        if px1 > ox0 and px0 < ox1:
          if feet >= top - 6 and feet <= top + 18:
            if best_top is None or top > best_top:
              best_top = top
              best_top_obs = obs
    if best_top is not None:
      self.player_y = best_top - self.player_h
      self.vel_y = 0.0
      self.on_ground = True
      self.coyote_timer_ms = self.coyote_time_ms
      self.current_platform = best_top_obs
    elif self.coyote_timer_ms > 0:
      self.coyote_timer_ms -= dt_ms
      if self.coyote_timer_ms > 0:
        self.on_ground = True
        # Keep current_platform as-is during coyote time
    if not self.on_ground and self.coyote_timer_ms <= 0:
      self.current_platform = None

    for obs in self.obstacles:
      oy = obs.y + self.scroll_y
      if oy > self.screen_h + 40:
        if obs.is_ground:
          continue
        spawn_floor = self.scroll_y - 400
        if self.next_spawn_y < spawn_floor:
          self.next_spawn_y = spawn_floor
        obs.y = self.next_spawn_y - self.scroll_y
        self.spawn_counter += 1
        force_safe = (self.spawn_counter % self.safe_every) == 0
        if force_safe:
          lane_idx = 1
          obs.w = self.lane_w + 70
          obs.h = 16
        else:
          if random.random() < 0.6:
            lane_idx = 1
          else:
            step = random.choice([-1, 0, 1])
            lane_idx = self.prev_lane_idx + step
            if lane_idx < 0:
              lane_idx = 0
            if lane_idx > 2:
              lane_idx = 2
          obs.w = self.lane_w + 10
          obs.h = random.randint(16, 28)
        obs.x = self.lanes[lane_idx] + random.randint(-self.lane_jitter, self.lane_jitter)
        obs.falling = False
        obs.fall_v = 0.0
        obs.build = 0.0
        obs.animated = False
        obs.stay = force_safe
        self.prev_lane_idx = lane_idx
        self.next_spawn_y -= random.randint(self.spawn_min_gap, self.spawn_max_gap)
        continue
      if oy + obs.h < -40:
        continue
      ox0 = obs.x
      ox1 = obs.x + obs.w
      oy0 = oy
      oy1 = oy + obs.h
      # Side or bottom collisions are allowed (no death).

    # Death if fall below screen
    if self.safe_time_ms == 0 and self.player_y > self.screen_h + 20:
      self._reset_game()

    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(10, 18, GAME_NAME)
    self.v.draw_str(10, 36, "Touch bottom-right to quit")

    for obs in self.obstacles:
      oy = obs.y + self.scroll_y
      visible = not (oy < -40 or oy > self.screen_h + 40)
      if not visible:
        continue
      if not obs.animated:
        obs.build += dt * 1.0
        if obs.build >= 1.0:
          obs.build = 1.0
          obs.animated = True
      draw_wire_box(self.v, obs.x, int(oy), obs.w, obs.h, obs.build, self.anim_phase + obs.y * 0.02, self.screen_w - 1, self.screen_h - 1)

    self.v.set_bitmap_mode(1)
    self.v.draw_xbm(int(self.player_x), int(self.player_y),
      self.ghost1[1], self.ghost1[2], self.ghost1[3])

    self.v.set_draw_color(1)
    self.v.draw_line(0, 0, self.screen_w - 1, 0)
    self.v.draw_line(self.screen_w - 1, 0, self.screen_w - 1, self.screen_h - 1)
    self.v.draw_line(self.screen_w - 1, self.screen_h - 1, 0, self.screen_h - 1)
    self.v.draw_line(0, self.screen_h - 1, 0, 0)

    self.v.finished()

  def init_background(self):
    for _ in range(18):
      w = random.randint(30, 80)
      h = random.randint(18, 50)
      x = random.randint(0, self.screen_w - w)
      y = random.randint(-self.screen_h, self.screen_h)
      d = random.randint(3, 10)
      self.bg_boxes.append([x, y, w, h, d])

  def draw_background(self, dt):
    self.bg_scroll += self.scroll_speed * 0.35 * dt
    span = self.screen_h + (self.bg_margin * 2)
    self.v.switch_buffer(1)
    self.v.clear_buffer()
    for b in self.bg_boxes:
      y = (b[1] + self.bg_scroll) % span - self.bg_margin
      self.v.set_dither(b[4])
      self.v.set_draw_color(1)
      self.v.draw_box(int(b[0]), int(y), int(b[2]), int(b[3]))
    self.v.copy_buffer(0, 1)
    self.v.switch_buffer(0)
    self.v.set_dither(16)


def main(vs, args):
  el = esclib.esclib()
  v = vs.v

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  obj = WireJumpGame(vs)
  v.callback(obj.update)

  while not obj.isExit:
    time.sleep(0.5)

  v.callback(None)
  v.print(el.display_mode(True))
