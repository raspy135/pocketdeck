import esclib as elib
import time
import pdeck
import random
import array
import pdeck_utils as pu

import mouse

class input_test:
  def __init__(self,vs):
    self.vs = vs
    self.v = vs.v
    self.mouse = mouse.mouse(self.v)
    self.point = array.array('i',bytearray(12))
    self.point[0] = 100
    self.point[1] = 100
    self.point[2] = 0
    self.t_timer = 0
    self.arc_length = 0
    
  def draw_mouse(self,x,y):
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(250,235,"Press Q to quit")
    self.mouse.update()
    self.point = self.mouse.get_point()
    self.v.draw_box(self.point[0],self.point[1],3,3)
    if self.point[2]&1 != 0:
      self.t_timer = 10
    if self.t_timer > 0:
      self.v.draw_str(190, 30, "Tap!")
      self.t_timer -= 1
    else:
      if x != 0xff:
        self.v.draw_str(190,30,f"({x},{y})")
      

  def draw_key(self, stat,x,y, size=30):
    if stat:
      self.v.draw_box(x,y,size,size)
    else:
      self.v.draw_frame(x,y,size,size)

  def draw_dial(self, angle_in):
    angle = angle_in
    if angle != 0xff:
      self.arc_length = self.arc_length+1 if self.arc_length < 20 else self.arc_length
      angle = -int(angle*1.6)+64
      for r in range(27,30):
        self.v.draw_arc(65,150, r,angle-self.arc_length,angle+self.arc_length)
      self.v.set_font("u8g2_font_profont15_mf")
      self.v.draw_str(55, 155,f"{angle_in}")
    else:
      self.arc_length=0    
  
  def draw_slider(self, position):
    if position != 0xff:
      self.v.draw_str(200,60,f"{position}")
    self.v.draw_frame(190,70,10,80)
    y_offset = int((position) * (3/2))
    self.v.draw_box(180,70+y_offset, 40,10)
    
    
  def update(self,e):
    if not self.v.active:
      self.v.finished()
      return
    keys = self.v.get_tp_keys()
    #print(keys)
    self.draw_key(keys[5]&0x1 == 1, 50,20)
    self.draw_key(keys[5]&0x4 != 0, 80,50)
    self.draw_key(keys[5]&0x10 != 0, 50,80)
    self.draw_key(keys[5]&0x40 != 0, 20,50)
    self.draw_key(keys[6]&0x1 != 0, 120,70,15)
    self.draw_key(keys[6]&0x2 != 0, 100,90,15)
    self.draw_key(keys[3]&0x1 != 0, 140,20,15)
    self.draw_key(keys[3]&0x2 != 0, 160,20,15)
    
    self.draw_mouse(keys[2],keys[1])
    self.draw_slider(keys[0])
    self.draw_dial(keys[4])  
    
    self.v.finished()

  def keyevent_loop(self):
    while True:
      keys = self.vs.read(1, 400)

      keys = keys.encode('ascii')

      if keys == b'q':
        print('quit')
        break
      

def main(vs, args):
  v = vs.v
  el = elib.esclib()  
  obj = input_test(vs)
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  v.callback(obj.update)
  obj.keyevent_loop()
  v.callback(None)
  v.print(el.display_mode(True))
  print("finished.", file=vs)

