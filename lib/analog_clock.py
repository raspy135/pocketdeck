import esclib as elib
import pdeck_utils
import time
import pdeck
import random
import math
import datetime
import network, socket
import ujson
import urequests as requests
import array
import xbmreader
import audio

from machine import RTC

rtc = RTC()

pi = const(3.14126536)
twopi = const(6.282531)

#Constants (Maybe it will improve performance?)
dc = { \
  "pi * 2 / 24" : (pi * 2 / 24),
  "pi * 2" : (pi * 2),
  "1/1000000" : (1/1000000),
  "pi * 2 / 60" : (pi * 2 / 60 ),
  "60*60*tz" : 60*15*pdeck_utils.timezone,
  "pi * 2 / 12": (pi * 2 / 12 ),
  "1/60": (1/60),
  "2*pi/1024" : (2*pi/1024),
  "/ (2 * 3.1415926536)" : 1.0 / (2 * 3.1415926536),
  "0.5 * 3.1415926536": (0.5 * 3.1415926536),
  "60*60*24": 60*60*24
}

class dsp_utils:
  def __init__(self):
    self.pi = 3.1415926536
    self.tablesize = 1024
    self.sin_table = array.array('f',bytearray(self.tablesize*4))
    for i in range(self.tablesize):
      self.sin_table[i] = math.sin(i * dc['2*pi/1024'])
      
  def sin(self, angle):
    index = angle * (self.tablesize * dc['/ (2 * 3.1415926536)'])
    #print(index)
    index = int(index)
    while True:
      if index < 0:
        index += self.tablesize
      elif index >= self.tablesize:
        index -= self.tablesize
      else:
        break
    return self.sin_table[index]
  def cos(self, angle):
    return self.sin(angle + dc['0.5 * 3.1415926536'])


KT_STOP = const(0)
KT_RUNNING = const(1)
KT_ALARM = const(2)

class ktimer:
  def __init__(self):
    self.stat = KT_STOP
    self.starttime = None
    self.minute = 0
    self.second = 0
    self.touched = False
    self.dial_base = 0

class analog_clock:
  def __init__(self,v, vs):
    self.key_event = False
    self.tide_chart = None
    self.message = ''
    self.message_life = 0
    self.du = dsp_utils()
    self.v = v
    self.vs = vs
    self.size = 100
    self.seconds_m_size = (85,95)
    self.hourhand_size = 60
    self.minutehand_size = 80
    self.number_size = 75
    self.secondhand_size = 90
    self.offset = (110,125)
    self.offset_days = 0
    self.pi = 3.1415926536
    self.week_list = ("Mo", "Tu", "We" ,"Th", "Fr", "Sa", "Su" )
    self.week_list2 = ("Mon", "Tue", "Wed" ,"Thu", "Fri", "Sat", "Sun" )
    
    
    self.month_list = ( \
    "","January","Febrary","March","April", \
    "May","June", "July", "August","September", \
    "October","November", "December" )
    self.tide_front = False    
    self.update_time()
    self.last_day = self.day
    self.last_second = self.second
    self.update_shifted_day()
    
    self.catimage = []
    self.catimage.append(xbmreader.read("/sd/data/cat1.xbm"))
    self.catimage.append(xbmreader.read("/sd/data/cat2.xbm"))
    self.catimage.append(xbmreader.read("/sd/data/cat3.xbm"))
    self.catimage.append(xbmreader.read("/sd/data/cat4.xbm"))
    self.cat_anm_goal = 0
    self.cat_anm_ct = 0
    self.cat_x = 0
    #self.last_us=0
    self.page = 'clock'
    self.kt = ktimer()
    self.wavbuf = array.array('h',bytearray(0x10000))
    phase = 0
    for i in range(0x4000):
      if i&0x1000 == 0:
        self.wavbuf[i] = int(self.du.sin(phase)*(10000-(i&0xfff)*2))
        phase += 0.3
        if phase > twopi: phase -= twopi
    #audio.stream_setup(0, 48000, 1, len(self.wavbuf))
    #audio.stream_setdata(0, 0, memoryview(self.wavbuf))
    
    self.wavbuf_click = array.array('h',bytearray(0x1000))
    for i in range(0x800):
        self.wavbuf_click[i] = int(math.sin(i*1)*1000)
      
  def wavplay_alarm(self):
    audio.stream_setup(0, 48000, 1, len(self.wavbuf))
    audio.stream_setdata(0, 0, memoryview(self.wavbuf))
    audio.stream_play(True)
    
  def wavplay_click(self):
    audio.stream_setup(0, 48000, 1, len(self.wavbuf_click))
    audio.stream_setdata(0, 0, memoryview(self.wavbuf_click))
    audio.stream_play(True)
        
  def update(self,e):
    if not self.v.active:
      self.v.finished()
      return

    self.update_time()
    
    if self.last_day != self.day:
      self.last_day = self.day
      self.get_tide(self.shifted_day)
    
    self.coffset = (300,40)
    #self.draw_edge()
    self.update_timer()
    
    if not e and self.cat_anm_ct >= 12 and not self.key_event and not self.kt.touched and self.last_second == self.second:

      if self.message_life > 0:
        self.message_life -= 1
    
      self.v.finished()
      return

    self.last_second = self.second
    
    #self.draw_secondhand()
    #return

    if self.page == 'timer':
      self.draw_measure()
      self.draw_numbers(24)
      self.draw_timerhand()
      self.draw_timerdigit()
      
    if self.page == 'clock':
      self.draw_cat()  
      self.draw_measure()
      self.draw_numbers(12)
      if not self.tide_front:
        self.draw_tide_chart()
      self.draw_hourhand()
      self.draw_minutehand()
      self.draw_secondhand()
      if self.tide_front:
        self.draw_tide_chart()

      self.draw_calender()

      
    if self.message_life > 0:
      self.v.set_font_mode(0)
      self.v.set_draw_color(1)
      self.v.set_font('u8g2_font_profont15_mf')
      #self.v.draw_button_utf8(100,30,1,200,5,5,self.message)
      m_width = self.v.get_str_width(self.message)
      self.v.set_dither(12)
      self.v.draw_box(90,110,m_width+20,30)
      self.v.set_dither(2)
      self.v.draw_box(95,115,m_width+10,20)
      self.v.set_dither(16)
      self.v.draw_str(100,130,self.message)
      self.message_life -= 1

    self.key_event = False
    self.v.finished()
    return

  def update_timer(self):
    kt = self.kt
    if kt.stat == KT_ALARM:
      if not audio.stream_play():
        self.wavplay_alarm()

    if kt.stat == KT_RUNNING:
      curtime = time.ticks_ms()
      kt.second_past = int(((curtime - kt.starttime) / (1000)))
      kt.minute = int(kt.org_minute + (kt.org_second / 60)- (self.kt.second_past / 60))
      kt.second = int(kt.org_second - (self.kt.second_past %60))
      if kt.second < 0:
        kt.second += 60
      if kt.minute < 0 or (kt.minute == 0 and kt.second == 0):
        kt.minute = 0
        kt.second = 0
        kt.stat = KT_ALARM
        self.wavplay_alarm()
    if not self.v.active:
      return
          
    input = self.v.get_tp_keys()
    if not input:
      return
    mb = input[3]
    if mb&1 != 0:
      self.page = 'clock'
    if mb&2 != 0:
      self.page = 'timer'
    if mb&3 != 0:
      self.key_event = True
    if self.page != 'timer':
      return
      
    dial = input[4]
    if dial == 0xff:
      if kt.minute > 0 and kt.touched:
          kt.starttime = time.ticks_ms()
          kt.second_past = 0
          kt.org_minute = kt.minute
          kt.org_second = kt.second
          kt.stat = KT_RUNNING

      kt.touched = False
    else:
      if not kt.touched:
        kt.dial_base = dial
        kt.minute_base = kt.minute
        kt.stat = KT_STOP
        kt.second = 0
      kt.touched = True

    if kt.touched:
      dial_distance = dial - kt.dial_base
      if dial_distance > 80:
        dial_distance = dial - (kt.dial_base + 160)
      elif dial_distance < -80:
        dial_distance = (dial+160) - kt.dial_base
      last_minute = kt.minute
      kt.minute += int(dial_distance / 20)
      if kt.minute < 0:
        kt.minute = 0
      if last_minute != kt.minute:
        kt.dial_base = dial
        #self.wavplay_click()
      
    #self.v.draw_str(300,20,str(input[4]))
    #self.v.draw_str(300,35,str(kt.minute))
    #self.v.draw_str(300,50,str(kt.dial_base))

  def draw_cat(self):

    image_index = self.cat_anm_goal
    if self.cat_anm_ct < 12:
      if self.cat_anm_goal == 3:
        image_index = self.cat_anm_ct >> 2
      if self.cat_anm_goal == 0:
        image_index = 3 - (self.cat_anm_ct >> 3)
      self.cat_anm_ct += 1
    else:      
      if random.randint(0,10) == 0:
        self.cat_anm_goal = 3 - self.cat_anm_goal
        self.cat_anm_ct = 0
      
    image = self.catimage[image_index]
    #self.v.set_draw_color(2)
    #self.v.draw_xbm(140,155, image[1], image[2], image[3])
    self.v.draw_xbm(295+self.cat_x,15, image[1], image[2], image[3])
    #self.cat_x += 1
    if self.cat_x == 20:
      self.cat_x = 0
    #self.v.set_draw_color(1)

  def draw_tide_chart(self):
    if not self.tide_chart:
      return
    # data starts from 0AM, 6 min interval per data. So let's skip to 7
    x = self.offset[0] - 50
    y = self.offset[1] - 10
    #print(self.tide_chart)
    for i in range(70,170):
      if i%10 == 0:
        self.v.set_dither(16)
        if i%30 == 0:
          self.v.draw_str(x - 5, y + 14, str(int(i/10)))
      else:
        self.v.set_dither(6)
      pix_height = int(self.tide_chart[i] * 10)
      #if pix_height < 0:
      #  pix_height == 0

      if pix_height > 0:
        self.v.draw_v_line(x, y - pix_height,pix_height)
      else:
        self.v.draw_v_line(x, y,-pix_height)
      
      #self.v.draw_line(x, y - pix_height,x,y)
      
      x = x + 1
      
    x = self.offset[0] - 50
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.set_dither(10)
    self.v.draw_h_line(x - 3, y - 10, 103)
    self.v.draw_h_line(x - 3, y - 20, 103)
    self.v.draw_h_line(x - 3, y - 30, 103)
    self.v.draw_h_line(x - 3, y - 40, 103)
    self.v.set_dither(16)

  def draw_calender(self):
    shifted_day = self.shifted_day
    
    self.v.set_font("u8g2_font_profont29_mf")
    month_str = self.month_list[self.month][:3]
    
    self.v.draw_str(self.coffset[0] - 50, self.coffset[1]-0, f"{month_str} {self.day}")

    
    d = time.mktime((shifted_day.year, shifted_day.month,1,0,0,0,0,0))
    
    day = 1
    weekrow = 0
    month = shifted_day.month
    
    
    self.v.set_font("u8g2_font_profont22_mf")
    month_str = self.month_list[shifted_day.month][:3]
    
    self.v.draw_str(self.coffset[0]-40, self.coffset[1]+35, f"{month_str}")
    self.v.set_font("u8g2_font_profont15_mf")

    # Week letters
    for i, week in enumerate(self.week_list):
      self.v.draw_str(self.coffset[0] - 50 + i * 20, self.coffset[1] + 55 + weekrow*20, f"{week}")

    weekrow += 1    

    while True:
      gmd = time.gmtime(d)
      if gmd[1] != month:
        break
      day = gmd[2]      
      weekday = gmd[6]
      self.v.set_font_mode(0)
      if day == shifted_day.day:
        #print(f"day {day}")
        #self.v.set_draw_color(1)
        #self.v.draw_box(self.coffset[0] - 50 + weekday * 20, self.coffset[1] + 50 + weekrow*20-15, 15,15)
        self.v.set_draw_color(0)
      else:        
        self.v.set_draw_color(1)
      self.v.draw_str(self.coffset[0] - 50 + weekday * 20, self.coffset[1] + 55 + weekrow*20, f"{day}")
      d = d + dc['60*60*24']
      if weekday == 6:
        weekrow += 1
    self.v.set_draw_color(1)
        

  def draw_numbers(self,ncount):
    self.v.set_font("u8g2_font_profont15_mf")
    for i in range(ncount):
      angle = i * twopi / ncount
      x = self.du.cos(angle) * self.number_size
      y = self.du.sin(angle) * self.number_size
      x += self.offset[0]
      y += self.offset[1]
      x = int(x)
      y = int(y)
      if ncount == 12:
        num = str(((i + 2) % ncount) + 1)
      elif ncount == 24:
        num = str(((i + 5) % ncount) + 1)
      extra = 3 if len(num) == 2 else -1
      
      self.v.draw_str(x-3-extra,y+6, num)


  def draw_edge(self):
    self.v.draw_disc(self.offset[0], self.offset[1], self.size+2,0xf) # 0xf = DRAW_ALL
    self.v.set_draw_color(0)
    self.v.draw_disc(self.offset[0], self.offset[1], self.size,0xf) # 0xf = DRAW_ALL
    self.v.set_draw_color(1)
    
  def rotate_pos(self, x, y, angle):
    rx = x * self.du.cos(angle) - y * self.du.sin(angle)
    ry = x * self.du.sin(angle) + y * self.du.cos(angle)
    return (rx, ry)

  def draw_timerdigit(self):
    self.v.set_font("u8g2_font_profont29_mf")
    month_str = self.month_list[self.month][:3]
    self.v.draw_str(self.coffset[0] - 40, self.offset[1]-0, f"{self.kt.minute:02} : {self.kt.second:02}")
    

  def draw_timerhand(self):
    minute = self.kt.minute
    second = self.kt.second
    h = minute + second * dc["1/60"]
    angle = h * dc["pi * 2 / 24"] 
  
    point_pair = ( \
      ( -10, 10 ), \
      ( 10,  10 ), \
      ( 0, -self.minutehand_size ))
    #  ( -5, 5))
      
    self.draw_poly(angle, point_pair, 1)
    
  def draw_hourhand(self):
    h = self.hour + self.minute * dc['1/60']
    angle = h * dc["pi * 2 / 12"]
    
    point_pair = ( \
      ( -8, 8 ), \
      ( 8,  8 ), \
      ( 0, -self.hourhand_size ))
    #  ( -8, 8))
      
    self.draw_poly(angle, point_pair)

  def draw_minutehand(self):
    h = self.minute + self.second * dc["1/60"]
    angle = h * dc["pi * 2 / 60"]
  
    point_pair = ( \
      ( -5, 5 ), \
      ( 5,  5 ), \
      ( 0, -self.minutehand_size ))
    #  ( -5, 5))
      
    self.draw_poly(angle, point_pair)

  def draw_secondhand(self):
    h = self.second + self.micro * dc["1/1000000"]
    angle = h * dc["pi * 2 / 60"]
    
    point_pair = ( \
      ( -3, 3 ), \
      ( 2,  3 ), \
      ( 0, -self.secondhand_size ))
    #  ( -3, 3))
      
    self.draw_poly(angle, point_pair)
    
  def draw_poly(self, angle, point_pair, color=0):
    self.v.set_draw_color(color)
    x = 0
    y = 0
    last_x = 0
    last_y = 0
    points = array.array('h',[0]*(len(point_pair)*2))
    points_line = []
    for i,pair in enumerate(point_pair):
      x, y = self.rotate_pos(pair[0],pair[1], angle)
      x += self.offset[0]
      y += self.offset[1]
      x = int(x)
      y = int(y)
      points[i] = x
      points[len(point_pair) + i] = y
      points_line.append((x,y))
 
    self.v.draw_polygon(points)
    
    # Draw outline
    self.v.set_draw_color(1)
    points_line.append(points_line[0])
    for i,p in enumerate(points_line):
      x,y = p
      if i > 0:
        self.v.draw_line(last_x, last_y, x, y)
      last_x = x
      last_y = y
          
  def draw_measure(self):
    for i in range(24):
      angle = i * dc["pi * 2 / 24"]
      size1 = self.seconds_m_size[0]
      if i % 3 == 0:
        size1 -= 2
      else:
        size1 += 4
      x1 = self.du.cos(angle) * size1
      x2 = self.du.cos(angle) * self.seconds_m_size[1]
      y1 = self.du.sin(angle) * size1
      y2 = self.du.sin(angle) * self.seconds_m_size[1]
      x1 += self.offset[0]
      x2 += self.offset[0]
      y1 += self.offset[1]
      y2 += self.offset[1]
      
      self.v.draw_line(int(x1),int(y1),int(x2),int(y2))

  def get_tide(self, qdate):
    if qdate != None:
      date_str = '{:04d}{:02d}{:02d}'.format(qdate.year, qdate.month, qdate.day)
    else:
      return
      
    station = network.WLAN(network.STA_IF)
    if not station.isconnected():
      return
 
    #print(date_str)
    
    self.url= f'https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?begin_date={date_str}&range=24&station=9411340&product=predictions&datum=MLLW&time_zone=lst_ldt&units=english&application=DataAPI_Sample&format=json'
    
    self.headers = {
      'Content-Type' : 'application/json',
      'Accept': 'application/json',
      }
    
    response = requests.get(self.url, headers=self.headers)
    response_data = response.json()
    response.close()
    #print(response_data)
    self.tide_chart = []
    if response_data:
      for entry in response_data['predictions']:
        #print(entry['t'])
        self.tide_chart.append(float(entry['v']))
    #print(self.tide_chart)

  def update_time(self):
    ctime = time.gmtime(time.time() + dc["60*60*tz"])
    #ctime = rtc.datetime()
    self.hour = ctime[3] 
    self.year = ctime[0]
    self.month = ctime[1]
    self.day = ctime[2]
    self.week = ctime[6]
    self.minute = ctime[4]
    self.second = ctime[5]
    self.micro = 0 #ctime[7]
            

  def update_shifted_day(self):
    shifted_day = datetime.date(self.year, self.month, self.day) + datetime.timedelta(days = self.offset_days)
    #print(f"sday.month {shifted_day.month}, year= {shifted_day.year}")      
    self.shifted_day = shifted_day

  def keyevent_loop(self):
    
    #if not self.tide_chart:
    #  self.get_tide(self.shifted_day)
    
    while True:
      ret = self.v.read_nb(1)
      if ret and ret[0] > 0:
        keys = ret[1]
      else:
        #time.sleep_ms(4)
        if not self.v.active:
          pdeck.delay_tick(200)
        else:        
          pdeck.delay_tick(4)
        
        if self.kt.stat == KT_RUNNING or self.kt.stat == KT_ALARM:
          self.update_timer()
        continue
        
      #keys = self.vs.read(1)
      #audio_setup.c.beep()
      keys = keys.encode('ascii')



      if keys == b'\x1b':
        seq = [ keys ]
        
        seq.append( self.vs.read(1).encode('ascii') )
        if seq[-1] == b'[':
          seq.append( self.vs.read(1).encode('ascii'))
          if seq[-1] >= b'0' and seq[-1] <= b'9':
            seq.append( self.vs.read(1).encode('ascii'))
          keys = b''.join(seq)
          #print(keys)
        else:
          keys = b''.join(seq)

      if self.page == 'timer':
        if keys == b'q':
          print('quit')
          break
        if keys == b'\x0d':
          self.wavplay_click()
          if self.kt.stat == KT_RUNNING:
            self.kt.stat = KT_STOP
            self.wavplay_click()
          elif self.kt.stat == KT_STOP and (self.kt.minute > 0 or self.kt.second > 0):
            self.kt.starttime = time.ticks_ms()
            self.kt.second_past = 0
            self.kt.org_minute = self.kt.minute
            self.kt.org_second = self.kt.second
            self.kt.stat = KT_RUNNING
          elif self.kt.stat == KT_ALARM:
            self.kt.stat = KT_STOP
        if keys == b'\b':
          if self.kt.minute == 0 and self.kt.second == 0 and self.kt.stat != KT_ALARM:
            self.page = 'clock'
          else:
            self.wavplay_click()
            self.kt.minute = 0
            self.kt.second = 0
            self.kt.stat = KT_STOP

        #if keys == b'\x1b[D':
        #  self.kt.minute -= 1
        #elif keys == b'\x1b[C':
        #  self.kt.minute += 1
          
        self.key_event = True
        continue

      # Key events for clock
      days_changed = True
      if keys == b'\x1b[D':
        self.offset_days -= 1
      elif keys == b'\x1b[C':
        self.offset_days += 1
      elif keys == b'\x1b[B':
        self.offset_days += 7
      elif keys == b'\x1b[A':
        self.offset_days -= 7
      elif keys == b'\x0d':
        self.offset_days = 0
      elif keys == b'\b':
        self.page = 'timer'
      else:
        days_changed = False
        
      if days_changed:
        #self.wavplay_click()        
        self.update_shifted_day()
        
      if keys == b'r':
        self.get_tide(self.shifted_day)
      
      if keys == b't':
        self.tide_front = not self.tide_front

      if keys == b'q':
        print('quit')
        break
      
      if keys == b'c':
        cstr = '<{:04d}-{:02d}-{:02d} {}>'.format(self.year, self.shifted_day.month, self.shifted_day.day, self.week_list2[self.shifted_day.weekday()])
        #print(cstr)
        pdeck.clipboard_copy(cstr)
        self.message = 'Date copied to clipboard.'
        self.message_life = 100

      self.key_event = True
      

el = elib.esclib()

def main(vs, args):
  v = vs.v
  v.print(el.erase_screen())
  #v.print(el.display_mode(False))
  v.print(el.home())

  v.unsubscribe_callback()
  clock = analog_clock(v, vs)
  
  v.callback(clock.update)
  clock.keyevent_loop()
  v.print(el.display_mode(True))
  print("finished.", file=vs)
  v.callback(None)
    

  
