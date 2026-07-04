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
import anm
from wav_loader import load_wav

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
#  "60*60*tz" : 60*15*pdeck_utils.timezone,
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
    self.anim = anm.anm_object(100,
    { 'minute': [anm.ease_out, 0,0]})
    self.anim.goal = 0

    # Timer dial range.  This is "minutes per one full D-pad cycle".
    # It can be changed with the slider.
    self.range_options = (12, 24, 30, 60)
    self.range_index = 1
    self.range_minutes = self.range_options[self.range_index]
    self.range_anim = anm.anm_object(100,
    { 'range_minutes': [anm.ease_out, self.range_minutes, self.range_minutes]})
    self.range_anim.goal = self.range_minutes
    self.last_slider_range_index = self.range_index
    

class analog_clock:
  def __init__(self,v, vs, sampler):
    self.key_event = False
    self.seq = anm.anm_sequencer()
    self.sampler = sampler
    self.tide_chart = None
    self.message = ''
    self.message_life = 0
    self.du = dsp_utils()
    self.v = v
    self.slider_start = 0xff
    self.vs = vs
    self.size = 100
    self.seconds_m_size = (85,95)
    self.hourhand_size = 60
    self.minutehand_size = 80
    self.number_size = 75
    self.secondhand_size = 90
    self.offset = (110,125)
    self.offset_days = 0
    self.coffset = (300,40)
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
    self.catimage.append(xbmreader.read_xbmr("/sd/lib/data/cat1.xbmr"))
    self.catimage.append(xbmreader.read_xbmr("/sd/lib/data/cat2.xbmr"))
    self.catimage.append(xbmreader.read_xbmr("/sd/lib/data/cat3.xbmr"))
    self.catimage.append(xbmreader.read_xbmr("/sd/lib/data/cat4.xbmr"))
    self.cat_anm_goal = 0
    self.cat_anm_ct = 0
    self.cat_x = 0
    self.setup_filled_arc()
    #self.last_us=0
    self.page = 'clock'
    self.kt = ktimer()
    self.seq.register('timer_hand', self.kt.anim)
    self.seq.register('timer_range', self.kt.range_anim)
    self.wavbuf = array.array('h',bytearray(0x10000))
    phase = 0
    for i in range(0x4000):
      if i&0x1000 == 0:
        self.wavbuf[i] = int(self.du.sin(phase)*(10000-(i&0xfff)*2))
        phase += 0.3
        if phase > twopi: phase -= twopi
    
    data, ch = load_wav('/sd/lib/data/click2.wav', sample_rate=16000, channels=2)
    self.wavbuf_click = data
    self.sampler.set_sample(0, self.wavbuf)
    self.sampler.set_sample(1, self.wavbuf_click)
    self.sampler.volume(1, 0.8)
    self.op_second = None
      
  def pub_set_timer(self, minute):
    self.wavplay_click()
    org_minute = self.kt.minute
    self.kt.minute = minute
    self.kt.second = 0
    self.kt.anim = anm.anm_object(min(20*org_minute,600),
      { 'minute' : [ anm.ease_out, self.kt.anim.minute, self.kt.minute ]})
    self.kt.anim.goal = self.kt.minute
    self.seq.register('timer_hand', self.kt.anim)
    self.kt.second_past = 0
    self.kt.starttime = time.ticks_ms()
    self.kt.org_minute = self.kt.minute
    self.kt.org_second = self.kt.second
    self.kt.stat = KT_RUNNING
    self.page = 'timer'
    if self.vs is not None:
      self.vs.record_event('set_timer %d min' % minute)

  def wavplay_alarm(self):
    self.sampler.play(0)
    
  def wavplay_click(self):
    self.sampler.play(1)


  def draw_oneline_help(self):
    self.v.set_draw_color(1)
    self.v.set_font('u8g2_font_profont15_mf')
    help_copy_str = 'C - Copy date, BS or B button - Toggle Timer'
    help_copy_str2 = 'arrow keys: move date in calendar'
    copy_str_width = self.v.get_str_width(help_copy_str) + 1
    copy_str_width2 = self.v.get_str_width(help_copy_str2) + 1
    self.v.draw_str(pdeck.get_screen_size()[0] - copy_str_width, self.coffset[1] + 195,help_copy_str)
    self.v.draw_str(pdeck.get_screen_size()[0] - copy_str_width2, self.coffset[1] + 180,help_copy_str2)

        
  def update(self,e):
    if not self.v.active:
      self.v.finished()
      return

    self.update_time()
    
    if self.last_day != self.day:
      self.last_day = self.day
      self.get_tide(self.shifted_day)
    
    #self.draw_edge()
    self.update_timer()
    
    if False and not e and self.cat_anm_ct >= 12 and not self.key_event and not self.kt.touched and self.last_second == self.second:

      if self.message_life > 0:
        self.message_life -= 1
    
      self.v.finished()
      return

    
    self.seq.update(time.ticks_ms())
    self.last_second = self.second
    #self.draw_secondhand()
    #return

    if self.page == 'timer':
      self.draw_timer_remaining_disc()
      self.draw_timer_measure()
      self.draw_timer_numbers()
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
      
      self.draw_oneline_help()

      
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

  def set_timer_range(self, index):
    kt = self.kt
    if index < 0:
      index = 0
    if index > 3:
      index = 3
    if index >= len(kt.range_options):
      index = len(kt.range_options) - 1
    if index == kt.range_index:
      return

    old_range = kt.range_anim.range_minutes
    kt.range_index = index
    kt.range_minutes = kt.range_options[index]

    # Seamless zoom-style range animation: start from the current animated
    # range, not from the old goal, so slider changes during animation do not
    # cause a visual snap.
    kt.range_anim = anm.anm_object(450,
    { 'range_minutes' : [ anm.ease_in_out, old_range, kt.range_minutes ]})
    kt.range_anim.goal = kt.range_minutes
    self.seq.register('timer_range', kt.range_anim)
    #self.message = 'Timer range: {} min / cycle'.format(kt.range_minutes)
    #self.message_life = 55
    self.wavplay_click()
    self.key_event = True

  def update_timer_range_from_slider(self, slider):
    if slider == 0xff:
      self.slider_start = 0xff
      return
      
    if self.slider_start == 0xff:
      self.slider_start = slider
    index = 0    
    if slider - self.slider_start > 10:
      index = 1
      self.slider_start +=10
    if slider - self.slider_start < -10:
      index = -1
      self.slider_start -=10

    if index != 0:
      self.set_timer_range(self.kt.range_index+index)

  def update_timer(self):
    kt = self.kt
    if kt.stat == KT_ALARM:
      if not self.sampler.is_playing(0):
        self.wavplay_alarm()

    if kt.stat == KT_RUNNING and not kt.touched:
      curtime = time.ticks_ms()
      kt.second_past = int(((curtime - kt.starttime) / (1000)))
      kt.minute = int(kt.org_minute + (kt.org_second / 60)- (self.kt.second_past / 60))
      kt.second = int(kt.org_second - (self.kt.second_past %60))

      if kt.minute != kt.anim.goal:
        kt.anim = anm.anm_object(0,
        { 'minute' : [ anm.ease_out, kt.anim.minute, kt.minute ]})
        kt.anim.goal = kt.minute
        self.seq.register('timer_hand', kt.anim)


      if kt.second < 0:
        kt.second += 60
      if kt.minute < 0 or (kt.minute == 0 and kt.second == 0):
        kt.minute = 0
        kt.second = 0
        kt.stat = KT_ALARM
        self.wavplay_alarm()
        self.vs.record_event('Timer triggered')
        
    if not self.v.active:
      return
          
    input = self.v.get_tp_keys()
    if not input:
      return

    # Slider changes timer scale/range.  It works while the timer app is open
    # so the clock screen does not accidentally change the kitchen-timer range.
    if self.page == 'timer':
      self.update_timer_range_from_slider(input[0])

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
        kt.org_minute = kt.minute
        kt.last_dial = dial
        kt.cycles = 0
        kt.minute_base = kt.minute
        kt.stat = KT_STOP
        kt.second = 0
      kt.touched = True

    if kt.touched:
      if dial - kt.last_dial < -120:
        kt.cycles += 1
      if dial - kt.last_dial > 120:
        kt.cycles -= 1
      dial_distance = dial - kt.dial_base + kt.cycles*160
        
      kt.last_dial = dial
      last_minute = kt.minute

      # One D-pad cycle is 160 units.  Make "minutes per cycle" selectable.
      minute_per_dial_unit = kt.range_minutes / 160.0
      kt.minute = kt.org_minute + int(dial_distance * minute_per_dial_unit)
      
      if kt.minute < 0:
        kt.minute = 0
      if kt.anim.goal != kt.minute:
        #print(kt.anim.props['minute'])
        self.seq.update(time.ticks_ms())
        skip_to = kt.anim.get_time() if kt.anim.get_time()< 1.0 else 0.0
        kt.anim = anm.anm_object(550,
        {'minute' : [anm.ease_out, kt.anim.minute,kt.minute ]})
        kt.anim.goal = kt.minute
        self.seq.register('timer_hand', kt.anim, seek_to = skip_to)
      
      if last_minute != kt.minute:
        #kt.dial_base = dial
        self.wavplay_click()
      
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
      if random.randint(0,50) == 0:
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
      if i < len(self.tide_chart):
        pix_height = int(self.tide_chart[i] * 10)
      else:
        pix_height = 0
      #if pix_height < 0:
      #  pix_height == 0
      #print(f'hello {i},{len(self.tide_chart)}:{self.tide_chart[i]} , {pix_height}')
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
      else:
        num = str(i)
      extra = 3 if len(num) == 2 else -1
      
      self.v.set_font_mode(1)
      self.v.draw_str(x-3-extra,y+6, num)
      self.v.draw_str(x-3-extra+1,y+6, num)
      self.v.set_font_mode(0)

  def draw_timer_numbers(self):
    kt = self.kt
    rng = kt.range_anim.range_minutes
    if rng <= 0:
      rng = kt.range_minutes

    # Draw a readable set of major labels.  The angle is computed from the
    # animated range, so changing 12/24/30/60 behaves like smooth zoom.
    if kt.range_minutes <= 12:
      step = 1
    elif kt.range_minutes <= 30:
      step = 5
    else:
      step = 10

    self.v.set_font("u8g2_font_profont15_mf")
    label = 0
    while label < kt.range_minutes:
      angle = (label / rng) * twopi - dc["0.5 * 3.1415926536"]
      x = self.du.cos(angle) * self.number_size
      y = self.du.sin(angle) * self.number_size
      x += self.offset[0]
      y += self.offset[1]
      x = int(x)
      y = int(y)
      num = str(label if label != 0 else kt.range_minutes)
      extra = 3 if len(num) == 2 else -1
      self.v.set_font_mode(1)
      self.v.draw_str(x-3-extra,y+6, num)
      #if int(num) == kt.range_minutes:
      self.v.draw_str(x-3-extra+1,y+6, num)
      self.v.set_font_mode(0)
      
      label += step

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
    self.v.set_font("u8g2_font_profont15_mf")
    self.v.draw_str(self.coffset[0] - 60, self.offset[1] + 30, 'Rotate your finger')
    self.v.draw_str(self.coffset[0] - 60, self.offset[1] + 30 + 16, 'on D-pad to set time')
    self.v.draw_str(self.coffset[0] - 60, self.offset[1] + 30 + 32, 'Slider: {} min/cycle'.format(self.kt.range_minutes))


  def setup_filled_arc(self):

    radius = 52
    seg_count = 60
    start_angle = 0
    end_angle = twopi
    span = end_angle - start_angle
    
    if span > twopi:
      span = twopi
      end_angle = start_angle + span
    cx = self.offset[0]
    cy = self.offset[1]
    points = array.array('h',[0,0,0,0,0,0]*60)

    for i in range(seg_count):
      a0 = start_angle + span * i / seg_count
      a1 = start_angle + span * (i + 1) / seg_count
      x0, y0 = self.rotate_pos(0, -radius, a0)
      x1, y1 = self.rotate_pos(0, -radius, a1)
      offset = i*6
      points[offset + 0] = cx
      points[offset + 1] = int(cx + x0)
      points[offset + 2] = int(cx + x1)
      points[offset + 3] = cy
      points[offset + 4] = int(cy + y0)
      points[offset + 5] = int(cy + y1)
      #self.v.draw_polygon(points)
    self.arc_points = points
    self.mv_arc_points = memoryview(points)


  def draw_filled_arc_disc(self, start_angle, end_angle, radius, dither):
    if radius <= 0:
      return
    if end_angle <= start_angle:
      return

    span = end_angle - start_angle
    if span > twopi:
      span = twopi
      end_angle = start_angle + span

    seg_count = int(60 * span / twopi) + 1
    if seg_count < 1:
      seg_count = 1
    if span < twopi and seg_count < 2:
      seg_count = 2

    self.v.set_draw_color(1)
    self.v.set_dither(dither)
    for i in range(seg_count):
      self.v.draw_polygon(self.mv_arc_points[i*6:(i+1)*6])

    self.v.set_dither(16)

  def draw_timer_remaining_disc(self):
    kt = self.kt
    rng = kt.range_anim.range_minutes
    if rng <= 0:
      rng = kt.range_minutes
    if rng <= 0:
      return

    minute = kt.anim.minute
    second = kt.second
    remain = minute + second * dc["1/60"]
    if remain <= 0:
      return

    radius = 52

    # For one turn, draw one normal pie slice.  For multiple turns, draw
    # overlapping slices with different dithers:
    #   1st turn: light full/partial arc
    #   2nd turn: stronger arc over it
    #   3rd turn: strongest arc over it
    # More than three turns is intentionally ignored/capped.
    if remain <= rng:
      end_angle = remain * dc["pi * 2"] / rng
      self.draw_filled_arc_disc(0, end_angle, radius, 4)
      self.v.set_dither(16)
      self.v.set_draw_color(1)
      return

    max_remain = rng * 3
    if remain > max_remain:
      remain = max_remain

    dithers = (4, 8, 12)
    layer = 0
    while layer < 3:
      part = remain - rng * layer
      if part <= 0:
        break
      if part > rng:
        part = rng

      end_angle = part * dc["pi * 2"] / rng
      self.draw_filled_arc_disc(0, end_angle, radius, dithers[layer])
      layer += 1

    self.v.set_dither(16)
    self.v.set_draw_color(1)
    

  def draw_timerhand(self):
    minute = self.kt.anim.minute
    second = self.kt.second
    h = minute + second * dc["1/60"]
    rng = self.kt.range_anim.range_minutes
    if rng <= 0:
      rng = self.kt.range_minutes
    angle = h * dc["pi * 2"] / rng
  
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
    if self.op_second == None:
      self.op_second = self.second
    speed = 0
    if self.op_second - self.second > 30:
      self.op_second -= 60
    # preventing jumping when the app resumes
    if abs(self.op_second - self.second) > 1.1:
      self.op_second = self.second
      
    if self.op_second > self.second:
      speed = (self.op_second - self.second) / 3
      if speed < 0.03:
        speed = 0
        self.op_second = self.second
      elif speed < 0.1: speed = 0.1
      speed = - speed
    if self.op_second < self.second:
      speed = (self.second - self.op_second) / 1.3      
      #print(f'{speed}')
      if speed < 0.03:
        speed = 0
        self.op_second = self.second
      elif speed < 0.4: speed = 0.4
    self.op_second += speed

    h = self.op_second + self.micro * 0.000001
    
    angle = h * dc["pi * 2 / 60"]
    
    point_pair = ( \
      ( -3, 3 ), \
      ( 2,  3 ), \
      ( 0, -self.secondhand_size ))
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

  def draw_timer_measure(self):
    kt = self.kt
    rng = kt.range_anim.range_minutes
    if rng <= 0:
      rng = kt.range_minutes

    # Show one tick per minute for 12/24/30, and one tick per 2 minutes for
    # 60 so the dial stays readable.
    if kt.range_minutes <= 30:
      tick_count = kt.range_minutes
      tick_step = 1
    else:
      tick_count = 30
      tick_step = 2

    for i in range(tick_count):
      minute_mark = i * tick_step
      angle = minute_mark * dc["pi * 2"] / rng
      size1 = self.seconds_m_size[0]
      if minute_mark % 5 == 0:
        size1 -= 4
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
    if len(self.tide_chart) < 170:
      print("Tide chart data error")
      self.tide_chart = []
      return
    #print(self.tide_chart)

  def update_time(self):
    ctime = time.gmtime(time.time() + 60*15*pdeck_utils.timezone)
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
            org_minute = self.kt.minute
            self.kt.minute = 0
            self.kt.second = 0
            self.kt.anim = anm.anm_object(min(20*org_minute,600),
            { 'minute' : [ anm.ease_out, self.kt.anim.minute, self.kt.minute ]})
            self.kt.anim.goal = self.kt.minute
            self.seq.register('timer_hand', self.kt.anim)
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
  v.print(el.home())
  v.print(el.display_mode(False))

  sampler = audio.sampler(2)
  with sampler:
    clock = analog_clock(v, vs, sampler)
    vs.register_module(clock)
    v.callback(clock.update)
    clock.keyevent_loop()
  
  v.print(el.display_mode(True))
  print("finished.", file=vs)
  v.callback(None)
