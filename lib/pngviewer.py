import time
import pdeck
import esclib as elib
import pdeck_utils as pu
import imagelib

import pngreader

class drawpng():
  
  def __init__(self, vs, filename):
    self.vs = vs
    self.v = vs.v
    self.image = pngreader.read(filename)
    print(f"image {self.image[1]},{self.image[2]}")

  def update(self, e):
    self.v.draw_box(0, 0, 400, 240)
    self.v.draw_xbm(
      200 - self.image[1] // 2 ,
      120 - self.image[2] // 2,
      self.image[1], self.image[2], self.image[3])
    
    self.v.finished()


def main(vs, args):
  if len(args) < 2:
    vs.v.print("Usage: pngviewer <file.png>\n")
    return

  obj = drawpng(vs, args[1])
  el = elib.esclib()

  obj.v.print(el.erase_screen())
  vs.v.print(el.display_mode(False))
  obj.v.callback(obj.update)
  while True:
    time.sleep(1)
    ret = obj.v.read_nb(10)
    if ret:
      if ret[0] > 0:
        obj.v.print("Quit\n")
        obj.v.callback(None)
        break

  vs.v.print(el.display_mode(True))
