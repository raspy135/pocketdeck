#
# Pem -- A editor for pocket deck
# Copyright Nunomo LLC
# MIT license

# For standard Linux system, turn off this flag
pdeck_enabled = True

import re
if pdeck_enabled:
  import pdeck
else:
  import termios
  import sys

import os
import time
import esclib as elib
import argparse
import array
import jp_input
import ls

el = elib.esclib()

IM_EN = const(1)
IM_JP = const(2)

import benchmark
bm = benchmark.benchmark(False)

def _basename(p):
    if p.endswith("/") and p != "/":
        p = p[:-1]
    i = p.rfind("/")
    return p if i < 0 else p[i + 1 :]

def _dirname(p):
    if p.endswith("/") and p != "/":
        p = p[:-1]
    i = p.rfind("/")
    if i < 0:
        return "."
    return p[:i] or "/"


class editor:
  def __init__(self,v):
    # enum
    self.MODE_NORMAL = 0
    self.MODE_SEARCH = 1
    self.MODE_SELECT_DIALOG = 2
    self.MODE_INPUT_LINE_DIALOG = 3
    self.MODE_REPLACE = 4
    self.IM_EN = 1
    self.IM_JP = 2
    self.h_diff = 1
    self.v = v
    self.mode = self.MODE_NORMAL
    self.text_width, self.text_height = v.get_terminal_size()
    self.yankbuf = yank_buffer()
    self.text_height -= 1
    self.adding_yank = False
    self.search_info = search_info()
    self.status_message =""
    self.status_message_life = 0
    self.file_list = []
    self.input_answer_list = None
    self.dmod = True
    # For select dialog
    self.sd_info = None

    # For input line dialog
    self.sl_info = None
    
    # file_row and col indicates cursor
    #  positon in file (not screen)
    self.file_row = 0
    self.file_col = 0

    # scroll_row and col indicates scroll
    # position. row is file row #, col is screen col shift
    self.scroll_row = 0
    self.scroll_col = 0

    # cursor position on display
    self.d_row = 0
    self.d_col = 0
    self.wished_d_col = 0 # screen col wanted (but it was not possible because it's more than the line length)

    # line number informaton on display [linenum, start_col]
    self.line_num_list = []
    self.tab_size = 2
    self.jpfont_loaded = False

  def load_jpfont(self):
    import fontloader
    #fontname = 'font_unifont_japanese3'
    fontname = 'unifont_large'
    fontloader.load(fontname)
  
    font = fontloader.font_list[fontname]
    self.v.v.set_terminal_font(font,font,8,16)
    self.jpfont_loaded = True

  def exit(self):
    self.v.print(el.raw_mode(False))
    #self.v.print(el.wraparound_mode(False))
    
  def open(self, filename):
    self.file = editor_file(self.v, filename, self.text_height, self.text_width - 1, self.tab_size)
    self.v.background_update=self.file.background_update

  def setup_screen(self):
    self.v.set_raw_mode(True)
    #self.v.print(el.wraparound_mode(False))
    self.v.print(el.erase_screen())    

  
  def render_main_text(self, dry_run = False):
    # When dry_run is True, it won't print chars
    # It's useful to update list_num_list and d_row,d_col
    self.line_num_list = self.file.file_refresh_screen(self.scroll_row, self.scroll_col, self.file_row, self.file_col, dry_run)

  def update_d_cursor(self):
    #figure out cursor position
    file_row = self.file_row
    file_col = self.file_col
    if self.file.im_session:
      file_col += self.file.im_session.col
    #print(f'row,col={file_row},{file_col}')
    llen = len(self.line_num_list)
    for num in self.line_num_list:
      
      if num[1] == file_row:
        d_cur_row = num[0]
        row = self.file.rows[num[1]]
        # Not the end of the screen
        if num[0]+1 < llen:
          # Next line is different row
          cond = self.line_num_list[num[0]+1][1] != file_row
        else:
          cond = True
        if row.expanded_to_pos(num[2],self.file.w) == file_col and cond:
          self.d_row = d_cur_row
          self.d_col = row.cpos_to_dpos(file_col, True) - row.cpos_to_dpos(num[2]) #row.expand(num[2], file_col)
          #print("cursor2 {},{}".format(self.d_row+1, self.d_col+1))
          break
        
        maybe_d_col = row.cpos_to_dpos(file_col, True) - row.cpos_to_dpos(num[2])
        
        if num[0]+1 < llen:
          if self.line_num_list[num[0]+1][1] == num[1] and file_col == self.line_num_list[num[0] + 1][2]:
            self.d_row = d_cur_row + 1
            self.d_col = 0
            break

        if self.file.w > maybe_d_col:
          self.d_row = d_cur_row
          self.d_col = maybe_d_col #row.expand(num[2], file_col)
          #print("cursor {},{}".format(self.d_row+1, self.d_col+1))
          break

  def print_input_line_dialog(self):
    self.v.print(el.set_font_color(7)) #invert
    title = f"  ** {self.sl_info.subject} ** "
    self.v.print(title + " "*(self.text_width - len(title)))
    self.v.print("\r\n")
    self.v.print(el.set_font_color(0))
    
    self.v.print(f"{self.sl_info.header}: {self.sl_info.line.decode()}")
    self.v.print(el.erase_to_end_of_current_line())



  def print_select_dialog(self):
    self.v.print(el.set_font_color(7)) #invert
    title = f"  ** {self.sd_info.subject} ** "
    self.v.print(title + " "*(self.text_width - len(title)))
    self.v.print("\r\n")
    
    b_list = self.sd_info.slist[self.sd_info.scroll:]
    
    self.v.print(el.move_cursor(self.text_height +2,1))
    #print(f"bufs {b_list}")
    for i in range(0,self.sd_info.height):
      if i >= len(b_list):
        self.v.print("~")
        self.v.print(el.erase_to_end_of_current_line())
      else:
        buf=b_list[i]
        if(i == self.sd_info.cur):
          self.v.print(el.set_font_color(7)) #invert
        else:
          self.v.print(el.set_font_color(0))
        self.v.print(f"{i+self.sd_info.scroll+1} :")
        self.v.print(el.set_font_color(0))
        self.v.print(" {}".format(buf[:self.text_width].replace('\n',' ')))
        self.v.print(el.erase_to_end_of_current_line())
      if i != self.sd_info.height - 1:
        self.v.print("\r\n")


  def refresh_screen(self):
    bm.start_bench()

    self.v.print(el.cursor_mode(False)) #hide cursor
    if self.dmod:
      self.render_main_text()
      self.dmod = False
    #else:
    #  print("no update")
    bm.add_bench('render')
    self.update_d_cursor()
    bm.add_bench('update_d')
    #status bar
    self.v.print(el.move_cursor(self.text_height + 1, 1))

    if self.status_message_life > 0:
      self.v.print(" [ ")
      self.v.print(self.status_message)
      self.v.print(" ] ")
      self.status_message_life -= 1
    else:
      if self.mode == self.MODE_NORMAL:
        stbout = []
        stbout.append((el.set_font_color(7))) #invert
        filename = self.file.filename
        if filename == None:
          filename = '** New file **'
        if len(filename) > 20:
          filename = filename[:20]
        filestat = f"{filename} {'*' if self.file.modified else '-'} L:{self.file_row+1}/{len(self.file.rows)} C:{self.file_col+1}"
        filestat_left = f"Mode:{'EN' if self.file.input_method == self.IM_EN else 'JP'},{self.file.mode}"
        statline = filestat + " " * (self.text_width - len(filestat) - len(filestat_left)) + filestat_left
        #self.v.print(statline)
        stbout.append(statline)
        self.v.print(''.join(stbout))
      if self.mode == self.MODE_SEARCH:
        searchstat = f"Search: {self.search_info.query_str}"
        if self.search_info.matched_query == None:
          searchstat += " : Not found"
        statline = searchstat + " " * (self.text_width - len(searchstat))
        self.v.print(statline)

      if self.sd_info: #mode == self.MODE_SELECT_DIALOG:
        self.print_select_dialog()
      if self.sl_info: #mode == self.MODE_INPUT_LINE_DIALOG:
        self.print_input_line_dialog()

    if self.mode == self.MODE_INPUT_LINE_DIALOG:
      # Position cursor at the end of input or current cursor position in input
      prompt_len = len(self.sl_info.header) + 2
      self.v.print(el.move_cursor(self.text_height + 2, prompt_len + self.sl_info.cur + 1))
    else:
      self.v.print(el.reset_font_color() + el.move_cursor(self.d_row +1, self.d_col + 1))



    #if (self.mode == self.MODE_REPLACE or self.mode == self.MODE_SEARCH) and 
    if self.search_info.matched_query != None:
      out = el.set_font_color(4) #underline
      offset = len(self.search_info.matched_query) + self.d_col - self.file.w
      #print(f"offset {offset}")
      if  offset > 0:
        out += self.search_info.matched_query[:-offset]
        out += "\r\n"
        out += self.search_info.matched_query[-offset:]
      else:
        out += self.search_info.matched_query
      out += el.move_cursor(self.d_row +1, self.d_col + 1)
      #out += el.cur_left(len(self.search_info.matched_query))
      out += el.reset_font_color()
      self.v.print(out)
    self.v.print(el.cursor_mode(True)) #show cursor at the very end
    bm.add_bench('status bar')
    bm.print_bench()

  def cursor_move(self, row, col):
    if row < 0:
      request_col = self.wished_d_col if self.wished_d_col != -1 else self.d_col
      filepos = self.file.scr_to_filepos(self.file.h, self.file.w, self.d_row - 1, request_col)
      #print(f"filepos {filepos}")
      
      if filepos:
        self.file_row = filepos[0]        
        self.file_col = filepos[1]
        rlen = self.file.rows[self.file_row].len
        if self.file_col >= rlen:
          self.file_col = rlen
          if self.wished_d_col == -1:
            self.wished_d_col = self.d_col
      row += 1
    if row > 0:
      request_col = self.wished_d_col if self.wished_d_col != -1 else self.d_col
      # print(f' Req: {request_col}')
      filepos = self.file.scr_to_filepos(self.file.h, self.file.w, self.d_row + 1, request_col)
      if filepos:
        self.file_row = filepos[0]        
        self.file_col = filepos[1]
        rlen = self.file.rows[self.file_row].len
        if self.file_col >= rlen:
          self.file_col = rlen
          if self.wished_d_col == -1:
            self.wished_d_col = self.d_col
            #print(f'wished_d_col {self.wished_d_col}')
      row -= 1
    if col < 0:
      self.wished_d_col = -1
      nextcol = self.file_col - 1
      if nextcol == -1:
        if self.file_row > 0:
          self.file_row -= 1
          self.file_col = self.file.rows[self.file_row].len
      else:
        self.file_col = nextcol
      col += 1
    if col > 0:
      self.wished_d_col = -1
      nextcol = self.file_col + 1
      if nextcol == self.file.rows[self.file_row].len + 1:
        if self.file_row < len(self.file.rows) - 1:
          self.file_row += 1
          self.file_col = 0
      else:
        self.file_col = nextcol
      col -= 1

    self.update_scroll_for_curmove()
    if row != 0 or col != 0:
      self.cursor_move(row,col)

  def update_scroll_for_curmove(self, offset = 0):
    file_col = self.file_col + offset
    range = self.file.in_screen(self.file_row,file_col)
    if range == -1:
      self.dmod = True
      #self.scroll_row -= 1
      lnl = self.file.gen_line_num_list(self.line_num_list[0][1],self.line_num_list[0][2], -1,0)
      self.scroll_row = lnl[0][1]
      self.scroll_col = lnl[0][2]
      
    if range == 1:
      self.dmod = True
      #self.scroll_row += 1
      lnl = self.line_num_list
      self.scroll_row = lnl[1][1]
      self.scroll_col = lnl[1][2]
      #print(lnl)

      
  def match_parenthesis(self, r_in, c_in):
    p_close = bytes(self.file.rows[r_in].at(c_in))
    pairs = { b"}": b"{" ,b"]": b"[" ,b")": b"("   }
    if p_close not in pairs:
      return
    p_open = pairs[p_close]

    level = 0
    c_start = -1
    matched_position = None

    for r in range(r_in,-1, -1):
      row = self.file.rows[r]
      if row.get_len() == 0:
        continue
      c_start = c_in  if c_start == -1 else row.get_len() - 1
      for c in range(c_start,-1, -1):
        #print(f" r {r}, c {c}")
        ch = row.at(c)
        if ch == p_close:
          #print("Level+1")
          level += 1
        if ch == p_open:
          #print("Level-1")
          level -= 1
          if level == 0:
            matched_position = (r,c)
            #print(f"matched {r},{c}")
            break
      if level == 0:
        break
    return matched_position


  def search_exec(self, direction = 0):
    if direction == 0:
      direction = self.search_info.last_direction
    else:
      self.search_info.last_direction = direction

    row = self.file_row
    col = self.file_col

    query = self.search_info.query_str
    self.search_info.matched_query = None
    #print(f"Query: {row},{col},{direction} q={query}")
    num_found = 0
    if direction == 1:
      r_goal = len(self.file.rows)
    if direction == -1:
      r_goal = -1
    
    self.search_info.aborted = False
    for idx in range(row, r_goal, direction):
      if self.v.poll():
        #keyboard interrupt
        print(f"Aborting {query}")
        self.search_info.aborted = True
        return  
      row = self.file.rows[idx]
      #print(f" searching.. row {idx} col {col} dir {direction}")
      result, self.search_info.matched_query = row.search(col, query, direction)

      # Reset col for the second line and the rest
      if direction == 1:
        col = 0 
      else:
        col = -1

      if result != None:
        num_found += 1
        #print(f"{query} found at {idx},{result}")
        self.jump_to_position(idx, result, direction)
        break

  def jump_to_position(self, r, c, direction = 1, stay_if_possible = True):
    range_ret = self.file.in_screen(r,c)
    if stay_if_possible and range_ret == 0:
      # in_screen
      self.file_row = r
      self.file_col = c
    else:
      if direction == 1:
        pad = 4 if self.file.h > 10 else 1
        if not stay_if_possible:
          pad = (self.file.h >> 1 ) - 1
      else:
        pad = 6 if self.file.h > 10 else self.file.h - 1
      lnl = self.file.gen_line_num_list(r,c, -pad,0)
      self.scroll_row = lnl[0][1]
      self.scroll_col = lnl[0][2]
      self.file_row = r
      self.file_col = c

    return
    
  def close_file(self):
    if len(self.file_list) == 0:
      self.set_message("The last file cannot be closed.")
      return
    self.process_file_select(0,"")
    del self.file_list[0]

  def process_replace1(self, replace_from):
    
    self.search_info.query_str = replace_from.chars.decode('utf-8')
    self.open_input_line_dialog("Replace",f"{replace_from.decode()} ->",self.process_replace2)
    
  def process_replace2(self, replace_to):
    self.search_info.replace_str = replace_to.chars.decode('utf-8')
    #self.mode = self.MODE_REPLACE
    #print(f"Replace {self.search_info.query_str} {self.search_info.replace_str}")
    self.search_exec(1)
    if self.search_info.matched_query:
      self.open_input_line_dialog("Replace","Replace? y/n (q for quit)", self.process_replace_yn, ["y","n","q"])
    
  def process_replace_yn(self, answer):
    #print(f"Answer: {answer.decode()}")
    if answer.chars == b"q":
      self.recall_pos(self.search_info.saved_pos)
      self.search_info.close()
      return
    if answer.chars == b"y":
      row = self.file.rows[self.file_row]
      row.delete_str(self.file_col, len(self.search_info.query_str))
      row.insert_str(self.file_col, self.search_info.replace_str)
      
    for i in range(0, len(self.search_info.replace_str)):
       self.cursor_move(0,1)
    self.search_exec(1)
    if self.search_info.matched_query:
      self.open_input_line_dialog("Replace","Replace? y/n (q for quit)", self.process_replace_yn, ["y","n","q"])
    return

  def process_goto_line(self, num):
    if not num.decode().isdigit():
      self.set_message("Not a number")
      return
    intnum = int(num.decode())-1
    if intnum < 0 or intnum >= len(self.file.rows):
      self.set_message("Out of range")
      return
    pos = self.save_pos()
    self.file.push_pos_history(pos)
    self.jump_to_position(intnum,0, 1)

  def process_open_file_select(self, idx, item):
    #print(f' {idx}:{item}')
    #self.open_input_line_dialog('Open file','Filename', self.process_open_file, answer_list = None, default_str=item.encode('utf-8'))
    self.process_open_file(item.encode('utf-8'))
    
  def process_open_file(self, name):
    #print(f"Opening.. file={name.decode()}")
    filename = name.decode()
    filename = None if filename == '' else filename
    
    self.file.saved_pos = self.save_pos()
    self.file_list.insert(0,self.file)
    self.file_row = 0
    self.file_col = 0
    self.scroll_row = 0
    self.scroll_col = 0
    self.file = editor_file(self.v, filename, self.text_height, self.text_width, self.tab_size)
    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)
    return


  def process_save_file(self, name):
    fname = name.decode()
    self.filename = fname
    self.file.filename = fname
    print(f"Saving.. file={name.decode()}")
    total = self.file.save()
      
    if total == 0:
      self.set_message('File write error')
      # Rollback the new filename to None
      self.filename = None
      self.file.filename = None
    else:
      self.set_message(f"{total} bytes written")
    return
    
  def process_yank_select(self, idx, item):
    #print("process_yank_select")
    self.yankbuf.curbuf = item
    if pdeck_enabled:
      pdeck.clipboard_copy(self.yankbuf.curbuf.encode('utf-8'))
    return

  def process_file_select(self, idx, item):
    #print("process_file_select")
    self.file_list.insert(0,self.file)
    self.file = self.file_list[idx+1]
    self.v.background_update=self.file.background_update
    self.file.w = self.text_width
    self.file.h = self.text_height
    del self.file_list[idx+1]
    self.recall_pos(self.file.saved_pos)
    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)
    
    return

  def process_input_line_dialog(self, keys):
    #Ctrl-g to quit
    if keys == b'\x07':
      self.mode = self.MODE_NORMAL
      self.h_diff -= 1
      self.text_height += 1
      self.file.h += 1
      self.sl_info = None
      self.search_info.close()
      return
      
    if self.input_answer_list:
      key = keys.decode('ascii')
      for ch in self.input_answer_list:
        if ch == key:
          #print("Answered {ch}")
          self.h_diff -= 1
          self.file.h += 1
          self.text_height += 1
          self.mode = self.MODE_NORMAL
          line = erow(keys, self.tab_size)
          s_callback = self.sl_info.callback
          self.sl_info = None
          s_callback(line)
      return     
    # Backspace
    elif keys == b'\x08':
      if self.sl_info.line.len !=0 and self.sl_info.cur != 0:
        self.sl_info.line.delete_str(self.sl_info.cur -1,1)
        self.sl_info.cur -= 1  
    # Enter
    elif keys in (b'\x0d', b'\x0a'): 
      #print("Calling callback")
      self.h_diff -= 1
      self.file.h += 1
      self.text_height += 1
      self.mode = self.MODE_NORMAL
      line = self.sl_info.line
      s_callback = self.sl_info.callback
      self.sl_info = None
      s_callback(line)
    elif keys in (b'\x09') and self.sl_info.callback == self.process_open_file:
      #TAB
      try:
        flist = ls.list_file(self.sl_info.line.decode() + '*')
        if len(flist[1]) > 0:
          if len(flist[1]) > 1:
            slist=[]
            for item in flist[1]:
              slist.append(flist[0] + '/' + item)
            
            self.h_diff -= 1
            self.file.h += 1
            self.text_height += 1
            self.sl_info = None
            self.open_select_dialog(slist,5,"File list", self.process_open_file_select)
            
          else:
            new_line = (flist[0] + '/' + flist[1][0])
            self.sl_info.line.update_str(bytearray(new_line.encode('utf-8')))
            self.sl_info.cur = len(new_line)
      except Exception as e:
         print(e)
    else:
      if keys[0] >= 0x20:
        self.sl_info.line.insert_str(self.sl_info.cur, keys)
        self.sl_info.cur += 1

    
  def process_select_dialog(self, keys):
    #Ctrl-g to quit
    if keys in (b'\x07', b'q'):
      self.mode = self.MODE_NORMAL
      self.h_diff -= self.sd_info.height
      self.text_height += self.sd_info.height
      self.file.h += self.sd_info.height
      self.sd_info = None
      return
    #Up
    elif keys in (b'\x1b[A', b'\x10'):
      if self.sd_info.scroll + self.sd_info.cur != 0:
        self.sd_info.cur -= 1
      if self.sd_info.cur < 0:
        self.sd_info.cur = 0
        self.sd_info.scroll -= 1
    #Down
    elif keys in  (b'\x1b[B', b'\x0e'):
      if self.sd_info.scroll + self.sd_info.cur < len(self.sd_info.slist) - 1:
        self.sd_info.cur += 1
      if self.sd_info.cur == self.sd_info.height:
        self.sd_info.cur -= 1
        self.sd_info.scroll += 1
    #Enter
    elif keys in ( b'\x0d', b'\x0a'): 
      self.h_diff -= self.sd_info.height
      self.text_height += self.sd_info.height
      self.file.h += self.sd_info.height
      self.sd_info.callback(self.sd_info.cur + self.sd_info.scroll, self.sd_info.slist[self.sd_info.cur + self.sd_info.scroll])
      self.mode = self.MODE_NORMAL
      self.sd_info = None
      return

  def process_comp_select(self, idx, comp):
    pos, sym = self.file.get_symbol(self.file_row, self.file_col)
    row = self.file.rows[self.file_row]
    row.delete_str(pos,len(sym))
    row.insert_str(pos,comp)
    #print(f"Replaced to {comp}")
    #self.cursor_move(0,pos - self.file_col + len(comp))
    self.file_col += pos - self.file_col + len(comp)
    #print(" cursor move to {}".format(pos - self.file_col + len(comp)))
    


  def process_search(self, keys, direction = 1):
    #Ctrl-g to quit
    if keys == b'\x07':
      self.scroll_row, self.scroll_col, self.file_row, self.file_col = self.search_info.saved_pos
      if self.search_info.matched_query != None:
        self.search_info.last_query_str = self.search_info.query_str
      self.mode = self.MODE_NORMAL
      self.search_info.close()
      return

    #Arrow keys (or any escape sequences, some control keys) to quit
    #print(f"hi {keys}")
    if keys[0] == 0x1b \
        or keys in (b'\x01', b'\x02', b'\x05', b'\x06', b'\x0a',b'\x0b', b'\x0e', b'\x10'):
      #print("hi2")
      pos = self.save_pos()
      self.file.push_pos_history(pos)  
      if self.search_info.matched_query != None:
        self.search_info.last_query_str = self.search_info.query_str
        #print(f"Record last query = {self.search_info.last_query_str}")
      self.mode = self.MODE_NORMAL
      self.search_info.close()
      return

    #Ctrl-s (Next)
    if keys == b'\x13':
      if self.search_info.matched_query:
        self.cursor_move(0,1)
      else:
        if len(self.search_info.query_str) == 0 and self.search_info.last_query_str:
          #print("last query: {self.search_info.last_query_str}")
          self.search_info.query_str = self.search_info.last_query_str
        else:
          self.file_row = 0
          self.file_col = 0

      self.search_exec(1)

    #Ctrl-r (Reverse)
    if keys == b'\x12':
      if self.search_info.matched_query:
        self.cursor_move(0,-1)
      else:
        if len(self.search_info.query_str) == 0 and self.search_info.last_query_str:
          #print("last query: {self.search_info.last_query_str}")
          self.search_info.query_str = self.search_info.last_query_str

      self.search_exec(-1)
      
    elif keys == b'\x08':
      self.search_info.query_str = self.search_info.query_str[:-1]
      if (self.search_info.query_str) == 0:
        self.scroll_row, self.scroll_col, self.file_row, self.file_col = self.search_info.saved_pos
        self.mode = self.MODE_NORMAL
        return
      self.file_row = self.search_info.saved_pos[2]
      self.file_col = self.search_info.saved_pos[3]
      self.search_exec()
    elif keys == b'\x19':
      # Yank
      if self.yankbuf.curbuf:
        line_str = self.yankbuf.curbuf
        pos = line_str.find("\n")
        if pos != -1:
          self.search_info.query_str += self.yankbuf.curbuf[:pos]
        else:
          self.search_info.query_str += self.yankbuf.curbuf
        #print(f"curbuf:{self.yankbuf.curbuf}")
        #print(f"sbuf:{self.search_info.query_str}")
        self.search_exec()

    elif keys[0] >= 0x20:

      self.search_info.query_str += keys.decode("utf-8")
      if self.search_info.aborted or self.search_info.matched_query or len(self.search_info.query_str) == 1:
        self.search_exec()

  def set_message(self, message):
    self.status_message=message
    self.status_message_life = 1

  def open_select_dialog(self,slist,height,subject, callback):
    self.mode = self.MODE_SELECT_DIALOG
    self.sd_info = select_dialog_info(slist, height, subject, callback)
    self.h_diff += height
    self.text_height -= height
    self.file.h -= height
    self.render_main_text(True)
    self.jump_to_position(self.file_row, self.file_col, 1, False)

  def open_input_line_dialog(self,subject,header,callback, answer_list = None, default_str=b''):
    self.mode = self.MODE_INPUT_LINE_DIALOG
    self.sl_info = input_line_info(subject, header, callback, default_str)
    self.h_diff += 1
    self.text_height -= 1
    self.file.h -= 1
    self.render_main_text(True)
    self.input_answer_list = answer_list
    self.jump_to_position(self.file_row, self.file_col, 1, False)

  def switch_buf_if_exists(self,link_filename):
    # Check if the file is already opened
    for i,file in enumerate(self.file_list):
      #print(f'{file.filename} vs {link_filename}')
      if file.filename == link_filename or file.filename == link_filename + '.md':
        self.process_file_select(i,None)
        return True
    return False
  
  def process_key(self):
    keys = self.v.read(1)


    tw, th = self.v.get_terminal_size()
    if tw != self.text_width or th-self.h_diff != self.text_height:
      print(f'ow,oh,nw,nh = {self.text_width},{self.text_height},{tw},{th}')
      h_diff = self.text_height - self.file.h
      self.text_width = tw
      self.text_height = th-1
      self.file.w = tw
      self.file.h = self.text_height - h_diff
      #self.jump_to_position(self.file_row, self.file_col, 1, False)
      self.update_scroll_for_curmove()
      #print("size changed")


    # Ctrl-x;
    if keys == b'\x18':
      seq = [ keys ]
      seq.append( self.v.read(1) )
      keys = b''.join(seq)
   
    # C- x C-c to exit
    if keys == b'\x18\x03':
      return 1



    if keys == b'\x1b':
      seq = [ keys ]
      seq.append( self.v.read(1) )
      if seq[-1] == b'[' or seq[-1] == b'O':
        # In Rawmode, arrow keys as send as \x1bOA (or BCD) instead of \x1b[A (or BCD). Replace it back to '['
        seq[-1] = b'['
        seq.append( self.v.read(1) )
        if seq[-1] >= b'0' and seq[-1] <= b'9':
          seq.append( self.v.read(1) )
        keys = b''.join(seq)
        #print(keys)
      else:
        keys = b''.join(seq)

    #print(f"--- {keys} ---")
    #self.v.read(1)
    self.dmod = True
    
    if self.mode == self.MODE_SEARCH:
      return self.process_search(keys)
      
    if self.mode == self.MODE_SELECT_DIALOG:
      return self.process_select_dialog(keys)

    if self.mode == self.MODE_INPUT_LINE_DIALOG:
      return self.process_input_line_dialog(keys)




    if self.file.input_method == self.IM_JP:
      if keys == b'\x1b`':
        pass
      elif self.file.im_session and len(self.file.im_session.buffer) == 0 and keys[0] <= 0x20:
        # Pass through control chars when IM is not active
        pass
      else:
        last_len = len(self.file.im_session.buffer)
        if last_len == 0:
          self.file.org_row = self.file.rows[self.file_row]
          
        result = self.file.im_session.feed_key(keys)
        if len(result) != 0:
          self.file.rows[self.file_row] = self.file.org_row
          self.file.insert_str(self.file_row, self.file_col, result)
          self.file_col += len(result)
          self.jump_to_position(self.file_row, self.file_col, -1)

        if last_len > 0 and len(self.file.im_session.buffer) == 0:
          #print('clear')
          self.file.rows[self.file_row] = self.file.org_row
          self.file.org_row = None #self.file.rows[self.file_row]

        if self.file.im_session and len(self.file.im_session.buffer) > 0:
          row = self.file.org_row
          curcol = self.file_col
          temp_row = erow( row.substr(0,curcol) +  el.set_font_color(4) +  self.file.im_session.d_buffer.encode('utf-8') + el.set_font_color(0) + row.substr(curcol, -1), self.file.tab_size)
          self.file.rows[self.file_row] = temp_row
          self.update_scroll_for_curmove(self.file.im_session.col)
          
        return 0
      
    # C-x C-s to save file
    if keys == b'\x18\x13':
      if self.file.filename == None:
        self.open_input_line_dialog("Save file","Filename",self.process_save_file)
      else:
        while True:
          total = self.file.save()
          if total != 0:
            break
          print("File write error. Retrying..")
          time.sleep_ms(200)
        
        if total == 0:
          self.set_message('File write error')
        else:
          self.set_message(f"{total} bytes written")

    # C-x C-f to open file
    if keys == b'\x18\x06':
      
      self.open_input_line_dialog("Open file in "+os.getcwd(),"Filename",self.process_open_file)

    # C-x k to close file
    if keys == b'\x18k':
      self.close_file()

    # C-x b to switch buffer
    if keys == b'\x18b':
      filenames = []
      for file in self.file_list:
        if file.filename == None:
          filenames.append("** New file **")
        else:
          filenames.append(file.filename)
      if len(filenames) == 0:
        self.set_message("No files to switch")
      else:
        self.file.saved_pos = self.save_pos()
        self.open_select_dialog(filenames, 5, "File list", self.process_file_select)


    # Reset yankbuf if the operation is not kill
    if keys != b'\x0b' and keys != b'\x1b[3~' and keys != b'\x04':
      self.adding_yank = False

    #Ctrl-s (Search)
    if keys == b'\x13':
      pos = self.save_pos()
      self.file.push_pos_history(pos)
      self.mode = self.MODE_SEARCH
      self.search_info.start_search( (self.scroll_row, self.scroll_col, self.file_row, self.file_col),1)

    #Ctrl-r (Reverse Search)
    elif keys == b'\x12':
      pos = self.save_pos()
      self.file.push_pos_history(pos)
      self.mode = self.MODE_SEARCH
      self.search_info.start_search( (self.scroll_row, self.scroll_col, self.file_row, self.file_col),-1 )

    # Escape + % (Replace)
    elif keys == b'\x1b%':
      pos = self.save_pos()
      self.search_info.start_search(pos,1,True)
      self.open_input_line_dialog("Replace","Replace from",self.process_replace1)

    # Escape + " " (Manual marking)
    elif keys == b'\x1b\x20':
      pos = self.save_pos()
      self.file.push_pos_history(pos)
      self.set_message("Position marked.")
    # Escape + ' (Position hisoty walk forward)
    elif keys == b'\x1b\x27':
      pos = self.file.walk_pos_history(1)
      if pos:
        self.recall_pos(pos)
      else:
        self.set_message("No more history")
   
    # Escape + ; (Position hisoty walk backward)
    elif keys == b'\x1b;':
      pos = self.file.walk_pos_history(-1)
      if pos:
        self.recall_pos(pos)
      else:
        self.set_message("No more history")

    # Escape + g : Go to input line #
    elif keys == b'\x1bg':
      self.open_input_line_dialog("Go to line #","Line #",self.process_goto_line)

    # Escape + . : Go to function definition in Python mode, try to go link in md mode
    elif keys in (b'\x1b.', b'\x1b/'):
      pos, sym = self.file.get_symbol(self.file_row, self.file_col)
      #print(f'sym {sym}')
      if sym and self.file.mode == 'md':
        print(f'sym in md mode {sym}')
        if sym.startswith('/'):
          dirname = ''
        else:
          dirname = _dirname(self.file.filename) + "/"
        try:
          link_filename = dirname + sym
          #print(link_filename)
          st = os.stat(link_filename)
          if st[0]&0x4000:
            raise Exception('directory')
    
          res = self.switch_buf_if_exists(link_filename)
          if not res:
            self.process_open_file(link_filename.encode('utf-8'))
        except Exception as e:
          try:
            link_filename += ".md"
            #print(link_filename)
            st = os.stat(link_filename)
            res = self.switch_buf_if_exists(link_filename)
            if not res:
              self.process_open_file(link_filename.encode('utf-8'))
          except Exception as e:
            self.process_open_file(link_filename.encode('utf-8'))
            #self.set_message('Link not found')
            print(e)
        
      if sym and self.file.mode == 'py':
        pos = self.save_pos()
        self.file.push_pos_history(pos)
        self.mode = self.MODE_SEARCH
        self.search_info.start_search( (self.scroll_row, self.scroll_col, self.file_row, self.file_col),1)
        self.search_info.query_str = sym
        if keys == b'\x1b.':
          self.search_info.query_str = "def " + sym
          self.file_row = 0
          self.file_col = 0

        self.search_exec(1)



    # Escape + < : Go to the top
    elif keys == b'\x1b<':
      self.jump_to_position(0,0,1)

    # Escape + > : Go to the end
    elif keys == b'\x1b>':
      r = len(self.file.rows) -1
      c = self.file.rows[-1].get_len()
      self.jump_to_position(r,c,-1)

    # Escape + y : Select kill ring
    elif keys == b'\x1by':
      self.yankbuf.reset_buf()
      if len(self.yankbuf.bufs) == 0:
        self.set_message("No yank list")
      else:
        self.open_select_dialog(self.yankbuf.bufs,5, "Yank list", self.process_yank_select)

    #Ctrl-a (Move to the start of the line)
    elif keys in (b'\x01', b'\x1b[1~'):
      # Stop at indent first
      if self.file.mode == "py":
        pos = self.file.get_indent(self.file_row)
        if pos != -1 and pos < self.file_col:
          self.file_col = pos
        else:
          self.file_col = 0

      else:
        self.dmod = False
        self.file_col = 0
      self.update_scroll_for_curmove()

    #Ctrl-e (Move to the end of the line)
    elif keys in (b'\x05', b'\x1b[4~'):
      self.dmod = False
      self.file_col = self.file.rows[self.file_row].get_len()
      self.update_scroll_for_curmove()
    
    #Ctrl-k (Erase to the end of the line)
    elif keys == b'\x0b':
      if not self.adding_yank:
        self.yankbuf.reset_buf()
      self.file.erase_to_the_end(self.file_row, self.file_col, self.yankbuf)
      self.adding_yank = True

    #Ctrl-y (Yank)
    elif keys == b'\x19':
      self.file_row, self.file_col = self.file.yank(self.file_row, self.file_col, self.yankbuf)
      self.jump_to_position(self.file_row, self.file_col, -1)

    elif keys == b'\x0c':
      #print("center")
      self.jump_to_position(self.file_row, self.file_col, 1, False)
      self.dmod = True

    #Up
    elif keys in (b'\x1b[A', b'\x10'):
      self.dmod = False
      self.cursor_move(-1,0)
    #Down
    elif keys in (b'\x1b[B', b'\x0e'):
      self.dmod = False
      self.cursor_move(1,0)
    #Left
    elif keys in (b'\x1b[D', b'\x02'):
      self.dmod = False
      self.cursor_move(0,-1)
    #Right 
    elif keys in (b'\x1b[C', b'\x06'):
      self.dmod = False
      self.cursor_move(0,1)

    # Input method toggle
    elif keys in (b'\x1b`', b'\x1b~'):
      if self.file.input_method == self.IM_EN:
        self.file.input_method = self.IM_JP
        if not self.jpfont_loaded:
          self.load_jpfont()
        self.file.im_session = jp_input.input_session()
        #self.file.org_row = self.file.rows[self.file_row]
        self.file.org_row = None
      else:
        self.file.input_method = self.IM_EN
        self.file.im_session = None
        if self.file.org_row:
          self.file.rows[self.file_row] = self.file.org_row
        self.file.org_row = None


    # Delete
    elif keys in ( b'\x1b[3~', b'\x04'): 
      if not self.adding_yank:
        self.yankbuf.reset_buf()
      self.adding_yank = True
      self.file_row, self.file_col = self.file.delete_one_char_del(self.file_row, self.file_col, self.yankbuf)
      self.update_scroll_for_curmove()

    # Backspace
    elif keys == b'\x08': 
      self.file_row, self.file_col = self.file.delete_one_char_bs(self.file_row, self.file_col)
      self.update_scroll_for_curmove()
                    
    # Enter
    elif keys in (b'\r',b'\x0a'):
      self.file_row, self.file_col = self.file.insert_return(self.file_row, self.file_col)
      self.update_scroll_for_curmove()
    #PageDown
    elif keys ==  b'\x1b[6~':
      lnl = self.file.gen_line_num_list(self.file_row, self.line_num_list[self.d_row][2],0, self.file.h)
      if self.wished_d_col != -1:
        d_col = self.wished_d_col
      else:
        d_col = self.d_col
      next_file_row = lnl[-1][1]
      next_file_col = lnl[-1][2] + d_col
      if next_file_col > self.file.rows[lnl[-1][1]].get_len():
        next_file_col = self.file.rows[lnl[-1][1]].get_len()
        self.wished_d_col = self.d_col
      self.jump_to_position(next_file_row, next_file_col)
      
      #for i in range(self.file.h):
      #  self.cursor_move(1,0)
      #  self.render_main_text(True) #dry_run
      #  self.update_d_cursor()
    #PageUp
    elif keys ==  b'\x1b[5~':
      lnl = self.file.gen_line_num_list(self.file_row, self.line_num_list[self.d_row][2],-self.file.h,0)
      if self.wished_d_col != -1:
        d_col = self.wished_d_col
      else:
        d_col = self.d_col
      next_file_row = lnl[0][1]
      next_file_col = lnl[0][2] + d_col
      if next_file_col > self.file.rows[lnl[0][1]].get_len():
        next_file_col = self.file.rows[lnl[0][1]].get_len()
        self.wished_d_col = self.d_col
      self.jump_to_position(next_file_row, next_file_col)
      #for i in range(self.file.h):
      #  self.cursor_move(-1,0)
      #  self.render_main_text(True) #dry_run
      #  self.update_d_cursor()
    #tab
    elif keys == b'\x09':
      tab_process = True
      if self.file.mode == "py":
        indent = self.file.get_indent(self.file_row)
        if indent >= 2 and self.file_col > indent:
          tab_process = False
          pos, sym = self.file.get_symbol(self.file_row, self.file_col)
          if sym:
            complist = self.file.get_comp_list(sym)
            if not complist:
              return
            if len(complist) == 0:
              return
            if len(complist) == 1:
              self.process_comp_select(0,complist[0])
              return
              
            list_size = 5 if len(complist) >=5 else len(complist)
            self.open_select_dialog(complist,list_size, "Compeletion", self.process_comp_select)
            #print(complist)
            
          else:
            self.set_message("List not found")
      
      if tab_process:
        num_space = self.tab_size - self.file.rows[self.file_row].expand(0,self.file_col) % self.tab_size
        if num_space == 0:
          num_space = self.tab_size        
        self.file.insert_str(self.file_row, self.file_col, " "*num_space)
        self.cursor_move(0,num_space)
    
    # Letters, etc..  
    else:
      if int(keys[0]) >= 0x20:
        self.file.insert_str(self.file_row, self.file_col, keys)
        mresult = self.match_parenthesis(self.file_row,self.file_col)
        if mresult:
          org_pos = self.save_pos()
          self.jump_to_position(mresult[0], mresult[1])
          self.refresh_screen()
          for i in range(16):
            if self.v.poll():
              break
            time.sleep_ms(50)
          self.recall_pos(org_pos)

        self.cursor_move(0,1)
        self.update_scroll_for_curmove()

    #print(f"file_row {self.file_row}")
    #if keys == b"\x1b"
    return 0

  def save_pos(self):
    return (self.scroll_row, self.scroll_col, self.file_row, self.file_col)
  def recall_pos(self, pos):
    self.scroll_row, self.scroll_col, self.file_row, self.file_col = pos

class select_dialog_info:
  def __init__(self, slist, height, subject, callback):
    self.slist = slist
    self.subject = subject
    self.height = height
    self.callback = callback
    self.cur = 0
    self.scroll = 0

class input_line_info:
  def __init__(self, subject, header, callback, default_str=b''):
    self.subject = subject
    self.callback = callback
    self.header = header
    self.line = erow(default_str, 2) # dummy tab_size
    self.cur = 0

class search_info:
  def __init__(self):
    self.saved_pos = []
    self.last_query_str = None
    self.query_str = None
    self.replace_str = None
    self.p_query_str = None
    self.p_replace_str = None
    self.matched_query = None
    self.index = 0
    self.last_direction = 1
    self.isreplace = False
    self.aborted = False

  def start_search(self,pos, direction, replace = False):
    self.saved_pos = pos
    self.query_str = ""
    self.replace_str = None
    self.matched_query = None
    self.index = 0
    self.last_direction = direction
    self.isreplace = replace
  def close(self):
    self.start_search(None, 1)
    
class editor_file:
  def __init__(self, v, filename,h,w, tab_size):
    self.v = v
    self.input_method = IM_EN
    self.im_session = None
    self.tab_size = tab_size
    self.rows = []
    self.pos_history = []
    self.phistory_cur = 0
    self.saved_pos = None
    self.h = h
    self.w = w
    self.modified = False
    self.filename = filename
    self.mode = "txt"
    self.num_updated = 0
    self.period_regex = {}
    self.period_regex['py'] = re.compile("([A-Za-z0-9_]+)")
    self.period_regex['md'] = re.compile("([A-Za-z0-9_\ \/\.']+)")
    if self.filename != None and self.filename[-3:] == ".md":
      self.mode = "md"
    elif self.filename != None and self.filename[-3:] == ".py":
      self.mode = "py"
    if self.file_exists(filename):
      try:
        with open(filename, "r") as f:
          for line in f:
            if line[-1] in ('\n', '\r'):
              if len(line) > 1 and line[-2] in ('\r','\n'):
                line = line[:-2]
              else:
                line = line[:-1]
            self.rows.append(erow(line.encode('utf-8'), self.tab_size))
      except:
        self.rows.append(erow(b"", self.tab_size))
    else:
      self.rows.append(erow(b"", self.tab_size))

  def background_update(self):
    if self.num_updated < len(self.rows):
      for i in range(self.num_updated, self.num_updated+3):
        if i < len(self.rows):
          self.rows[i].update()
      self.num_updated += 3
      return True
    return False

  def push_pos_history(self,pos):
    # Detect Duplication
    if len(self.pos_history) > 0 and self.phistory_cur > 0 and pos[2] == self.pos_history[self.phistory_cur-1][2] and pos[3] == self.pos_history[self.phistory_cur-1][3]:
      return

    #if len(self.pos_history) > 0:
    
    self.phistory_cur += 1
    self.pos_history.insert(self.phistory_cur,pos)
    #print(f"pos history saved to #{self.phistory_cur}:{pos[2]},{pos[3]}")
    #if len(self.pos_history) == 0:
    #  self.phistory_cur += 1

    if len(self.pos_history) > 30:
      if self.phistory_cur > 10:
        del self.pos_history[-1]
      else:
        del self.pos_history[0]
      #self.phistory_cur -= 1
      if self.phistory_cur > len(self.pos_history):
        self.phistory_cur = len(self.pos_history)

  def walk_pos_history(self,step):
    if self.phistory_cur+step < 0 or self.phistory_cur+step >= len(self.pos_history):
      return None
    self.phistory_cur += step
    return self.pos_history[self.phistory_cur]

  def file_exists(self,name):
    if name == None:
      return False
    try:
      os.stat(name)
      return True
    except OSError:
      return False


  def save(self):
    if self.filename == None:
      return
    total_bytes = 0
    try:
      with open(self.filename, "wb") as f:
        for row in self.rows:
          f.write(row.chars)
          f.write("\n")
          total_bytes += len(row.chars) + 1
      self.modified = False
      os.sync()
    except:
      return 0
    return total_bytes

  def get_indent(self, r):
    row = self.rows[r]
    rlen = self.rows[r].get_len()
    if rlen == 0:
      return 0
    first_nonspace = -1
    if row.at(0) == b' ':
      for c in range(0, rlen):
        if row.at(c) != b' ':
          first_nonspace = c
          break
    return first_nonspace


  def gen_line_num_list(self,filerow, filecol, rel_start,rel_end):
    lnl = [ [0, filerow, filecol] ]
    for _ in range(rel_end):    
      newln = self.get_next_line_num_list(lnl)
      if newln:
        lnl.append(newln)
    if rel_start < 0:
      for _ in range(rel_start,0):
        newln = self.get_prev_line_num_list(lnl)
        if newln:
          lnl.insert(0, newln)
    #print(lnl)
    return lnl

  def get_prev_line_num_list(self, lnl):
    top_ln = lnl[0]
    toprow = self.rows[top_ln[1]]
    if top_ln[2] > 0:
      next_stop = toprow.expanded_to_pos(top_ln[2], -self.w)
      return ( top_ln[0] - 1, top_ln[1], next_stop)
    else:
      if top_ln[1] == 0:
        return None
      file_row = top_ln[1] - 1
      nextrow = self.rows[file_row]
      elen = nextrow.cpos_to_dpos(-1) #nextrow.ex_len -1
      elen = 0 if elen < 0 else elen
      file_col = nextrow.dpos_to_cpos((elen // self.w) * self.w)
      #print(f"here {nextrow.ex_len}")
      return (top_ln[0] - 1, file_row, file_col)

  def get_next_line_num_list(self, lnl):
    last_ln = lnl[-1]
    lastrow = self.rows[last_ln[1]]
    #if lastrow.expand(last_ln[2],lastrow.get_len()) > self.w:
    maybe_next_stop = lastrow.expanded_to_pos(last_ln[2], self.w)
    if maybe_next_stop < lastrow.get_len():
      next_stop = maybe_next_stop
      return (last_ln[0] + 1, last_ln[1], next_stop)
    else:
      file_row = last_ln[1] + 1
      if file_row >= len(self.rows):
        return None
      return (last_ln[0] + 1, file_row, 0)

  def utf8_trim(self, str, col):
    ct = 0
    i = 0
    for ch in str:
      ct += pdeck.get_utf8_width(ch)
      #if ord(ch) >= 0x100:
      #  ct += 2
      #else:
      #  ct += 1
      
      i += 1
      if ct >= col:
        return str[:i]
    return str


  def file_refresh_screen(self,filerow, filecol, currow, curcol, dry_run = False):

    bm.add_bench('refresh_start')
      
    out_buf = bytearray()
    line_count = 0
    
    lnl = self.gen_line_num_list(filerow, filecol,0, self.h - 1)
    bm.add_bench('num_list')

    #print(lnl)
    #print(len(lnl))

    for ln in lnl:
      if not dry_run:
        row = self.rows[ln[1]]
        #print(f"exchars: {row.get_ex_chars()}")

        # Trim the row to one display line.
        # ln[2] is the starting column
        # expos will be the end of the column
        expos, d_pos = row.expanded_to_pos_with_d(ln[2], self.w)
        out_line = row.substr(ln[2], expos)
        
        
        if row.tab_detected:
          # Use cached expanded characters and slice them
          # We need to map ln[2] (file col) and expos (file col end) to expanded col positions
          # or simply use the fact that d_pos is display position.
          d_start = row.bdmap[row.cbmap[ln[2]]]
          out_line = row.ex_chars[d_start : d_start + self.w]
        else:
          out_line = row.substr(ln[2], expos)
        
        out_buf.extend(out_line)
        out_buf.extend(el.erase_to_end_of_current_line().encode('utf-8'))
        #print(f"outbuf: {out_line}")
        #print(f"outbuf: {out_line.decode('utf-8')}")
        
        #out_buf.extend(el.erase_to_end_of_current_line().encode('utf-8'))
        if ln[0] != self.h-1:
          line_count += 1
          out_buf.extend(b"\r\n")
    #Add lines if it's not enough
    while line_count < self.h:
      line_count += 1
      out_buf.extend(el.erase_to_end_of_current_line().encode('utf-8') + b"\r\n")
      #out_buf.extend(b"\r\n")
      
    if not dry_run:
      self.v.print(el.cursor_mode(False)) #hide cursor
      self.v.print(el.home())
      #print(out_buf.decode('utf-8'))
      #self.v.print(out_buf.decode('utf-8'))
      self.v.print(out_buf)
    #print(f"line_count {line_count}")
    self.line_num_list = lnl
    bm.add_bench('print')
    return lnl

  def in_screen(self, row, col):
    lnl = self.line_num_list
    #print(f"in_screen {row},{col}")
    #print(lnl)
    if row < lnl[0][1]:
      return -1
    if row == lnl[0][1] and col < lnl[0][2]:
      return -1
    w = lnl[-1][2] + self.w
    if row == lnl[-1][1]:
      lnl_next = self.gen_line_num_list(lnl[-1][1], lnl[-1][2], 0,1)
      if len(lnl_next) == 2 and lnl_next[1][1] == row:
        w = lnl_next[1][2]

    if row > lnl[-1][1] or (row == lnl[-1][1] and col >= w):
      #if file is less  then one screen
      if lnl[-1][0] < self.h - 1:
        pad = self.h - lnl[-1][0]
        if row < lnl[-1][1]+pad:
          return 0
      return 1
    return 0

  def scr_to_filepos(self, h, w, scr_y, scr_x):
    # Convert screen position to file position
    # This might return filecol more than the its length

    file_row = -1
    file_col = -1
    lnl = self.line_num_list

    # Take care if scr_y is out of screen
    # (Only one more line)
    if scr_y == -1:
      lnl_extra = self.gen_line_num_list(lnl[0][1], lnl[0][2], -1,0)
      for ln in lnl_extra:
        if ln[0] == -1:
          #print(f"lnl_extra {ln}")
          return (ln[1], self.rows[ln[1]].expanded_to_pos(ln[2], scr_x))
      return None # if there is no item for the line_num, return None

    if scr_y == h:
      lnl_extra = self.gen_line_num_list(lnl[h-1][1], lnl[h-1][2], 0,1)
      for ln in lnl_extra:
        if ln[0] == 1:
          return (ln[1], self.rows[ln[1]].expanded_to_pos(ln[2], scr_x))
      return None # if there is no item for the line_num, return None


    # scr_y is within the display
    for lineinfo in lnl:
      if lineinfo[0] == scr_y:
        file_row = lineinfo[1]
        file_col = self.rows[file_row].expanded_to_pos(lineinfo[2], scr_x)
        break

    if file_row == -1:
      return None    
    return (file_row, file_col)

  def insert_str(self, r, c, str):
    self.modified = True
    self.rows[r].insert_str(c,str)

  def insert_return(self, r, c, auto_indent = True):
    self.modified = True
    newrow = erow(self.rows[r].substr(c,-1), self.tab_size)

    # Auto indent for Python
    ind = 0
    if auto_indent and self.mode == "py" and c != 0:
      ind = self.get_indent(r)
      ind = 0 if ind == -1 else ind
      if self.rows[r].at(c-1) == b":":
        ind += 2
      #print(f"Auto indent ind = {ind}")
      if ind != -1:
        newrow.insert_str(0," "*ind)

    self.rows[r].update_str(self.rows[r].substr(0,c))
    self.rows.insert(r+1, newrow)
    return (r+1, ind)

  def get_comp_list(self, sym):
    row = 0
    col = 0
    query = sym
    comp_list = []
    #print(f"CompQuery: {row},{col} q={query}")
    r_goal = len(self.rows)

    for idx in range(row, r_goal):
      if self.v.poll():
        #keyboard interrupt
        return None
      row = self.rows[idx]
      #print(f" searching.. row {idx} col {col} dir {direction}")

      col = 0 

      while True:
        result, matched_string = row.search(col, query, 1, True)


        if result != None:
          pos, sym = self.get_symbol(idx,result)
          if sym:
            #print(f"Comp:maybe {sym}")
            if len(sym) > len(query) and query == sym[:len(query)]:
              comp_list.append(sym)
            col = result + 1
            if len(comp_list) > 20:
              break
          else:
            # error to get symbol
            break
        else:
          break
    if len(comp_list) > 0:
      comp_list = list(set(comp_list))
    return comp_list

  def get_symbol(self, r,c):
    line = self.rows[r]
    if self.mode == 'py':
      search_list = ( b".",b"(",b" ",b"+",b"/",b"-",b"~",b"=",b">",b"<",b"?",b",",b".",b"{",b"}",b"[",b"]",b"|")
    elif self.mode == 'md':
      search_list = ( b"(",b"+",b"-",b"~",b"=",b">",b"<",b"?",b",",b"{",b"}",b"[",b"]",b"|")
    else:
      return None
      
    period = None
    sep_ch = None
    for ch in range(c-1,-1,-1):
      for search_ch in search_list:
        if line.at(ch) == search_ch:
          period = ch
          sep_ch = search_ch
          break
      if period:
        break

    if period:
      result = self.period_regex[self.mode].search(line.substr(period,-1).decode('utf-8'))
    else:
      return (None, None)
    if result:
      #print(result.group(1))
      # Return the top column of the symbol and the symbol itself
      return (period + 1, result.group(1))
    else:
      return (None, None)

  def yank(self, r, c, yankbuf):
    self.modified = True
    if yankbuf.curbuf != None:
      line_str = yankbuf.curbuf
      while True:
        pos = line_str.find("\n")
        if pos != -1:
          #print(f"return found at {pos}")
          self.rows[r].insert_str(c, line_str[:pos])
          self.insert_return(r, c+pos, False)
          line_str = line_str[pos+1:]
          r += 1
          c = 0
        else:        
          self.rows[r].insert_str(c, line_str)
          c += len(line_str)
          break
    return (r,c)
        
  def erase_to_the_end(self, r, c, yankbuf):
    self.modified = True
    if c == 0 and r < len(self.rows) - 1:
      yankbuf.add_str(self.rows[r].chars.decode('utf-8'))
      yankbuf.add_str("\n")
      del self.rows[r]
    elif c == self.rows[r].get_len() and len(self.rows)-1 > r:
      self.rows[r].insert_str(c,self.rows[r+1].chars)
      yankbuf.add_str("\n")
      del self.rows[r+1]
    else:
      yankbuf.add_str(self.rows[r].substr(c, -1).decode('utf-8'))
      self.rows[r].erase_to_the_end(c)

  def delete_one_char_bs(self, r, c):
    self.modified = True
    if c == 0:
      if r == 0:
        return (r,c)
      col = self.rows[r - 1].get_len()
      self.rows[r-1].insert_str(self.rows[r-1].get_len(), self.rows[r].chars)
      del self.rows[r]
      return (r-1, col)
    else:
      self.rows[r].delete_str(c - 1,1)
      return (r, c - 1)      

  def delete_one_char_del(self, r, c, yankbuf):
    self.modified = True
    if self.rows[r].get_len() == 0:
      if len(self.rows) > 1:
        del self.rows[r]
    elif c == self.rows[r].get_len() and len(self.rows)-1 > r:
      self.rows[r].insert_str(c,self.rows[r+1].chars)
      del self.rows[r+1]
    else:
      yankbuf.add_str(self.rows[r].at(c).decode('utf-8'))
      self.rows[r].delete_str(c,1)
    return (r, c)

class yank_buffer:
  def __init__(self):
    self.bufs = []
    self.curbuf = None
    self.numbuf = 40

  def add_str(self, str):
    if self.curbuf == None:
      self.curbuf = str
    else:
      self.curbuf += str
    #print(f"yank buf '{self.curbuf}'")
    if pdeck_enabled:
      pdeck.clipboard_copy(self.curbuf.encode('utf-8'))
      
    

  def reset_buf(self):
    if self.curbuf != None:
      self.bufs.insert(0, self.curbuf)
      if len(self.bufs) > self.numbuf:
        del self.bufs[self.numbuf]
      self.curbuf = None


class erow:
  def __init__(self, str, tab_size):
    self.chars = str
    if self.chars == None:
      self.chars = bytearray()
    if type(self.chars) == bytes:
      self.chars = bytearray(self.chars)
    if type(self.chars) != bytearray:
      raise Exception(f'chars must be bytearray {type(self.chars)}, {self.chars}')
    
    self.tab_size = tab_size
    self.tab_detected = False
    self.scanned = False
    self.updated = False
    #self.update(True)

  def decode(self):
    return self.chars.decode('utf-8')

  def update(self, skip_tab_scan = False):
    # bmap stores char to byte offset info
    self.cbmap = array.array('h')
    # cmap stores byte to char info
    self.bcmap = array.array('h')
    # dmap stores bytes to display width (utf-8 chars has size of 2, and tab)
    self.bdmap = array.array('h')
    # dmap stores display width to bytes (utf-8 chars has size of 2, and tab)
    self.dbmap = array.array('h')

    numchar = 0
    numdchar = 0
    last_numchar = 0
    last_numdchar = 0
    tab_found = False
    escape_sequence_idx = 0
    csize=0
    dsize=0
    for i,ch in enumerate(self.chars):
      #if ch&0xc0 != 0x80 and escape_sequence_idx == 0:
      #  last_numchar = numchar
      #  last_numdchar = numdchar
      #if escape_sequence_idx == -1:
      #  escape_sequence_idx = 0
      
      csize = 1
      dsize = 1
        
      if ch&0xc0 == 0xc0:
        csize = 1
        dsize = pdeck.get_utf8_width(self.chars[i:i+3])
        org_numchar = numchar
        org_numdchar = numdchar
      elif ch&0xc0 == 0x80:
        csize = 0
        dsize = 0
        self.bcmap.append(org_numchar+1)
        self.bdmap.append(org_numdchar+1)
        continue
      elif ch == 0x9:
        csize = 1
        dsize = self.tab_size - (numdchar % self.tab_size)
        tab_found = True
      elif ch == 0x1b:
        csize = 0
        dsize = 0
        escape_sequence_idx = 1
        org_numchar = numchar-1
        org_numdchar = numdchar-1
        self.bcmap.append(org_numchar)
        self.bdmap.append(org_numdchar)
        continue
      elif escape_sequence_idx == 1:
        csize = 0
        dsize = 0
        if ch == ord('['):
          escape_sequence_idx += 1
        else:
          escape_sequence_idx = 0
        self.bcmap.append(org_numchar)
        self.bdmap.append(org_numdchar)
        continue
      elif escape_sequence_idx > 1:
        csize = 0
        dsize = 0
        if ch >= ord('a') and ch  <= ord('z'):
          escape_sequence_idx = 0
        elif ch >= ord('A') and ch <= ord('A'):
          escape_sequence_idx = 0
        else:
          escape_sequence_idx += 1
        self.bcmap.append(org_numchar)
        self.bdmap.append(org_numdchar)
        continue


      numchar += csize
      numdchar += dsize
      
      if last_numchar != numchar:
        while csize > 0:
          self.cbmap.append(i)
          csize -= 1
      if last_numdchar != numdchar:
        while dsize > 0:
          self.dbmap.append(i)
          dsize -= 1
        
      self.bcmap.append(last_numchar)
      self.bdmap.append(last_numdchar)
      last_numchar = numchar
      last_numdchar = numdchar
      
    #print(self.cbmap)  
    #print(self.dbmap)  
    self.len : int = numchar
    
    # Build ex_chars (tab-expanded version) if needed
    if tab_found:
      self.tab_detected = True
      self.scanned = True
      ex_chars = bytearray()
      for i, ch in enumerate(self.chars):
        if ch == 0x9:
          d_pos = self.bdmap[i]
          dsize = self.tab_size - (d_pos % self.tab_size)
          ex_chars.extend(b' ' * dsize)
        else:
          ex_chars.append(ch)
      self.ex_chars = ex_chars
      self.ex_len = len(self.ex_chars)
    else:
      self.ex_chars = self.chars
      self.ex_len = self.len
      self.tab_detected = False
      
    self.updated = True
  
  def get_len(self):
    if not self.updated: #self.scanned:
      self.update()
    return self.len
 
  def get_ex_chars(self):
    if not self.updated: #self.scanned:
      self.update()
    if self.tab_detected:
      return self.ex_chars
    else:
      return self.chars

  def at(self, start):
    if not self.updated:
      self.update()
    if start < 0:
      start = len(self.cbmap) + start
    if start >= len(self.cbmap):
      return bytearray()
    if len(self.cbmap) > start+1:
      atend = self.cbmap[start+1]
    elif len(self.cbmap) == start+1:
      return self.chars[self.cbmap[start]:]
    else:
      atend = self.cbmap[start] + 1
    return self.chars[self.cbmap[start]:atend]
    
  def substr(self, start, end):
    if start == end:
      return bytearray()

    if not self.updated:
      self.update()
    #print(f'substr {start} {end}')
    if start >= len(self.cbmap):
      return bytearray()
    if end < 0:
      end = len(self.cbmap) + end + 1
    
    if end >= len(self.cbmap):
      endat = len(self.chars)
    else:
      endat = self.cbmap[end]
      
    #if self.chars[endat]&0xc0 == 0xc0:
    #  endat += 1
    #  while self.chars[endat]&0xc0 == 0x80:
    #    endat += 1
    startat = 0 if start == 0 else self.cbmap[start]
    return self.chars[startat:endat]
    
  def insert_str(self, at, str):
    if not self.updated:
      self.update()
    if type(str) == str:
      str = str.encode("utf-8")
    #print(self.cbmap)
    newchars = self.substr(0,at)
    newchars.extend(str)
    newchars.extend(self.substr(at,-1))
    self.chars = newchars
    #print(self.chars)
    #arr = [ self.sub[:at], str, self.chars[at:] ]
    #print(arr)
    #self.chars = "".join(arr)
    self.update()

  def update_str(self, str):
    if not isinstance(self.chars, bytearray):
      raise Exception('chars must be bytearray')
    self.chars = str
    self.update()

  def delete_str(self, at, length):
    newchars = self.substr(0,at)
    newchars.extend(self.substr(at+length, -1))
    self.chars = newchars
    self.update()

  def erase_to_the_end(self,c):
    self.chars = self.substr(0,c)
    self.update()

  #Obsoluted
  def get_expanded_chars(self):
    if not self.updated:
      self.update()
    total = 0
    out = bytearray()
    for ch in self.chars:
      if ch == 0x9:
        #print("tab detected\n")
        self.tab_detected = True
        size = self.tab_size - (total % self.tab_size)
        total += size
        while size > 0:
          out.extend(b' ')
          size -= 1
      else:
        total += 1
        out.append(ch)
    return out
    

  def expand(self, start, at):
    if not self.updated:
      self.update()
    # It will return the number with tab-expanded
    #if not self.tab_detected:
    #  return at - start
    if self.len == 0:
      return 0
    if at >= len(self.cbmap):
      return self.bdmap[-1]+1 - self.bdmap[self.cbmap[start]]
      #print(f'expand: out of range {at}, {len(self.cbmap)}')
    return self.bdmap[self.cbmap[at]] - self.bdmap[self.cbmap[start]]
  
  def dpos_to_cpos(self, at):
    if not self.updated:
      self.update()
    if len(self.bcmap) == 0:
      return 0
    if len(self.dbmap) <= at:
      return self.bcmap[-1]
    return self.bcmap[self.dbmap[at]];
         
  def cpos_to_dpos(self, at, overflow = False):
    if not self.updated:
      self.update()
    if self.len == 0:
      return 0
    if at == -1:
      return self.bdmap[-1]
    if at >= len(self.cbmap):
      if overflow:
        return self.bdmap[-1] + 1
      else:
        return self.bdmap[-1]
    return self.bdmap[self.cbmap[at]];

  # from start(file position), count expanded chars to "at" position (expanded position, and return file position of "at".
  def expanded_to_pos(self, start, at):
    if not self.updated:
      self.update()
    # It will return the number with tab-expanded
    #if not self.tab_detected:
    #  return start + at

    if self.len == 0:
      return 0
    #print(f"s {start},{at}  {self.len}")
    if start >= len(self.cbmap):
      start = len(self.cbmap) - 1
    d_start = self.bdmap[self.cbmap[start]]
    if len(self.dbmap) <= d_start + at:
      return self.len
    if d_start + at < 0:
      return 0
    b_end = self.dbmap[d_start + at]
    return self.bcmap[b_end]

  def expanded_to_pos_with_d(self, start: int, at: int):
    if not self.updated:
      self.update()
    if int(self.len) == 0:
      return (0,0)
    #print(f"s {start},{at}  {self.len}")
    if start >= len(self.cbmap):
      start = len(self.cbmap) - 1
    d_start = self.bdmap[self.cbmap[start]]
    if len(self.dbmap) <= d_start + at:
      return (self.len, self.bdmap[-1]+1-d_start)
    if d_start + at < 0:
      return None
    b_end = self.dbmap[d_start + at]
    return (self.bcmap[b_end], b_end)

  def search(self, c, query, direction = 1, sensitive = False):
    if direction == 1:
      if c == 0:
        searched_string = self.chars
      else:  
        searched_string = self.substr(c,-1)
    else:
      if c != -1:
        c+=len(query)
        searched_string = self.substr(0,c)
      else:
        c = len(self.chars)
        searched_string = self.chars
        
      c = 0 if c == -1 else 0
    searched_string = searched_string.decode('utf-8')
    searched_string_org = searched_string
    # Case sensitive when query has upper cases
    if not sensitive and query.lower() == query:
      searched_string = searched_string.lower()

    if direction == 1:
      result = searched_string.find(query)
    else:
      result = searched_string.rfind(query)

    if result == -1:
      return (None, None)
    # Returns the position of the result and the matched string
    return (result + c, searched_string_org[result:result+len(query)])

if pdeck_enabled:
  class screen_interface:
    def __init__(self, vs):
      self.v = vs.v
      self.background_update = None

    def poll(self):
      return self.v.poll()

    def print(self, str):
      self.v.print(str)

    def read(self, n):
      ret = None
      while True:
        ret = self.v.read_nb(1)
        if ret:
          if ret[0] > 0:
            break
        if self.v.active:
          
          if self.background_update:
            if not self.background_update():
              pdeck.delay_tick(7)
          else:
            pdeck.delay_tick(7)
          #time.sleep_ms(10)
        else:
          pdeck.delay_tick(100)
          #time.sleep_ms(200)
      keys = ret[1].encode('ascii')
      return keys

    def get_terminal_size(self):
      return self.v.get_terminal_size()

    def set_raw_mode(self, mode):
      self.v.print(el.raw_mode(mode))
else:
  class screen_interface:
    def __init__(self, vs):
      self.fd = sys.stdin.fileno()
      self.org_term = termios.tcgetattr(self.fd)
    def poll(self):
      return False
    def print(self, str):
      sys.stdout.write(str)
      sys.stdout.flush()
    def read(self, n):
      return sys.stdin.read(n).encode('ascii')

    def get_terminal_size(self):
      import os
      size = os.get_terminal_size()

      return (size.columns, size.lines)

    def set_raw_mode(self, mode):
      if mode == True:
        new = termios.tcgetattr(self.fd)
        new[0] &= ~(termios.BRKINT | termios.ICRNL | termios.INPCK | termios.ISTRIP | termios.IXON)
        new[1] &= ~(termios.OPOST);
        new[2] |= (termios.CS8);
        new[3] &= ~(termios.ECHO | termios.ICANON | termios.IEXTEN | termios.ISIG);

        termios.tcsetattr(self.fd,termios.TCSANOW, new)
      else:
        new = self.org_term
        termios.tcsetattr(self.fd,termios.TCSANOW, new)
      return

def main(vs, args_in):
  # Get a virtual screen (No argument = current)
  v = screen_interface(vs)
  parser = argparse.ArgumentParser( description = "pem")
  parser.add_argument("filename")
  if len(args_in) > 1:
    args = parser.parse_args(args_in[1:])
  else:
    class obj: pass
    args = obj()
    args.filename = None
    pass
    #v.print("Specify filename\r\n")
    #return

  try: 
    e = editor(v)
    e.open(args.filename)
    e.setup_screen()
    e.refresh_screen()
    while True:
      ret = e.process_key()
      if ret == 1:
        break
      e.refresh_screen()
    e.exit()
  except OSError:
    v.print("File open error\n")
  finally:
    v.print(el.reset_font_color())
    v.set_raw_mode(False)
    v.print(el.erase_screen())
    #print("exiting..")
    v.print('finished\n')

if not pdeck_enabled:
  if __name__ == "__main__":
    main(None, sys.argv)
