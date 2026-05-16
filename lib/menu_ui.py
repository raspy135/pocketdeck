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
      self.v.set_draw_color(0)
      self.v.draw_rbox(x, y - 16, button_w, 22, 4)
      self.v.set_draw_color(1)
      self.v.set_dither(14)
      self.v.draw_rframe(x, y - 16, button_w, 22, 4)

    self.v.draw_str(x + 10, y, label)
    self.v.set_dither(16)         
    self.v.set_draw_color(1)


  def _dialog_items(self, node):
    if not node:
      return []
    if isinstance(node, dict):
      if 'items' in node:
        out = []
        for item in node['items']:
          out += self._dialog_items(item)
        return out
      return [node]
    if isinstance(node, list):
      out = []
      for item in node:
        out += self._dialog_items(item)
      return out
    return []

  def _focusable_items(self):
    items = self._dialog_items(self.dialog)
    out = []
    for item in items:
      if not isinstance(item, dict):
        continue
      typ = item.get('type')
      if typ in ('textbox', 'button', 'switch', 'checkbox', 'select'):
        if item.get('enabled', True):
          out.append(item)
    return out

  def _clamp_dialog_focus(self):
    focusable = self._focusable_items()
    if len(focusable) == 0:
      self.dialog_focus = 0
      return
    if self.dialog_focus < 0:
      self.dialog_focus = 0
    if self.dialog_focus >= len(focusable):
      self.dialog_focus = len(focusable) - 1

  def _focused_widget(self):
    focusable = self._focusable_items()
    if len(focusable) == 0:
      return None
    self._clamp_dialog_focus()
    return focusable[self.dialog_focus]

  def _widget_value(self, item):
    if 'value' in item:
      return item['value']
    typ = item.get('type')
    if typ == 'textbox':
      item['value'] = ''
      return item['value']
    if typ in ('switch', 'checkbox'):
      item['value'] = False
      return item['value']
    if typ == 'select':
      item['value'] = 0
      return item['value']
    return None

  def get_dialog_values(self):
    values = {}
    for item in self._dialog_items(self.dialog):
      if isinstance(item, dict) and 'name' in item:
        typ = item.get('type')
        if typ in ('textbox', 'switch', 'checkbox', 'select'):
          values[item['name']] = self._widget_value(item)
    return values

  def _run_widget_callback(self, item):
    spec = item.get('onPress')
    if spec == None:
      return None
    values = self.get_dialog_values()
    if isinstance(spec, (list, tuple)):
      cb = spec[0]
      if len(spec) <= 1:
        return cb()
      arg = spec[1]
      if arg == 'dialog_values' or arg == 'dialog_menu_item':
        return cb(values)
      if arg == 'focused_item':
        return cb(item)
      if arg == 'dialog':
        return cb(self.dialog)
      if arg == None:
        return cb()
      return cb(arg)
    return spec(values)

  def _press_focused_widget(self):
    item = self._focused_widget()
    if not item:
      return False
    typ = item.get('type')
    if typ == 'button':
      old_dialog = self.dialog
      result = self._run_widget_callback(item)
      close_on_press = item.get('close_on_press', True)
      if close_on_press and result is not False and self.dialog is old_dialog:
        self.close_dialog()
      return True
    if typ in ('switch', 'checkbox'):
      item['value'] = not self._widget_value(item)
      self._run_widget_callback(item)
      return True
    if typ == 'select':
      self._change_focused_select(1)
      return True
    return False

  def _change_focused_select(self, direction):
    item = self._focused_widget()
    if not item or item.get('type') != 'select':
      return False
    opts = item.get('options', ())
    if len(opts) == 0:
      return False
    val = int(self._widget_value(item))
    val += direction
    if val < 0:
      val = 0
    if val >= len(opts):
      val = len(opts) - 1
    item['value'] = val
    self._run_widget_callback(item)
    return True

  def handle_key(self, keys=None):
    if not self.dialog:
      return False
    # Passing None is intentionally a no-op. Home may call this from its
    # update loop, while actual key bytes are delegated from keyevent_loop.
    if keys == None:
      return False
    if isinstance(keys, str):
      keys = keys.encode('ascii')
    focusable = self._focusable_items()
    if len(focusable) == 0:
      if keys == b'\x08' or keys == b'\x1b':
        self.close_dialog()
        return True
      return False
    item = self._focused_widget()
    typ = item.get('type') if item else None

    if keys == b'\x1b[B':
      if self.dialog_focus < len(focusable) - 1:
        self.dialog_focus += 1
      return True
    if keys == b'\x1b[A':
      if self.dialog_focus > 0:
        self.dialog_focus -= 1
      return True
    if keys == b'\x1b[C':
      if typ == 'select':
        return self._change_focused_select(1)
      if typ in ('switch', 'checkbox'):
        item['value'] = True
        self._run_widget_callback(item)
        return True
      return True
    if keys == b'\x1b[D':
      if typ == 'select':
        return self._change_focused_select(-1)
      if typ in ('switch', 'checkbox'):
        item['value'] = False
        self._run_widget_callback(item)
        return True
      return True
    if keys == b'\r':
      if typ == 'textbox':
        if self.dialog_focus < len(focusable) - 1:
          self.dialog_focus += 1
        return True
      return self._press_focused_widget()
    if keys == b'\x08' or keys == b'\x1b':
      if typ == 'textbox' and len(self._widget_value(item)) > 0:
        item['value'] = self._widget_value(item)[:-1]
      else:
        self.close_dialog()
      return True
    if typ == 'textbox' and keys and keys[0] >= 32 and keys[0] < 127:
      item['value'] = self._widget_value(item) + keys.decode('ascii')
      return True
    return True

  def _widget_height(self, item):
    typ = item.get('type') if isinstance(item, dict) else None
    if typ == 'textbox':
      return 34
    if typ == 'button':
      return 30
    if typ in ('switch', 'checkbox', 'select'):
      return 28
    if typ == 'label':
      return 20
    if typ in ('v_container', 'dialog'):
      return self._calc_dialog_height(item.get('items', ()), False)
    if typ == 'h_container':
      return self._calc_h_container_height(item)
    return 24

  def _calc_h_container_height(self, item):
    max_h = 0
    for child in item.get('items', ()):
      h = self._widget_height(child)
      if h > max_h:
        max_h = h
    return max_h

  def _calc_dialog_height(self, items, include_padding=True):
    h = 44 if include_padding else 0
    for item in items:
      h += self._widget_height(item)
    return h

  def _draw_textbox(self, item, x, y, box_w, focused):
    self.v.set_font('spleen816')
    label = item.get('label', item.get('name', ''))
    self.v.draw_str(x + 16, y, label)
    tbox_x = x + 110
    tbox_w = box_w - 126
    self.v.set_draw_color(0)
    self.v.draw_box(tbox_x, y - 14, tbox_w, 20)
    self.v.set_draw_color(1)
    self.v.set_dither(8)
    self.v.draw_frame(tbox_x, y - 14, tbox_w, 20)
    self.v.set_dither(16)
    if focused:
      self.v.draw_frame(tbox_x - 1, y - 15, tbox_w + 2, 22)
    p_str = str(self._widget_value(item))
    while len(p_str) > 0:
      if self.v.get_utf8_width(p_str) < tbox_w - 15:
        break
      p_str = p_str[1:]
    self.v.draw_str(tbox_x + 6, y, p_str)
    if focused:
      str_w = self.v.get_utf8_width(p_str)
      self.v.draw_h_line(tbox_x + 6 + str_w, y - 2, 8)
      self.v.draw_h_line(tbox_x + 6 + str_w, y - 1, 8)

  def _draw_switch(self, item, x, y, box_w, focused):
    self.v.set_font('spleen816')
    label = item.get('label', item.get('name', ''))
    self.v.draw_str(x + 16, y, label)
    sx = x + box_w - 70
    if focused:
      self.v.draw_frame(sx - 4, y - 18, 42, 24)
    self.v.draw_rframe(sx, y - 16, 34, 20, 5)
    if self._widget_value(item):
      self.v.draw_rbox(sx + 19, y - 14, 12, 16, 3)
    else:
      self.v.draw_rbox(sx + 3, y - 14, 12, 16, 3)

  def _draw_select(self, item, x, y, box_w, focused):
    self.v.set_font('spleen816')
    label = item.get('label', item.get('name', ''))
    opts = item.get('options', ())
    val = int(self._widget_value(item))
    if len(opts) > 0:
      if val < 0:
        val = 0
      if val >= len(opts):
        val = len(opts) - 1
      text = str(opts[val])
    else:
      text = ''
    self.v.draw_str(x + 16, y, label)
    self.v.draw_str(x + 150, y, '< ' + text + ' >')
    if focused:
      self.v.draw_frame(x + 145, y - 16, box_w - 160, 22)

  def _draw_dialog_item(self, item, x, cy, box_w, focused):
    typ = item.get('type') if isinstance(item, dict) else None
    is_focused = item is focused
    if typ == 'label':
      self.v.set_font('spleen816')
      self.v.draw_str(x + 16, cy, item.get('text', item.get('label', '')))
      return 24
    if typ == 'textbox':
      self._draw_textbox(item, x, cy, box_w, is_focused)
      return 34
    if typ == 'button':
      bx = item.get('x', x + 110)
      self.draw_button(bx, cy, item.get('label', 'OK'), is_focused)
      return 30
    if typ in ('switch', 'checkbox'):
      self._draw_switch(item, x, cy, box_w, is_focused)
      return 28
    if typ == 'select':
      self._draw_select(item, x, cy, box_w, is_focused)
      return 28
    if typ in ('v_container', 'dialog'):
      return self._draw_v_container(item, x, cy, box_w, focused)
    if typ == 'h_container':
      return self._draw_h_container(item, x, cy, box_w, focused)
    return 24

  def _draw_v_container(self, item, x, cy, box_w, focused):
    start_y = cy
    child_x = x + item.get('pad_left', 0)
    child_w = box_w - item.get('pad_left', 0) - item.get('pad_right', 0)
    for child in item.get('items', ()):
      cy += self._draw_dialog_item(child, child_x, cy, child_w, focused)
    return cy - start_y

  def _draw_h_container(self, item, x, cy, box_w, focused):
    children = item.get('items', ())
    count = len(children)
    if count == 0:
      return 0

    gap = item.get('gap', 8)
    margin_l = item.get('pad_left', 16)
    margin_r = item.get('pad_right', 16)
    available_w = box_w - margin_l - margin_r - gap * (count - 1)
    if available_w < count:
      available_w = count
    cell_w = available_w // count
    row_h = self._calc_h_container_height(item)

    cx = x + margin_l
    for child in children:
      typ = child.get('type') if isinstance(child, dict) else None
      if typ == 'button':
        label = child.get('label', 'OK')
        button_w = self.v.get_utf8_width(label) + 20
        bx = cx + (cell_w - button_w) // 2
        if bx < cx:
          bx = cx
        self.draw_button(bx, cy, label, child is focused)
      else:
        self._draw_dialog_item(child, cx, cy, cell_w, focused)
      cx += cell_w + gap
    return row_h

  def _draw_generic_dialog(self):
    self.update_animation()
    anim = self.dialog_anim
    items = self.dialog.get('items', ())
    box_w_target = self.dialog.get('width', 340)
    box_h_target = self.dialog.get('height', self._calc_dialog_height(items))
    box_w = int(box_w_target * anim)
    box_h = int(box_h_target * anim)
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

    title = self.dialog.get('title', '')
    cy = y + 28
    if title:
      self.v.set_font('u8g2_font_profont22_mf')
      self.v.draw_str(x + 16, cy, title)
      cy += 26
    else:
      cy = y + 32

    focused = self._focused_widget()
    for item in items:
      cy += self._draw_dialog_item(item, x, cy, box_w, focused)

  def draw_dialog(self):
    if not self.dialog:
      return
    if 'items' in self.dialog or self.dialog.get('type') in ('v_container', 'h_container', 'dialog'):
      self._draw_generic_dialog()
      return
      
    return
    # Fallback: unknown old-style dialog data is rendered as a simple message.
    self.update_animation()
    anim = self.dialog_anim
    box_w = int(340 * anim)
    box_h = int(self.dialog.get('height', 80) * anim)
    x = 200 - box_w // 2
    y = 120 - box_h // 2
    self.v.set_dither(16)
    self.v.set_draw_color(0)
    self.v.draw_rbox(x, y, box_w, box_h, 8)
    self.v.set_draw_color(1)
    self.v.set_dither(1)
    self.v.draw_rbox(x, y, box_w, box_h, 8)
    self.v.set_dither(16)
    if anim >= 0.95:
      self.v.set_font('u8g2_font_profont22_mf')
      self.v.draw_str(x + 16, y + 32, self.dialog.get('message', self.dialog.get('title', 'Dialog')))
