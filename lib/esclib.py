#
# Escape sequence lib
# Copyright Nunomo LLC.
# MIT license
#

class esclib:
  def erase_screen(self):
    return "\x1b[2J"
  def home(self):
    return "\x1b[H"
  def erase_to_end_of_current_line(self):
    return "\x1b[K"
  def cur_up(self,num = 1):
    if num == 1:
      return "\x1b[A"
    else:
      return f"\x1b[{num}A"
  def cur_down(self,num = 1):
    if num == 1:
      return "\x1b[B"
    else:
      return f"\x1b[{num}B"
  def cur_left(self,num = 1):
    if num == 1:
      return "\x1b[D"
    else:
      return f"\x1b[{num}D"
  def cur_right(self,num = 1):
    if num == 1:
      return "\x1b[C"
    else:
      return f"\x1b[{num}C"
  def raw_mode(self, mode):
    if mode == True:
      return "\x1b[?1h";
    else:
      return "\x1b[?1l";
  def cursor_mode(self, mode):
    if mode == True:
      return "\x1b[?25h";
    else:
      return "\x1b[?25l";
  def wraparound_mode(self, mode):
    if mode == True:
      return "\x1b[?7h";
    else:
      return "\x1b[?7l";
  #Enable / disable text drawing
  def display_mode(self, mode):
    if mode == True:
      #Enabling display
      return "\x1b[?5000h";
    else:
      #Disabling display
      return "\x1b[?5000l";
  def move_cursor(self, x, y):
    return f"\x1b[{x};{y}H"
  def set_font_color(self, color):
    return f"\x1b[{color}m"
  def reset_font_color(self):
    return f"\x1b[39m"

