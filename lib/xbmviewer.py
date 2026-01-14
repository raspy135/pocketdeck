import time
import pdeck
#import xbmreader
import esclib as elib
import pdeck_utils as pu

pu.reimport('xbmreader')
class drawxbm():
  def __init__(self,vs, filename):
    self.vs = vs
    self.image = xbmreader.read(filename)
    self.v = vs.v

  def update(self,e):
    self.v.draw_box(0,0,420, 240)
    self.v.draw_xbm(0,0,self.image[1],self.image[2], self.image[3])
    self.v.finished()

  
def main(vs, args):
  obj = drawxbm(vs, args[1])
  el = elib.esclib()

  obj.v.print(el.erase_screen())
  vs.v.print(el.display_mode(False))
  obj.v.callback(obj.update)
  # Foreground app
  while True:
    time.sleep(1)
    ret = obj.v.read_nb(10)
    if ret:
      if ret[0] > 0:
        obj.v.print("Quit\n")
        obj.v.callback(None)
        break

  vs.v.print(el.display_mode(True))

