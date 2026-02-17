import pdeck
import xbmreader
import esclib
import time
import pdeck_utils
import overlay

class hello_graphic():
  def __init__(self,vs):
    self.vs = vs
    self.v = vs.v
    
    self.ghost1 = xbmreader.read("/sd/data/ghost1.xbm")
    self.ghost1 = xbmreader.scale(self.ghost1,2)
    self.ghost_x = 20

  def update(self,e):
    
    # Display fps
    overlay.show_fps(self.v)
    
    # Display title and graphic
    self.v.set_font("u8g2_font_profont29_mf")
    self.v.draw_str(10,30, "Hello graphic app")
    self.v.draw_xbm(self.ghost_x, 100,
      self.ghost1[1],self.ghost1[2], 
      self.ghost1[3])
    
    self.ghost_x += 1
    # Once you finished update, you need to notify the frame update is finished.
    self.v.finished()
    
    
def main(vs, args):
  el = esclib.esclib()
  # Obtain vsceen object
  v = vs.v

  # Erasing screen and cursor
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  obj = hello_graphic(vs)

  # Register callback for graphic update
  # System will call update() for every frame update
  v.callback(obj.update)

  # Wait for keyboard input for 1 byte, polling rate is 50ms
  vs.read(1, 50)

  # Unregister callback and recover the cursor
  v.callback(None)
  v.print(el.display_mode(True))
  

