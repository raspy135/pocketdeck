import array
import pdeck

class mouse:
  def __init__(self,v):
    self.v = v
    self.touchbase = array.array('i',bytearray(8))
    self.mousebase = array.array('i',bytearray(8))
    self.lastpoint = array.array('i',bytearray(8))
    self.point = array.array('i',bytearray(8))
    self.point[0] = 100
    self.point[1] = 100
    self.mousebase[0] = self.point[0]
    self.mousebase[1] = self.point[1]
    self.timer = 0
    self.tap = 0
    self.touched = False
    self.rbutton = 0
    self.lbutton = 0
    self.rclick = 0
    self.lclick = 0
    self.last_button = 0
    self.limit_low = [0,0]
    self.limit_high = list(pdeck.get_screen_size())
    
  def update(self):
    keys = self.v.get_tp_keys()
    if not keys:
      return
    x = keys[2]
    y = keys[1]
    self.lbutton = 1 if keys[3]&1 else 0
    self.rbutton = 1 if keys[3]&2 else 0
    if not self.last_button&1 and keys[3]&1:
      self.lclick = 1
    if not self.last_button&2 and keys[3]&2:
      self.rclick = 1
    
    self.last_button = keys[3]
    
    touching = not (x == 255 or y == 255)
    
    self.active = touching or self.lbutton ==1 or self.rbutton == 1 or self.lclick == 1 or self.rclick == 1
    
    if not touching:
      if self.touched and self.timer < 8 and abs(self.mousebase[0] - self.point[0] < 10) and abs(self.mousebase[1] - self.point[1]) < 10:
        self.tap = 1
        self.point[0] = self.mousebase[0]
        self.point[1] = self.mousebase[1]
      self.touched = False
      return
    if touching:
      if not self.touched:
        self.lastpoint[0] = x
        self.lastpoint[1] = y
        self.touchbase[0] = x
        self.touchbase[1] = y
        self.mousebase[0] = self.point[0]
        self.mousebase[1] = self.point[1]
        self.timer = 0
        self.touched = True
        
      self.timer += 1
      
      diff_x = x - self.lastpoint[0]
      diff_y = y - self.lastpoint[1]
      speed = abs(diff_x) + abs(diff_y)
      if speed > 2:
        accel = 256 + (speed - 2) * 25
        if accel > 768:
          accel = 768
        diff_x = (diff_x * accel) // 256
        diff_y = (diff_y * accel) // 256

      if abs(self.touchbase[0] - x) < 20 and abs(self.touchbase[1] - y) < 20 and self.timer < 10:
        diff_x = 0
        diff_y = 0

      self.point[0] += diff_x
      self.point[1] += diff_y


      if self.point[0] >= self.limit_high[0]:
        self.point[0] =  self.limit_high[0]-1
      if self.point[1] >= self.limit_high[1]:
        self.point[1] = self.limit_high[1]-1
      
      self.point[0] = self.limit_low[0] if self.point[0] < self.limit_low[0] else self.point[0]
      self.point[1] = self.limit_low[1] if self.point[1] < self.limit_low[1] else self.point[1]
      self.lastpoint[0] = x
      self.lastpoint[1] = y
    
  #@micropython.native
  # Get the points of the mouse.
  # Return is (x, y, buttons)
  # button indicates:
  #   Bit 0: tap
  #   Bit 1: Left button
  #   Bit 2: Right button
  def get_point(self):
    ret = [0]*3
    ret[0] = self.point[0] 
    ret[1] = self.point[1]
    ret[2] = self.tap | (self.lclick << 1) | (self.rclick << 2) | (self.lbutton << 3) | (self.rbutton << 4)
    self.rclick = 0
    self.lclick = 0
    if self.tap:
      self.tap = 0
    return ret
    
  def set_limit(self, low, high):
    self.limit_low = low
    self.limit_high = high
    
  def draw_mouse_cursor(self):
    self.v.set_draw_color(0)
    self.v.draw_disc(self.point[0],self.point[1],8,0xf)
    self.v.set_draw_color(1)
    self.v.draw_circle(self.point[0],self.point[1],8,0xf)
    self.v.draw_circle(self.point[0],self.point[1],7,0xf)


   
