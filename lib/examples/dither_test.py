import esclib as elib
import time
import pdeck
import random
import re_test
import array
import xbmreader
import pdeck_utils as pu
import dsplib as dl
import gc

pu.reimport("dsp_utils")
import dsp_utils as du


class Box:
  def __init__(self):
    self.x = -45
    self.y = -45
    self.w = random.randint(10,60)
    self.h = random.randint(10,60)
    self.r = 0
    self.off_x = random.randint(40,380)
    self.off_y = random.randint(40,220)
    self.dither = random.randint(1,16)
    self.rspeed = random.randint(-300,300) / 20000.0
    self.points = array.array('h', bytearray(2*8))

class utest():
  
  def __init__(self,v):
    self.boxes = []
    self.v = v
    self.ct = 0
    self.last_us = 0
    self.A = array.array('f', bytearray(4*4))
    self.Ah = array.array('h', bytearray(2*4))
    self.Ch = array.array('h', bytearray(2*8))
    du.gen_fp_sin(6)
    for i in range(20):
      self.boxes.append(Box())

  def rotate_pos(self, points, npoints, angle):
    #A = array.array('f', ( du.cos(angle), -du.sin(angle), du.sin(angle), +du.cos(angle) ) )
    self.A[0] = du.cos(angle)
    self.A[1] = -du.sin(angle)
    self.A[2] = du.sin(angle)
    self.A[3] = +du.cos(angle)
    r =  dl.matrix_mul_f32(self.A,points,2,2,npoints)
    return r
    
  def rotate_pos_s16(self, points, npoints, angle):
    #return points
    self.Ah[0] = du.fp_cos(angle)
    self.Ah[1] = -du.fp_sin(angle)
    self.Ah[2] = du.fp_sin(angle)
    self.Ah[3] = +du.fp_cos(angle)
    
    dl.matrix_mul_s16(self.Ah,points,2,2,npoints,15-6, self.Ch)
    memoryview(points)[:] = memoryview(self.Ch)[:]
    return

  def rotate(self, points, angle):
    num_p = len(points) >> 1
    self.rotate_pos_s16(points, num_p, angle)
      
  @micropython.native
  def update(self,e):
    if not self.v.active:
      self.v.finished()
      return
    current = time.ticks_us()
    diff = current - self.last_us
    self.last_us = current
    fps = 1000000 // diff
    self.v.set_dither(16)
    self.v.set_draw_color(1)
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(400-50,10,str(fps)+" FPS")
    
    self.v.set_draw_color(1)
    #self.v.draw_box(0,0,420,240)
    #self.v.set_draw_color(0)
    #self.ct += 1
    #self.v.set_bitmap_mode(0)
    for box in self.boxes:

      self.v.set_dither(box.dither)
      
      #box.x += random.randint(-2,2)
      #box.y += random.randint(-2,2)

      #box.points = array.array('h', ( box.x, box.x+box.w, box.x+box.w, box.x, box.y, box.y, box.y+box.h, box.y+box.h ))
      box.points[0] = box.x
      box.points[1] = box.x+box.w
      box.points[2] = box.x+box.w
      box.points[3] = box.x
      box.points[4] = box.y
      box.points[5] = box.y
      box.points[6] = box.y+box.h
      box.points[7] = box.y+box.h

      
      box.r += box.rspeed
      if box.r > 2*du.pi:
        box.r -= 2*du.pi
      if box.r < -2*du.pi:
        box.r += 2*du.pi
      self.rotate(box.points, box.r)
      #d_points = array.array('h')
      npoints = len(box.points) >> 1
      for i in range(npoints):
        box.points[i] += box.off_x
        box.points[npoints + i] += box.off_y
    
      self.v.draw_polygon(box.points)
    self.v.finished()

def main(vs, args):
  v = vs.v
  el = elib.esclib()  
  obj = utest(v)
  #v.unsubscribe_callback()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  v.callback(obj.update)
  #v.finished()
  #while v.callback_exists():
  #  time.sleep_ms(500)

