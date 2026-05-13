import esclib as elib
import time
import math
import anm
from font2d import font_2d, text_renderer_2d

class text_anim_demo:
  def __init__(self, vs, font_file):
    self.v = vs.v
    self.vs = vs
    self.phase = 0
    self.scale = 6
    self.last_us = time.ticks_us()
    self.start_ms = time.ticks_ms()
    self.font = font_2d(font_file)
    self.renderer = text_renderer_2d(self.font, self.v)
    self.seq = anm.anm_sequencer()
    
    self.word1 = "Fluffy"
    self.word2 = "Pancake"
    self.word1_center_x = 200
    self.word2_center_x = 200

    self.word1_width = self.renderer.get_width(self.word1, self.scale)
    self.word2_width = self.renderer.get_width(self.word2, self.scale)

    self.word1_start_x = self.word1_center_x - self.word1_width / 2.0
    self.word2_start_x = self.word2_center_x - self.word2_width / 2.0

    self.set_anim(0)

  def set_anim(self, phase):
    if phase == 0:
      x = self.word1_start_x
      for i, ch in enumerate(self.word1):
        anmobj = anm.anm_object(700,
        {
        'x' : [lambda t:anm.ease_out_in(t,0.5) , - 110 - i*42, x+10, x],
        'y' : [anm.linear, 140 ,120,150, 140],
        'scale_x' : [anm.linear, 1.0, 0.8, 1.0],
        'scale_y' : [anm.jump, 1.0],
        'rot' : [anm.linear, 0, 0.2, 0]
        }
        )
        adv = self.renderer.get_width(ch, self.scale)
        anmobj.ch = ch
        self.seq.register(f"word1_{i}", anmobj)
        anmobj.seek(-i/7)
        x += adv
    if phase == 1:
      for obj in self.seq:
        newobj = anm.anm_object(700,
        {
        'x' : [anm.jump, obj.x ],
        'y' : [anm.ease_out, obj.y, obj.y-50],
        'scale_x' : [anm.jump, 1.0],
        'scale_y' : [anm.ease_out, 1.0,0.8, 1.0],
        'rot' : [anm.jump, 0]
        }
        )
        newobj.ch = obj.ch
        self.seq.register(obj.key, newobj)
        #print(newobj.x)
    if phase == 2:
      x = self.word2_start_x
      for i, ch in enumerate(self.word2):
        anmobj = anm.anm_object(700,
        {
        'x' : [lambda t:anm.ease_out_in(t,0.5) , - 110 - i*42, x+10, x],
        'y' : [anm.linear, 140 ,120,150, 140],
        'scale_x' : [anm.linear, 1.0, 0.8, 1.0],
        'scale_y' : [anm.linear, 1.0, 1.1, 1.0, 0.9, 1.0],
        'rot' : [anm.linear, 0, 0.6, -0.2,0]
        }
        )
        adv = self.renderer.get_width(ch, self.scale)
        anmobj.ch = ch
        self.seq.register(f"word2_{i}", anmobj)
        anmobj.seek(-i/7)
        x += adv

  def draw_letter(self, ch, x, y, scale_x=1.0, scale_y=1.0, rot=0.0, light=1.0):
    self.renderer.draw_text(ch, x=x, y=y, scale=self.scale, rot=rot, scale_x=self.scale * scale_x, scale_y=self.scale * scale_y, light=light)

  def update(self, e):
    now_us = time.ticks_us()
    diff = time.ticks_diff(now_us, self.last_us)
    fps = 1000000 // diff if diff > 0 else 0
    self.last_us = now_us
    now_ms = time.ticks_ms()
    elapsed = time.ticks_diff(now_ms, self.start_ms)
    
    self.seq.update(now_ms)

    if elapsed > 1400 and self.phase == 0:
      self.phase +=1
      self.set_anim(self.phase)
    if elapsed > 1500 and self.phase == 1:
      self.phase +=1
      self.set_anim(self.phase)

    
    for anm in self.seq:
      self.draw_letter(anm.ch, anm.x, anm.y, anm.scale_x, anm.scale_y, anm.rot,1.0)

    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(8, 14, "FONT ANIMATION DEMO")
    self.v.set_font("u8g2_font_profont11_mf")
    self.v.draw_str(8, 28, str(fps) + " FPS")
    
    self.v.finished()

def main(vs, args):
  font = args[1] if len(args) > 1 else "/sd/lib/font/miranda-bolditalic.g3df"

  el = elib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  demo = text_anim_demo(vs, font)

  v.callback(demo.update)

  try:
    while True:
      ch = vs.read(1)
      if ch == 'q':
        break
  except Exception as ex:
    print("Error: " + str(ex), file=vs)
  finally:
    v.callback(None)
    v.print(el.display_mode(True))
    print("Demo Finished.", file=vs)
