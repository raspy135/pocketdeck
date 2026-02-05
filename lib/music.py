import os
import time
import pdeck
import pdeck_utils as pu
import audio
import esclib as elib
import wav_play
import menu_ui

MUSIC_ROOT = "/sd/music"

# Key codes (same escape sequences you already handle)
KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_RIGHT = b'\x1b[C'
KEY_LEFT = b'\x1b[D'
KEY_ENTER = b'\x0d'
KEY_BS = b'\b'



class MusicGUI:
  def __init__(self, v, vs):
    self.v = v
    self.vs = vs

    # UI state
    #self.mode = "albums"  # "albums" or "tracks"

    # Playback
    self.wp = wav_play.wav_play(20000)  # same as ref 2
    self.playing = False
    self.paused = False

    self.current_tick = 0

    self.message = ""
    self.message_life = 0
    self.menu_list = []
    self.load_albums()
  
    self.menu_ui = menu_ui.menu_ui(vs, self.menu_list)
    
    

  # -------- Data loading ----------
  def load_albums(self):
    try:
      items = os.listdir(MUSIC_ROOT)
    except Exception as e:
      self.message = "Missing /sd/music"
      self.message_life = 120
      return

    albums = []
    for name in items:
      p = MUSIC_ROOT + "/" + name
      st = os.stat(p)
      if st[0]&0x4000 != 0:
        albums.append(name)

    albums.sort(key=lambda s: s.lower())
    for name in albums:
      self.menu_list.append([name, None ])
    self.scroll_top = 0

  def load_tracks(self, album):
    folder = MUSIC_ROOT + "/" + album
    items = os.listdir(folder)
    # Filter common audio extensions; adjust if your wav_play supports more
    tracks = [x for x in items if x.lower().endswith(".wav")]
    tracks.sort(key=lambda s: s.lower())
    menu_items = []
    for item in tracks:
      menu_items.append([item, 
      {'filename': item,
       'type' : 'str'
        }])
    return menu_items

  # -------- Playback ----------
  def current_track_path(self, track):
    return MUSIC_ROOT + "/" + self.current_album + "/" + track

  def stop(self):
    try:
      self.wp.stop()
      self.wp.close()
    except:
      pass
    self.playing = False
    self.paused = False

  def play_selected(self):
    filename = self.menu_ui.get_current_item()[1]['filename']
    path = self.current_track_path(filename)
    self.stop()
    try:
      self.wp.open(path)
      self.wp.play()
      self.playing = True
      self.paused = False
      #self.message = "Playing"
      #self.message_life = 40
    except Exception as e:
      print(path)
      print(e)
      self.message = "Play error"
      self.message_life = 120
      self.playing = False

  def toggle_pause(self):
    if not self.playing:
      self.play_selected()
      return
    self.stop()
    self.paused = True
    self.message = "Stopped"
    self.message_life = 40

  def next_track(self):
    ret = self.menu_ui.move_cursor(1)
    self.play_selected()

  def prev_track(self):
    ret = self.menu_ui.move_cursor(-1)
    self.play_selected()


  def draw_header(self):
    self.v.set_draw_color(0)
    self.v.draw_box(0,0,400,40)
    self.v.set_draw_color(1)
    
    self.v.set_font('u8g2_font_profont22_mf')
    self.v.set_draw_color(1)
    title = "Music / "
    title += "Albums" if self.menu_ui.depth == 0 else ""

    if self.menu_ui.depth == 1 and self.current_album:
      #self.v.draw_str(110, 24, self.current_album)
      title = title + self.current_album
    self.v.draw_str(50, 24, title)

    self.v.set_font('u8g2_font_profont15_mf')
    # small help
    self.v.set_draw_color(0)
    self.v.draw_box(0,220,400,20)
    self.v.set_draw_color(1)
    self.v.draw_str(10, 238, "Enter: select/play  <-:back  q:quit  Arrows:navigate")


  def draw_play_animation(self, x, y):
    if self.playing:
      pos = ((self.current_tick // 1000) % 1000) // 40
      self.v.draw_box(4, 4, pos, 25)
      self.v.draw_box(8 + pos, 4, 25 - pos, 25)
    else:
      self.v.draw_box(4, 4, 25, 25)

  def draw_message(self):
    if self.message_life <= 0:
      return
    self.v.set_font('u8g2_font_tenfatguys_tf')
    #'u8g2_font_profont15_mf')
    self.v.set_dither(16)
    w = self.v.get_str_width(self.message) + 20
    self.v.draw_box(200, 200, w, 22)
    self.v.set_dither(16)
    self.v.set_draw_color(0)
    self.v.draw_str(210, 216, self.message)
    self.v.set_draw_color(1)
    self.message_life -= 1

  def draw_playbar(self):
    if not self.playing:
      return
    pos, total = self.wp.get_position()
    self.v.set_dither(3)
    self.v.draw_box(10,100,15,100)
    self.v.set_dither(16)
    progress = pos * 100 // total 
    x = 17
    y = progress + 100
    self.v.set_draw_color(0)
    self.v.draw_disc(x,y,8,0xf)
    self.v.set_draw_color(1)
    self.v.draw_circle(x,y,8,0xf)
    self.v.draw_circle(x,y,9,0xf)

  # -------- Frame update callback ----------
  def update(self, screen_change_requested):
    if not self.v.active:
      self.v.finished()
      return

    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = (self.current_tick - self.last_tick)

    self.menu_ui.draw_menu(offset=50)
    self.draw_header()
    self.draw_play_animation(0, 0)
    self.menu_ui.draw_cursor(self.time_diff, offset=50)
    self.draw_playbar()
    self.draw_message()

    self.v.finished()

  # -------- Input handling ----------
  def read_key(self):
    ret = self.v.read_nb(1)
    if not ret or ret[0] <= 0:
      return None
    k = ret[1].encode('ascii')
    if k == b'\x1b':
      # parse escape sequence like your existing apps
      seq = [k]
      seq.append(self.vs.read(1).encode('ascii'))
      if seq[-1] == b'[':
        seq.append(self.vs.read(1).encode('ascii'))
        if seq[-1] >= b'0' and seq[-1] <= b'9':
          seq.append(self.vs.read(1).encode('ascii'))
      return b"".join(seq)
    return k

  def handle_key(self, k):
    if k is None:
      return True

    if k == b'q':
      return False

    if k == KEY_DOWN:
      self.menu_ui.move_cursor(1)
    elif k == KEY_UP:
      self.menu_ui.move_cursor(-1)
    if k == KEY_BS:
      if self.menu_ui.depth == 0:
        return False
      self.stop()      
      self.menu_ui.change_font("u8g2_font_profont29_mf",30)
      self.menu_ui.goup_item()
    elif k == KEY_RIGHT:
      if self.menu_ui.depth == 1:
        self.next_track()
    elif k == KEY_LEFT:
      if self.menu_ui.depth == 1:
        self.prev_track()
      
    elif k == KEY_ENTER:
      item = self.menu_ui.get_current_item()[1]
      if item == None:
        track_menu = self.load_tracks(self.menu_ui.get_current_item()[0])
        #print(track_menu)
        self.menu_ui.menu_list[self.menu_ui.y[0]][1] = track_menu
        #print(self.menu_ui.menu_list)
        item = self.menu_ui.get_current_item()[1]
      if isinstance(item,list):
        self.menu_ui.change_font('u8g2_font_profont15_mf',16)
        self.current_album = self.menu_ui.get_current_item()[0]
        self.menu_ui.select_item()
      if isinstance(item,dict):        
        self.play_selected()

    return True

  def loop(self):
    # main input loop; callback handles drawing
    while True:
      # if track finishes, auto-advance
      if self.playing and not audio.stream_play():
        # end reached
        self.playing = False
        if self.menu_ui.depth == 1:
          if self.menu_ui.get_cursor_pos() < self.menu_ui.get_current_list_len():
            self.menu_ui.move_cursor(1)
            self.play_selected()

      k = self.read_key()
      if not self.handle_key(k):
        break

      pdeck.delay_tick(8)

    self.stop()

def main(vs, args):
  v = vs.v

  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  gui = MusicGUI(v, vs)
  v.callback(gui.update)  # GUI render callback (ref 0)
  gui.loop()
  v.callback(None)
  v.print(el.display_mode(True))
  print("finished.", file=vs)

