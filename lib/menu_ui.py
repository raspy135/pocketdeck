import array
import math
import time
import pdeck_utils
import anm

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
    self.seq = anm.anm_sequencer()
    self.dialog = None
    self.dialog_result = None
    self.dialog_focus = 0
    self.dialog_anim = 0.0
    self.move_mode = False
    self.move_index = 0
    self.move_shift = 0
    self.last_dialog_ms = time.ticks_ms()
    self.set_move_mode(False)

  def set_move_mode(self, mode):
    self.move_mode = mode
    if mode:
      obj = anm.anm_object(200,{
        'x' : [anm.ease_out, 0, 30]})
      self.seq.register('move_shift',obj)
      obj = anm.anm_object(600,{
        'x' : [anm.ease_out_in, 0, 10, 0]}, loop = True)
      self.seq.register('move_wobble',obj)
    else:
      org = self.seq.get_obj('move_shift')
      start = org.x if org else 0 
      obj = anm.anm_object(200,{
        'x' : [anm.ease_out, start, 0,]})
      self.seq.register('move_shift',obj)

      org = self.seq.get_obj('move_wobble')
      start = org.x if org else 0 
      obj = anm.anm_object(600,{
        'x' : [anm.ease_out, start, 0]}, loop = False)
      self.seq.register('move_wobble',obj)
      
  def change_font(self, font, font_height):
    self.item_font = font
    self.item_font_height = font_height
    
  def draw_cursor(self, time_diff, x_offset=0, y_offset=0):
    if self.dialog:
      return
    rotate = math.sin(self.cursor_angle)
    height = int(10 * rotate)
    self.cursor_angle += time_diff * 0.001 * 0.003
    if self.cursor_angle >= 2*3.14159:
      self.cursor_angle -= 2*3.14159
    center_y = y_offset + int(self.item_font_height//4)*3
    points = array.array('h',(
      10 + x_offset, 30 + x_offset, 10 + x_offset,
      center_y - height, center_y, center_y + height
    ))
    self.v.draw_polygon(points)

  def _row_height(self, item):
    h = self.item_font_height
    if isinstance(item[1], dict):
      detail = item[1]
      if 'description' in detail:
        h += 18
      if detail['type'] == 'switch':
        h += 26
      if detail['type'] == 'int':
        h += 24
    return h

  def draw_menu(self, x_offset=0, y_offset=10):
    #self.seq.update(time.ticks_ms())
    c_offset = 0
    c_offset_x = 0
    for i,item in enumerate(self.cur_root):
      if i == self.y[self.depth]:
        break
      c_offset += self._row_height(item)
      
    if self.anm_offset_x > c_offset_x:
      self.anm_offset_x -= (self.anm_offset_x - c_offset_x) // 4 + 1
    if self.anm_offset_x < c_offset_x:
      self.anm_offset_x += (c_offset_x - self.anm_offset_x) // 4 + 1
    if self.anm_offset > c_offset:
      self.anm_offset -= (self.anm_offset - c_offset) // 4 + 1
    if self.anm_offset < c_offset:
      self.anm_offset += (c_offset - self.anm_offset) // 4 + 1
      
    cur_y = y_offset - self.anm_offset
    cur_x = x_offset + self.anm_offset_x
    anm1 = self.seq.get_obj('move_shift')
    anm2 = self.seq.get_obj('move_wobble')
    move_shift = int(anm1.x + anm2.x)
    for idx, item in enumerate(self.cur_root):
      extra_x = 0
      if idx == self.y[self.depth]:
        extra_x += move_shift
      self.v.set_font(self.item_font)
      self.v.draw_str(40 + cur_x + extra_x,cur_y + self.item_font_height, item[0])
      cur_y += self.item_font_height
      if isinstance(item[1], dict):
        detail = item[1]
        self.v.set_font('u8g2_font_profont15_mf')
        if 'description' in detail:
          self.v.draw_str(40 + cur_x + extra_x,cur_y+16, detail['description'])
          cur_y += 18
        if detail['type'] == 'int':
          self.v.set_font('u8g2_font_profont22_mf')
          if 'format' in detail:
            str_value = detail['format'](detail['value'])
          else:
            str_value = str(detail['value'])
          self.v.draw_str(50 + cur_x + extra_x,cur_y+22,str_value) 
          cur_y += 24
        if detail['type'] == 'switch':
          self.v.draw_rframe(50 + cur_x + extra_x,cur_y + 3,30,20,5)
          if detail['value'] == True:
            self.v.draw_rbox(67 + cur_x + extra_x,cur_y + 5, 10, 16,3)
          else:
            self.v.draw_rbox(53 + cur_x + extra_x,cur_y + 5, 10, 16,3)
          cur_y += 26

  def draw_help(self):
    y = 210
    self.v.set_draw_color(0)
    self.v.draw_box(0,y-20, 400, 239 - y + 30)
    self.v.set_draw_color(1)
    if self.message_life > 0:
      return
    self.v.set_font('u8g2_font_profont15_mf')
    if self.dialog:
      self.v.draw_str(65, y,'Up/Down: Move  Left/Right: Edit  Enter: OK')
      y += 16
      self.v.draw_str(65, y, 'B/BS: Cancel')
      return
    if self.move_mode:
      self.v.draw_str(65, y,'MOVE MODE: Up/Down swap item positions')
      y += 16
      self.v.draw_str(65, y, 'Enter: finalize | BS/pad B: cancel')
      return
    self.v.draw_str(65, y,'Up/Down: Move cursor | Left/Right: Change val')
    y += 16
    self.v.draw_str(65, y, 'Enter/pad A: Select item | R bottom: menu')

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

  def open_dialog(self, dialog):
    self.dialog = dialog
    self.dialog_result = None
    self.dialog_focus = 0
    self.last_dialog_ms = time.ticks_ms()
    obj = anm.anm_object(220, {
      'dialog_anim': [anm.ease_out, 0.0, 1.0]
    }, loop=False)
    self.seq.register('dialog_open', obj)

  def close_dialog(self):
    self.dialog = None
    self.dialog_result = None

  def update_animation(self):
    obj = self.seq.get_obj('dialog_open')
    if obj:
      self.dialog_anim = obj.dialog_anim
      
  def draw_button(self,x,y, label, focused):
    self.v.set_font('spleen816')
    button_w = self.v.get_utf8_width(label) + 20
    if focused:
      self.v.set_dither(16)
      self.v.draw_rbox(x, y - 16, button_w, 22, 4)
      self.v.set_draw_color(0)
    else:
      self.v.set_dither(14)
      self.v.draw_rframe(x, y - 16, button_w, 22, 4)

    self.v.draw_str(x + 10, y, label)
    self.v.set_dither(16)         
    self.v.set_draw_color(1)

  def draw_dialog(self):
    if not self.dialog:
      return
    self.update_animation()
    anim = self.dialog_anim
    box_w = int(340 * anim)
    extra_h = 20*len(self.dialog['options']) if 'options' in self.dialog else 180
    extra_h = self.dialog['height'] if 'height' in self.dialog else extra_h
    box_h = int(40 +  extra_h*anim)
    x = 200 - box_w // 2
    y = 120 - box_h // 2
    self.v.set_dither(16)
    self.v.set_draw_color(0)
    self.v.draw_rbox(x, y, box_w, box_h, 8)
    self.v.set_draw_color(1)
    
    self.v.set_dither(1)
    self.v.draw_rbox(x, y, box_w, box_h, 8)
    self.v.set_dither(16)
    self.v.set_draw_color(1)
    if anim < 0.95:
      return
    #self.v.set_font('u8g2_font_profont22_mf')
    #self.v.draw_str(x + 16, y + 24, self.dialog['title'])
    self.v.set_font('u8g2_font_profont22_mf')
    dtype = self.dialog['type']
    cy = y + 32
    cy_end = y + box_h
    if dtype == 'launcher_menu':
      opts = self.dialog['options']
      for i, opt in enumerate(opts):
        self.v.draw_str(x + 22, cy, opt)
        if i == self.dialog_focus:
          self.v.set_draw_color(1)
          self.v.draw_rbox(x + 12, cy - 18, box_w - 24, 26, 4)
          self.v.set_draw_color(0)
          self.v.draw_str(x + 22, cy, opt)
          self.v.set_draw_color(1)
        cy += 28
    elif dtype == 'confirm':
      self.v.draw_str(x + 16, cy, self.dialog['message'])
      opts = ('Cancel', 'Delete')
      self.v.set_font('spleen816')
      for i, opt in enumerate(opts):
        bx = x + 40 + i * 120
        self.draw_button(bx, cy_end - 10, opt, i == self.dialog_focus)
        
    elif dtype == 'add_item':
      self.v.set_font('spleen816')
      labels = self.dialog['labels']
      vals = self.dialog['values']
      cy = y + 38
      for i, label in enumerate(labels):
        self.v.draw_str(x + 16, cy, label)
        self.v.set_draw_color(0)
        self.v.draw_box(x + 110, cy - 14, box_w - 126, 20)
        self.v.set_draw_color(1)
        self.v.set_dither(8)
        tbox_w = box_w - 124
        self.v.draw_frame(x + 110, cy - 14, tbox_w, 20)
        self.v.set_dither(16)
        if i == self.dialog_focus:
          self.v.draw_frame(x + 109, cy - 15, tbox_w+2, 22)
        p_str = vals[i]
        while True:
          if self.v.get_utf8_width(p_str) < tbox_w-15:
            break
          p_str=p_str[1:]
        self.v.draw_str(x + 116, cy, p_str)
        if i == self.dialog_focus:
          str_w = self.v.get_utf8_width(p_str)
          self.v.draw_h_line(x+116+str_w,cy-2,8)
          self.v.draw_h_line(x+116+str_w,cy-1,8)
        cy += 34
      # Button
      if 'button_label' in self.dialog:
        self.draw_button(x + 110, cy, self.dialog['button_label'],self.dialog_focus == len(self.dialog['labels']))



