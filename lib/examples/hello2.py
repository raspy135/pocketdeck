import pdeck
import audio
import xbmreader
import esclib
import time
import pdeck_utils
import overlay
import array

def create_triangle(table_size):
  frame = array.array('h',bytearray(table_size * 2))
  for i in range(table_size):
    phase = (i / table_size) * 2 * math.pi
    val = 2 * abs(phase / math.pi - 1) - 1
    sample_val = int(val * 20000)
    frame[i] = sample_val
  return [frame]    
  

class hello_graphic():
  def __init__(self,vs, wavetable):
    self.vs = vs
    self.v = vs.v
    self.wt = wavetable
    frame = create_triangle(256)
    self.wt.set_wavetable(0,frame)
    self.wt.set_adsr(0,10,400,0.01,.1)
    self.wt.frequency(0,440)
    self.current_tick = time.ticks_us()
    
    self.ghost1 = xbmreader.read_xbmr("/sd/data/ghost1.xbmr")
    self.ghost1 = xbmreader.scale(self.ghost1,2)
    
    self.fireball = xbmreader.read_xbmr("/sd/data/fireball.xbmr")
    self.g_pos = [20, 100]
    self.g_force = [0,0]
    self.touch_ground = 0

  def play_jump(self):
    self.wt.pitch(0,1)
    self.wt.volume(0,1)
    self.wt.note_on(0)
    self.wt.pitch(0,1.5, 400)
    self.wt.note_off(0,"+0.5s")
    
  def handle_key_event(self):
    side_force = 0.04
    if self.touch_ground != 20:
      side_force = 0.01
    
    if self.v.get_key_state(0x50) == 1 and self.g_force[0] > -2 and self.touch_ground == 20:
      self.g_force[0] -= side_force
    if self.v.get_key_state(0x4f) == 1 and self.g_force[0] < 2:
      self.g_force[0] += side_force
    tpkey = self.v.get_tp_keys()
    if tpkey and tpkey[3]&0x2 != 0:
      self.v.callback(None)

    # Jump
    if self.v.get_key_state(0x28) == 1 and self.touch_ground == 20:
      self.play_jump()
      self.g_force[1] = -.4
      
      #if self.touch_ground > 12:
      #   self.g_force[1] = -2
      #else:
      #   self.g_force[1] = -4
      
      #self.g_pos[1] = 199
      self.touch_ground = 18 if self.touch_ground == 20 else self.touch_ground

  def update(self,e):
    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = (self.current_tick - self.last_tick) * 0.001

    # Display fps
    overlay.show_fps(self.v)
    
    self.handle_key_event()

    self.g_pos[0] += self.g_force[0]*self.time_diff
    self.g_pos[1] += self.g_force[1]*self.time_diff
    
    if self.g_pos[0] < 0:
      self.g_pos[0] = 0
    if self.g_pos[0] > 370:
      self.g_pos[0] = 370
      
    # Friction
    if abs(self.g_force[0]) > 0.02 and self.touch_ground == 20:
      self.g_force[0] *= 0.9
      self.g_force[0] = 0 if abs(self.g_force[0]) < 0.02 else self.g_force[0]
      
    if self.touch_ground != 20:
      self.g_force[1] += 0.015
      if self.touch_ground != 0:
         self.touch_ground -= 1
      
      
    if self.g_pos[1] >= 200:
      self.touch_ground = 20
      self.g_pos[1] = 200
      self.g_force[1] = 0

    # Display title and graphic
    self.v.set_font("u8g2_font_profont29_mf")
    self.v.draw_str(10,30, "Hello graphic app")
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(10,55, "Touch bottom-right button to quit")
    self.v.draw_image(int(self.g_pos[0]),int(self.g_pos[1]),self.ghost1)

    self.v.draw_image(100,100,self.fireball,0)

    #self.ghost_x += 1
    
    # Once you finished update, you need to notify the frame update is finished.
    self.v.finished()
    
    
def main(vs, args):
  audio.sample_rate(24000)
  el = esclib.esclib()
  # Obtain vsceen object
  v = vs.v

  # Erasing screen and cursor
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  with audio.wavetable(4) as wavetable:
    obj = hello_graphic(vs, wavetable)

    # Register callback for graphic update
    # System will call update() for every frame update
    v.callback(obj.update)

    while v.callback_exists():
      time.sleep(0.5)

    # Unregister callback and recover the cursor
    v.callback(None)
    v.print(el.display_mode(True))
  

