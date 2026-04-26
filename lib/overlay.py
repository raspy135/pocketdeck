import pdeck
import time

last_us = 0

def show_fps(v):
  global last_us
  current = time.ticks_us()
  diff = current - last_us
  last_us = current
  fps = 1000000 // diff
  v.set_draw_color(0)
  v.draw_box(350,0,50,15)
  v.set_draw_color(1)
  v.set_font("u8g2_font_profont15_mf")
  a = f'{fps:3d} FPS'
  v.draw_str(400-50,10,a)

