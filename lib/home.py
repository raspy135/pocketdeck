import esclib as elib
import time
import pdeck
import fontloader
import xbmreader
import array
import math
import pdeck_utils
import audio
import codec_config
import random
import menu_ui
import ujson

codec_config= codec_config.codec_config()

SETTING_FILENAME = '/config/settings.json'

def format_mic_gain(value):
  return f'{value/2:.1f}dB'
  
def set_mic_gain(value = None):
  if value != None:
    if value > 0x5f:
      value = 0x5f
    if value < 0:
      value = 0
    codec_config.set_micgain(value)
  if set_audio_power():
    return codec_config.get_micgain()
  return 0
  
def set_mic_auto_gain(value = None):
  if value != None:
    codec_config.set_agc(value)
  if set_audio_power():
    enabled, target_level = codec_config.get_agc()
    return enabled
  return 0
  
def format_audio_volume(value):
  return f'{value}dB'

def set_audio_volume(value = None):
  if value != None:
    if value > 0:
      value = 0
    if value < -60:
      value = -60
    value = 255 + value      
    codec_config.set_vol(value)
  if set_audio_power():
    return codec_config.get_vol()-255
  return 0

def set_speaker_out(value = None):
  if value != None:
    if value:
      codec_config.set_lpf(cutoff_freq=3000, biquad_idx='A')
      codec_config.set_hpf(cutoff_freq=150, biquad_idx='B')
      codec_config.set_hpf(cutoff_freq=80, biquad_idx='C')
    else:
      codec_config.set_pass_through(biquad_idx='A')
      codec_config.set_pass_through(biquad_idx='B')
      codec_config.set_pass_through(biquad_idx='C')
    codec_config.toggle_lo(value)
  if set_audio_power():
    return codec_config.get_lo()
  return True

def set_line_in(value = None):
  if value != None:
    codec_config.toggle_li(value)
  if set_audio_power():
    return codec_config.get_li()
  return True

def set_audio_power(value = None):
  if value != None:
    if audio.power() != value:
      audio.power(value)
  return audio.power()

def set_system_font(value = None):
  if value != None:
    pdeck.set_default_terminal_font_size(value)
  return pdeck.get_default_terminal_font_size()
  
def set_autosleep(value = None):
  if value != None:
    if value < 0:
      value=0
    pdeck_utils.autosleep = value
    pdeck.set_autosleep(value*60)
  return pdeck_utils.autosleep
  
def format_autosleep(value):
  if value == 0:
    return 'never'
  return f'{value} min'

def set_timezone(value = None):
  if value != None:
    pdeck_utils.timezone = value
  return pdeck_utils.timezone
  
def format_timezone(value):
  minute_list = ('00','15','30','45')
  minute = minute_list[abs(value) % 4]
  if value < 0:
    hour = -((-value) // 4)
  else:
    hour = value // 4 
  return f'{hour}:{minute}'

def set_invert(value = None):
  if value != None:
    pdeck.screen_invert(value)
  return pdeck.screen_invert()
  
menu_list = [
 [ 'Launch apps', None ],
 [ 'Audio',[
  [ 'Volume' , 
     { 'description': 'Sound volume in dB',
     'type' : 'int',
     'step' : 3,
     'value' : set_audio_volume(),
     'format' : format_audio_volume,
     'callback' : set_audio_volume
     }
  ],
  [ 'Speaker out' , 
     { 'description': 'Set it off when you use phone out',
     'type' : 'switch',
     'value' : set_speaker_out(),
     'callback' : set_speaker_out
     }
  ],
  [ 'Input source' , 
     { 'description': 'On = Line in, Off = Microphone',
     'type' : 'switch',
     'value' : set_line_in(),
     'callback' : set_line_in
     }
  ],
  [ 'Input gain' ,
     { 'description': 'Input gain in dB',
     'type' : 'int',
     'step' : 3,
     'value' : set_mic_gain(),
     'format' : format_mic_gain,
     'callback' : set_mic_gain
     }
   ],
  [ 'Mic Auto gain' ,
     { 'description': 'Mic auto gain',
     'type' : 'switch',
     'value' : set_mic_auto_gain(),
     'callback' : set_mic_auto_gain
     }
   ],
  [ 'Power' ,
     { 'description': 'Controls audio power',
     'type' : 'switch',
     'value' : set_audio_power(),
     'callback' : set_audio_power
     }
  ],
  ]
 ],
 [ 'Screen',
   [ 
     ['Invert',   
     { 'description': 'Invert screen',
     'type' : 'switch',
     'value' : set_invert(),
     'callback' : set_invert
     }
     ],
     ['System font',   
     { 'description': 'Default system font',
     'type' : 'int',
     'value' : set_system_font(),
     'callback' : set_system_font
     }
     ]
   ]
 ],
 [ 'System',
   [ 
     ['Timezone',   
     { 'description': 'Timezone setting',
     'type' : 'int',
     'value' : set_timezone(),
     'callback' : set_timezone,
     'format' : format_timezone
     }
     ],
     ['Sleep',
     { 'description': 'Autosleep to save power',
     'type' : 'int',
     'value' : set_autosleep(),
     'callback' : set_autosleep,
     'format' : format_autosleep
     }
     ],
   ],
 ],
 [ 'Reload app list', { 'type' : 'reload_applist' } ],
 [ 'Save', { 'type': 'save_settings' } ],
]

class noisebox():
  def __init__(self,v):
    self.v = v
    self.x,self.y,self.w,self.h = (random.randint(0,400), random.randint(0,240), random.randint(0,80), random.randint(0,10))
    self.life = random.randint(2,70)
    self.x_moment = random.randint(0,4) -2
    self.y_moment = random.randint(0,4) -2
    
  def draw(self):
    self.v.set_dither(random.randint(3,14))
    self.v.draw_box(self.x,self.y,self.w,self.h)
    self.v.set_dither(16)
    self.life -= 1

class setting():
  def __init__(self,vs, skiplogo = False):
    self.vs = vs
    self.v = self.vs.v
    self.message_life = 0
    self.message = ""
    self.last_tick=0
    self.current_tick=0
    self.last_r_btn = 0
    if not skiplogo:
      self.splash_count = 400
      self.logo = xbmreader.read_xbmr("/sd/lib/data/nunomo_logo.xbmr")
    else:
      self.splash_count = 0
    self.boxes = []
    self.menu_ui = menu_ui.menu_ui(vs, menu_list)
    self.edit_buffer = ['', '', '']
    self.read_app_list()

  def save_app_list(self):
    filename = '/config/apps.json'
    with open(filename,'w') as f:
      item = self.menu_ui.menu_list[0][1]
      ujson.dump(item, f, separators = (',\n',': '))
      
  def gen_setting_list(self, root):
    out = {}
    for item in root:
      if isinstance(item, list) and len(item) == 2 and isinstance(item[1], list):
        out = out | self.gen_setting_list(item[1],)
      if isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict):
        if 'value' in item[1]:
          out[item[0]] = { 'type' : item[1]['type'], 'value': item[1]['value'] }
    return out
        
  def update_setting(self, root):
    for item in root:
      if isinstance(item, list) and len(item) == 2 and isinstance(item[1], list):
        self.update_setting(item[1])
      if isinstance(item, list) and len(item) == 2 and isinstance(item[1], dict):
        if 'value' in item[1] and item[0] in self.loaded_setting:
          if item[1]['value'] != self.loaded_setting[item[0]]['value']:
            item[1]['value'] = self.loaded_setting[item[0]]['value']
            if 'callback' in item[1] and item[1]['callback'] != None:
              item[1]['callback'](item[1]['value'])

  def load_settings(self):
    filename = SETTING_FILENAME
    try:
      with open(filename, 'r') as f:
        self.loaded_setting = ujson.load(f)
    except Exception as e:
      self.menu_ui.set_message(f'Error in loading setting')
      return
    self.update_setting(self.menu_ui.menu_list[1:])

  def save_settings(self):
    filename = SETTING_FILENAME
    out = self.gen_setting_list(self.menu_ui.menu_list[1:])
    with open(filename,'w') as f:
      ujson.dump(out, f, separators = (',\n',': '))
    
  def read_app_list(self):
    filename = '/config/apps.json'    
    try:
      with open(filename,'r') as f:
        self.menu_ui.menu_list[0][1] = ujson.load(f)
      self.menu_ui.set_message(f'Application list reloaded')
    except Exception as e:
      self.menu_ui.set_message(f'Error: {e}')
      print(e)

  def search_free_screen(self,launched, scnum = None):
    loop = True
    if scnum == None:
      scnum = 2
    else:
      loop = False
    while True:
      if not pdeck.cmd_exists(scnum) and scnum not in launched:
        break
      if not loop:
        return -1
      scnum = scnum + 1
      if scnum == 10:
        return -1
    return scnum
    
  def launch_app(self,command, pref_scnum = None):
    first = True
    launched = []
    for one in command:
      scnum = self.search_free_screen(launched, pref_scnum)
      launched.append(scnum)
      if scnum == - 1:
        break
      if first:
        pdeck.change_screen(scnum)
      first = False
      pdeck_utils.launch(one,scnum)
    pdeck.show_screen_num()
    self.menu_ui.select_root()
    return True

  def draw_splash(self):
    rx = ry = 0
    if random.randint(0,40) == 0:
      rx = random.randint(-20, 20)//10 * 15
    if random.randint(0,40) == 0:
      ry = random.randint(-20, 20)//10 * 15
    self.v.draw_xbm(200-150 +rx, ry+120-41, self.logo[1],self.logo[2], self.logo[3])
    for i in range(40):
      box = random.randint(0,800)
      if box < 3:
        self.boxes.append(noisebox(self.v))
    for key, box in enumerate(self.boxes):
      if box.life == 0:
        del(self.boxes[key])
        continue
      box.draw()
    dc = 0
    if self.splash_count > 300:
      dc = (self.splash_count - 300) // 4
    if self.splash_count < 140:
      dc = (140 - self.splash_count) // 4
    dc = 16 if dc > 16 else dc
    dc = 0 if dc < 0 else dc
    self.v.set_dither(dc)
    self.v.set_draw_color(0)
    self.v.set_bitmap_mode(1)
    self.v.draw_box(0, 0, 400, 240)
    self.v.set_bitmap_mode(0)
    self.v.set_dither(16)
    self.v.set_draw_color(1)

  def update(self,e):
    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = (self.current_tick - self.last_tick)
    if self.splash_count > 0:
      self.draw_splash()
      self.splash_count -= 1
      self.v.finished()
      return
      
    self.menu_ui.seq.update(time.ticks_ms())
    self.menu_ui.handle_key()
    self.menu_ui.draw_cursor(self.time_diff, y_offset=10)
    
    self.menu_ui.draw_menu(y_offset=10)
    self.menu_ui.draw_help()
    self.menu_ui.draw_clock()
    self.menu_ui.draw_message()
    self.menu_ui.draw_dialog()
    self.v.finished()

  def change_value(self,val):
    item = self.menu_ui.get_current_item()[1]
    if not isinstance(item, dict):
      return
    if item['type'] == 'int':
      if 'step' in item:
        step = item['step'] * val
      else:
        step = 1 * val
      item['callback'](item['callback']()+step)
      item['value'] = item['callback']()
    elif item['type'] == 'switch':
      item['callback'](not item['callback']())
      item['value'] = item['callback']()

  def open_launcher_dialog(self):
    if self.menu_ui.depth != 1:
      return
    cur = self.menu_ui.cur_root
    if cur is not self.menu_ui.menu_list[0][1]:
      return
    self.menu_ui.open_dialog({
      'type': 'v_container',
      'name': 'launcher_menu',
      'title': 'Launcher Menu',
      'items': [
        {
          'type': 'button',
          'label': 'Add a new item',
          'onPress': [self.open_add_launcher_dialog, None],
          'close_on_press': False
        },
        {
          'type': 'button',
          'label': 'Move this app',
          'onPress': [self.begin_move_launcher, None]
        },
        {
          'type': 'button',
          'label': 'Delete this app',
          'onPress': [self.open_delete_confirm_dialog, None],
          'close_on_press': False
        }
      ]
    })

  def open_add_launcher_dialog(self, arg=None):
    self.menu_ui.open_dialog({
      'type': 'v_container',
      'name': 'dialog_add_item',
      'title': 'Add launcher',
      'items': [
        {
          'type': 'textbox',
          'name': 'title',
          'label': 'Title'
        },
        {
          'type': 'textbox',
          'name': 'command',
          'label': 'Command'
        },
        {
          'type': 'textbox',
          'name': 'description',
          'label': 'Description'
        },
        {
          'type': 'button',
          'label': 'Add',
          'onPress': [self.add_launcher_from_dialog, 'dialog_menu_item']
        }
      ]
    })
    return False

  def add_launcher_from_dialog(self, values):
    return self.add_launcher_item(
      values.get('title', ''),
      values.get('command', ''),
      values.get('description', '')
    )

  def begin_move_launcher(self, arg=None):
    self.menu_ui.set_move_mode(True)
    self.org_app_list = [n for n in self.menu_ui.menu_list[0][1]]
    return True

  def open_delete_confirm_dialog(self, arg=None):
    self.menu_ui.open_dialog({
      'type': 'v_container',
      'name': 'delete_launcher_confirm',
      'title': 'Delete launcher',
      'items': [
        {
          'type': 'label',
          'text': 'Delete this app?'
        },
        {
          'type': 'h_container',
          'gap': 12,
          'items': [
            {
              'type': 'button',
              'label': 'Cancel',
              'onPress': [self.cancel_dialog, None]
            },
            {
              'type': 'button',
              'label': 'Delete',
              'onPress': [self.confirm_delete_launcher, None]
            }
          ]
        }
      ],
      'height': 120
    })
    return False

  def cancel_dialog(self, arg=None):
    self.menu_ui.close_dialog()
    return True

  def confirm_delete_launcher(self, arg=None):
    self.delete_launcher_item()
    return True

  def parse_command(self, text):
    parts = []
    cur = ''
    in_quote = False
    quote = ''
    i = 0
    while i < len(text):
      ch = text[i]
      if in_quote:
        if ch == quote:
          in_quote = False
        else:
          cur += ch
      else:
        if ch == '"' or ch == "'":
          in_quote = True
          quote = ch
        elif ch == ' ':
          if cur != '':
            parts.append(cur)
            cur = ''
        else:
          cur += ch
      i += 1
    if cur != '':
      parts.append(cur)
    if len(parts) == 0:
      return None
    return [parts]

  def add_launcher_item(self, title, command_line, desc):
    cmd = self.parse_command(command_line)
    if not title or not cmd:
      self.menu_ui.set_message('Title and command required')
      return False
    item = [
      title,
      {
        'type': 'program',
        'command': cmd,
        'description': desc
      }
    ]
    app_list = self.menu_ui.menu_list[0][1]
    insert_at = len(app_list)
    if self.menu_ui.cur_root is app_list:
      insert_at = self.menu_ui.y[self.menu_ui.depth] + 1
    app_list.insert(insert_at, item)
    self.menu_ui.y[self.menu_ui.depth] = insert_at
    self.save_app_list()
    self.menu_ui.set_message('Launcher added')
    return True

  def move_launcher_item(self, delta):
    app_list = self.menu_ui.menu_list[0][1]
    idx = self.menu_ui.y[self.menu_ui.depth]
    new_idx = idx + delta
    if new_idx < 0 or new_idx >= len(app_list):
      return
    tmp = app_list[idx]
    app_list[idx] = app_list[new_idx]
    app_list[new_idx] = tmp
    self.menu_ui.y[self.menu_ui.depth] = new_idx

  def delete_launcher_item(self):
    app_list = self.menu_ui.menu_list[0][1]
    idx = self.menu_ui.y[self.menu_ui.depth]
    if idx < 0 or idx >= len(app_list):
      return
    del app_list[idx]
    if self.menu_ui.y[self.menu_ui.depth] >= len(app_list) and len(app_list) > 0:
      self.menu_ui.y[self.menu_ui.depth] = len(app_list) - 1
    if len(app_list) == 0:
      self.menu_ui.y[self.menu_ui.depth] = 0
    self.save_app_list()
    self.menu_ui.set_message('Launcher deleted')

  def handle_dialog_key(self, keys):
    return self.menu_ui.handle_key(keys)

  def handle_tp_buttons(self):
    tp = self.v.get_tp_keys()
    if not tp or len(tp) < 4:
      return False
    r_btn = tp[3] & 0x02
    triggered = False
    if r_btn and not self.last_r_btn:
      if self.menu_ui.dialog:
        self.menu_ui.close_dialog()
      elif self.menu_ui.move_mode:
        self.menu_ui.set_move_mode(False)
      else:
        self.open_launcher_dialog()
      triggered = True
    self.last_r_btn = 1 if r_btn else 0
    return triggered

  def keyevent_loop(self):
    while True:
      self.handle_tp_buttons()
      ret = self.v.read_nb(1)
      if ret and ret[0] > 0:
        keys = ret[1]
      else:
        if not self.v.active:
          pdeck.delay_tick(200)
        else:        
          pdeck.delay_tick(4)
        continue
        
      keys = keys.encode('ascii')

      if keys == b'q' and not self.menu_ui.dialog:
        break

      if keys == b'\x1b':
        seq = [ keys ]
        seq.append( self.vs.read(1).encode('ascii') )
        if seq[-1] == b'[':
          seq.append( self.vs.read(1).encode('ascii'))
          if seq[-1] >= b'0' and seq[-1] <= b'9':
            seq.append( self.vs.read(1).encode('ascii'))
          keys = b''.join(seq)
        else:
          keys = b''.join(seq)

      if self.menu_ui.dialog:
        self.menu_ui.handle_key(keys)
        continue

      if self.menu_ui.move_mode:
        if keys == b'\x1b[B':
          self.move_launcher_item(1)
        elif keys == b'\x1b[A':
          self.move_launcher_item(-1)
        elif keys == b'\r':
          self.menu_ui.set_move_mode(False)
          self.save_app_list()
          self.menu_ui.set_message('Launcher moved')
        else:
          self.menu_ui.set_move_mode(False)
          self.menu_ui.menu_list[0][1] = self.org_app_list
          self.menu_ui.cur_root = self.menu_ui.menu_list[0][1]
          
          
        continue

      if keys == b'\x1b[B':
        self.menu_ui.move_cursor(1)
      elif keys == b'\x1b[A':
        self.menu_ui.move_cursor(-1)
      elif keys == b'\x1b[C':
        self.change_value(1)
      elif keys == b'\x1b[D':
        self.change_value(-1)
      elif keys == b'\r':
        item = self.menu_ui.get_current_item()[1]
        if isinstance(item, dict):
          if item['type'] == 'reload_applist':
            self.read_app_list()
          if item['type'] == 'save_applist':
            self.save_app_list()
          if item['type'] == 'save_settings':
            self.save_settings()
            self.menu_ui.set_message('Setting saved.')
          if item['type'] == 'program':
            pref_scnum = item.get('screen_number')
            self.launch_app(item['command'], pref_scnum)
          if item['type'] == 'quit':
            break
        if isinstance(item,list):
          self.menu_ui.select_item()
      elif keys == b'\x08':
        self.menu_ui.goup_item()

def main(vs, args):
  el = elib.esclib()  
  obj = setting(vs, True)
  vs.v.print(el.display_mode(False))
  vs.v.callback(obj.update)  
  obj.load_settings()
  obj.keyevent_loop()
  vs.v.callback(None)
  vs.v.print(el.display_mode(True))
  print("finished.", file=vs)
