import array
import math
import time
import pdeck_utils

class menu_ui:
  
  def __init__(self,vs,menu_list):
    self.vs = vs
    self.v = self.vs.v
    self.message_life = 0
    self.menu_list = menu_list
    self.cur_root = self.menu_list
    self.y = [0, 0]
    self.depth = 0
    self.anm_offset = 0
    self.anm_offset_x = 0
    self.cursor_angle = 0
    self.item_font_height = 30
    self.item_font = "u8g2_font_profont29_mf"

  def change_font(self, font, font_height):
    self.item_font = font
    self.item_font_height = font_height
    
  def draw_cursor(self, time_diff, offset=0):
    rotate = math.sin(self.cursor_angle)
    height = int(10 * rotate)
    self.cursor_angle += time_diff * 0.001 * 0.003
    if self.cursor_angle >= 2*3.14159:
      self.cursor_angle -= 2*3.14159
    center_y = offset +  int(self.item_font_height//4)*3 #why???
    points = array.array('h',(10,30,10, center_y - height,center_y, center_y+height))
      
    self.v.draw_polygon(points)

  def draw_menu(self, offset=10):
    # Calculate Y offset
    c_offset = 0
    c_offset_x = 0
    for i,item in enumerate(self.cur_root):
      if i == self.y[self.depth]:
        break
      c_offset += self.item_font_height
      
      if isinstance(item[1] , dict):
        detail = item[1]
        if 'description' in detail:
          c_offset += 18
        if detail['type'] == 'switch':
          c_offset += 26
        if detail['type'] == 'int':
          c_offset += 24
      
    if self.anm_offset_x > c_offset_x:
      self.anm_offset_x -= (self.anm_offset_x - c_offset_x) // 4 + 1
    if self.anm_offset_x < c_offset_x:
      self.anm_offset_x += (c_offset_x - self.anm_offset_x) // 4 + 1
    if self.anm_offset > c_offset:
      self.anm_offset -= (self.anm_offset - c_offset) // 4 + 1
    if self.anm_offset < c_offset:
      self.anm_offset += (c_offset - self.anm_offset) // 4 + 1
      
    cur_y = offset - self.anm_offset
    cur_x = self.anm_offset_x
    for item in self.cur_root:
      self.v.set_font(self.item_font)
      self.v.draw_str(40+ cur_x,cur_y + self.item_font_height, item[0])
      cur_y += self.item_font_height
      if isinstance(item[1], dict):
        detail = item[1]
        self.v.set_font('u8g2_font_profont15_mf')
        if 'description' in detail:
          self.v.draw_str(40+cur_x,cur_y+16, detail['description'])
          cur_y += 18
        if detail['type'] == 'int':
          self.v.set_font('u8g2_font_profont22_mf')
          if 'format' in detail:
            str_value = detail['format'](detail['value'])
          else:
            str_value = str(detail['value'])
            
          self.v.draw_str(50+cur_x,cur_y+22,str_value) 
          cur_y += 24

          
        if detail['type'] == 'switch':
          self.v.draw_rframe(50+cur_x,cur_y + 3,30,20,5)
          if detail['value'] == True:
            self.v.draw_rbox(50+17+cur_x,cur_y + 5, 10, 16,3)
          else:
            self.v.draw_rbox(50+3+cur_x,cur_y + 5, 10, 16,3)
          cur_y += 26


  def draw_help(self):
    y = 210
    self.v.set_draw_color(0)
    self.v.draw_box(0,y-20, 400, 239 - y + 30)
    self.v.set_draw_color(1)
    if self.message_life > 0:
      return
    self.v.set_font('u8g2_font_profont15_mf')
    self.v.draw_str(65, y,'Up/Down: Move cursor | Left/Right: Change val')
    y += 16
    self.v.draw_str(65, y, 'Enter/pad A: Select item | BS/pad B: back')


  def draw_clock(self):
    self.v.set_font('u8g2_font_profont22_mf')
    ctime = time.gmtime(time.time() + 900*pdeck_utils.timezone)
    hour = ctime[3]
    minute = ctime[4]
    second = ctime[5]
    column = ':' if second&1 else ' '
    self.v.draw_str(0, 220, f"{hour:02}{column}{minute:02}")

  def set_message(self, message):
    self.message = message
    self.message_life = 150
  def draw_message(self):
    if self.message_life == 0:
      return
    self.v.set_font('u8g2_font_profont15_mf')

    self.v.draw_str(65,240-22, self.message)
    self.message_life -= 1

  def select_item(self):
    self.cur_root = self.cur_root[self.y[self.depth]][1]
    self.depth += 1
    self.y[self.depth] = 0
    self.anm_offset_x = 100
  
  def select_root(self):
    self.depth = 0
    self.cur_root = self.menu_list
      
  def goup_item(self):
    if self.depth != 0:
      self.depth -= 1
      self.cur_root=self.menu_list
      self.anm_offset_x = -100
      
      for i in range(self.depth):
        self.cur_root = self.cur_root[self.y[i]][1]
    
  def get_current_item(self):
    item = self.cur_root[self.y[self.depth]]
    return item

  def get_current_list_len(self):
    return len(self.cur_root)

  def get_cursor_pos(self):
    return self.y[-1]
    
    
  def move_cursor(self, offset):
    if offset == 0:
      return True
    if offset > 0:
      if len(self.cur_root)-1 > self.y[self.depth]:
        self.y[self.depth] += offset
        return True
      else:
        return False
    if offset < 0:
      if self.y[self.depth] != 0:
        self.y[self.depth] += offset
        return True
      else:
        return False
    

