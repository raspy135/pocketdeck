import dsplib as dl
import esclib as elib
import xbmreader
import math
from array import array

class TexturedPolyDemo:
  def __init__(self, vscreen):
    self.v = vscreen
    self.angle = 0.0
    self.data = xbmreader.read_xbmr("/sd/lib/data/ghost1.xbmr")
    self.tw, self.th = self.data[1], self.data[2]
    # Pre-allocate buffers for performance
    self.pts = array('h', [0] * 8)
    self.maps = array('h', [0, self.tw, self.tw, 0,  0, 0, self.th, self.th])
    
  def update(self, e):

    v = self.v
    v.set_draw_color(1)
    size = 20
    
    for i in range(10):
      angle = self.angle + i * 0.5
      cx = 40 + i * 35
      cy = 120 + math.sin(self.angle + i) * 50
      scale = 1.0 + math.sin(self.angle * 2 + i) * 0.5
      
      s, c = math.sin(angle), math.cos(angle)
      
      def rot(px, py):
        px, py = px * scale, py * scale
        rx = px * c - py * s
        ry = px * s + py * c
        return int(rx + cx), int(ry + cy)
      
      # Fill pre-allocated pts buffer
      x0, y0 = rot(-size, -size)
      x1, y1 = rot(size, -size)
      x2, y2 = rot(size, size)  
      x3, y3 = rot(size, size) 
      x3, y3 = rot(-size, size)
      
      self.pts[0], self.pts[1], self.pts[2], self.pts[3] = x0, x1, x2, x3
      self.pts[4], self.pts[5], self.pts[6], self.pts[7] = y0, y1, y2, y3
      
      v.draw_polygon_texture(self.pts, self.maps, self.data)
    
    v.set_font("u8g2_font_profont15_mf")
    v.draw_str(5, 15, "TEXTURED POLYGON LOOP TEST")
    
    v.finished()
    self.angle += 0.05

def main(vs, args):
  el = elib.esclib()
  v = vs.v
  
  # Switch to graphics mode
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  # Start callback loop
  v.callback(TexturedPolyDemo(v).update)
  
  # Wait for input to exit
  vs.read(1)
  
  # Cleanup
  v.callback(None)
  v.print(el.display_mode(True))
