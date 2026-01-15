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

def set_mic_gain(value = None):
  if value != None:
    if value > 0:
      value = 0
    if value < -60:
      value = -60
    value = 255 + value      
    codec_config.set_micgain(value)
  if set_audio_power():
    return codec_config.get_micgain()-255

  return 0
  
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
    codec_config.toggle_lo(value)
  if set_audio_power():
    return codec_config.get_lo()
  return True

def set_audio_power(value = None):
  if value != None:
    audio.power(value)
  return audio.power()

def set_system_font(value = None):
  if value != None:
    pdeck.set_default_terminal_font_size(value)
  return pdeck.get_default_terminal_font_size()
  

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
  #print('set_invert')
  if value != None:
    pdeck.screen_invert(value)
  return pdeck.screen_invert()
  

menu_list = [
 [ 'Launch apps', None
    ],
 [ 'Audio',[
  [ 'Volume' , 
     { 'description': 'Sound volume in dB',
     'type' : 'int',
     'step' : 3,
     'value' : set_audio_volume(),
     'callback' : set_audio_volume
     }
  ],
  [ 'Speaker out' , 
         { 'description': 'Controls speaker output',
     'type' : 'switch',
     'value' : set_speaker_out(),
     'callback' : set_speaker_out
     }
  ],
  [ 'Microphone gain' ,
     { 'description': 'Microphone sensitivity in dB',
     'type' : 'int',
     'step' : 3,
     'value' : set_mic_gain(),
     'callback' : set_mic_gain
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
   ],
 ],
 [ 'Reload app list', 
    { 'type' : 'reload_applist',
    } 
  ],
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
    #self.x += self.x_moment
    #self.y += self.y_moment
    self.life -= 1
    

class setting():
  def __init__(self,vs, skiplogo = False):
    #fontname = 'cour_r18'
    #fontloader.load(fontname)
    #self.font = fontloader.font_list[fontname]
    self.vs = vs
    self.v = self.vs.v
    self.message_life = 0
    self.message = ""
    self.last_tick=0
    self.current_tick=0
    if not skiplogo:
      self.splash_count = 400
      self.logo = xbmreader.read("/sd/data/nunomo_logo.xbm")
    else:
      self.splash_count = 0
    self.boxes = []
    self.menu_ui = menu_ui.menu_ui(vs, menu_list)
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
        if 'value' in item[1]:
          #print(f'Updating{item[0]}')
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
    #pdeck.cmd_execute(f'set_font_size {self.menu_ui.menu_list[2][1][1][1]['value']}', 1)
    #print(self.menu_ui.menu_list[2][1][1][1]['value'])


  def save_settings(self):
    filename = SETTING_FILENAME
    out = self.gen_setting_list(self.menu_ui.menu_list[1:])
    with open(filename,'w') as f:
      ujson.dump(out, f, separators = (',\n',': '))
    
  def read_app_list(self):
    filename = '/config/apps.json'    
    out = []
    try:
      with open(filename,'r') as f:
        self.menu_ui.menu_list[0][1] = ujson.load(f)
      self.menu_ui.set_message(f'Application list reloaded')
    except Exception as e:
      self.menu_ui.set_message(f'Error: {e}')
      print(e)
      pass
      
  def search_free_screen(self,launched):
    scnum = 2
    while True:
      if not pdeck.cmd_exists(scnum) and scnum not in launched:
        break
      scnum = scnum + 1
      if scnum == 10:
        return -1
    return scnum
    
  def launch_app(self,command):

    #pdeck.cmd_execute(' '.join(command), 1, scnum)
    first = True
    launched = []
    for one in command:
      scnum = self.search_free_screen(launched)
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
    self.v.draw_xbm(200-150 +rx, ry+120-41,
      self.logo[1],self.logo[2], 
      self.logo[3])

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
    #self.v.draw_box(200-143, 120-41, 290, 90)  
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
    self.menu_ui.draw_cursor(self.time_diff)
    self.menu_ui.draw_menu()
    self.menu_ui.draw_help()
    self.menu_ui.draw_clock()
    self.menu_ui.draw_message()
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

  def keyevent_loop(self):
    while True:
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

      if keys == b'q':
        #print('quit')
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
            self.launch_app(item['command'])
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


