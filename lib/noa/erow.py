#
# erow -- one editable text row for the Pem editor (Pocket Deck)
# Copyright Nunomo LLC
#
# Split out of pem.py to keep that file smaller. `erow` models a single line of
# text and owns its byte<->char<->display-column maps. pem.py pulls the class
# back into its own namespace with `from erow import erow`, so every existing
# `erow(...)` call site is unchanged.
#
# `_hl_line` (per-line syntax highlighting) is left in pem.py and imported here.
# pem.py is always the entry point and defines `_hl_line` before it imports this
# module, so the import cycle resolves cleanly.

import array
import pdeck
from pem import _hl_line


class erow:
  def __init__(self, str, tab_size, w=200):
    self.chars = str
    self.w = w
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
    self.hl_mode = None
    self.hl_bytes = {}
    #self.update(True)

  def decode(self):
    return self.chars.decode('utf-8')

  def update(self, skip_tab_scan = False):
    self.hl_bytes = {}
    chars = self.chars
    n = len(chars)
    tab_size = self.tab_size
    # pre-allocate to max possible size; sliced to actual length at end
    # bmap stores char to byte offset info
    cbmap = array.array('h', b'\x00' * (n * 2))
    # cmap stores byte to char info
    bcmap = array.array('h', b'\x00' * (n * 2))
    # dmap stores bytes to display width (utf-8 chars has size of 2, and tab)
    bdmap = array.array('h', b'\x00' * (n * 2))
    # dmap stores display width to bytes; tab expands so worst case n*tab_size
    dbmap = array.array('h', b'\x00' * (n * tab_size * 2))
    cbmap_len = 0
    bcmap_len = 0
    bdmap_len = 0
    dbmap_len = 0

    numchar = 0
    numdchar = 0
    last_numchar = 0
    last_numdchar = 0
    tab_found = False
    escape_sequence_idx = 0
    org_numchar = 0
    org_numdchar = 0
    for i in range(n):
      ch = chars[i]
      csize = 1
      dsize = 1

      if ch&0xc0 == 0xc0:
        csize = 1
        dsize = pdeck.get_utf8_width(chars[i:i+3])
        org_numchar = numchar
        org_numdchar = numdchar
      elif ch&0xc0 == 0x80:
        bcmap[bcmap_len] = org_numchar+1; bcmap_len += 1
        bdmap[bdmap_len] = org_numdchar+1; bdmap_len += 1
        continue
      elif ch == 0x9:
        csize = 1
        dsize = tab_size - (numdchar % tab_size)
        tab_found = True
      elif ch == 0x1b:
        escape_sequence_idx = 1
        org_numchar = numchar-1
        org_numdchar = numdchar-1
        bcmap[bcmap_len] = org_numchar; bcmap_len += 1
        bdmap[bdmap_len] = org_numdchar; bdmap_len += 1
        continue
      elif escape_sequence_idx == 1:
        if ch == 91:
          escape_sequence_idx += 1
        else:
          escape_sequence_idx = 0
        bcmap[bcmap_len] = org_numchar; bcmap_len += 1
        bdmap[bdmap_len] = org_numdchar; bdmap_len += 1
        continue
      elif escape_sequence_idx > 1:
        if ch >= 97 and ch <= 122:
          escape_sequence_idx = 0
        elif ch >= 65 and ch <= 65:
          escape_sequence_idx = 0
        else:
          escape_sequence_idx += 1
        bcmap[bcmap_len] = org_numchar; bcmap_len += 1
        bdmap[bdmap_len] = org_numdchar; bdmap_len += 1
        continue

      numchar += csize
      numdchar += dsize

      if last_numchar != numchar:
        while csize > 0:
          cbmap[cbmap_len] = i; cbmap_len += 1
          csize -= 1
      if last_numdchar != numdchar:
        while dsize > 0:
          dbmap[dbmap_len] = i; dbmap_len += 1
          dsize -= 1

      bcmap[bcmap_len] = last_numchar; bcmap_len += 1
      bdmap[bdmap_len] = last_numdchar; bdmap_len += 1
      last_numchar = numchar
      last_numdchar = numdchar

    self.cbmap = cbmap[:cbmap_len]
    self.bcmap = bcmap[:bcmap_len]
    self.bdmap = bdmap[:bdmap_len]
    self.dbmap = dbmap[:dbmap_len]
    self.len = numchar

    # Build ex_chars (tab-expanded version) if needed
    if tab_found:
      self.tab_detected = True
      self.scanned = True
      ex_chars = bytearray()
      ex_ap = ex_chars.append
      ex_ext = ex_chars.extend
      for i in range(n):
        ch = chars[i]
        if ch == 0x9:
          d_pos = bdmap[i]
          dsize = tab_size - (d_pos % tab_size)
          ex_ext(b' ' * dsize)
        else:
          ex_ap(ch)
      self.ex_chars = ex_chars
      self.ex_len = len(ex_chars)
    else:
      self.ex_chars = chars
      self.ex_len = self.len
      self.tab_detected = False

    self.updated = True
    self.update_hl_bytes()
    
  def update_hl_bytes(self):
    if not self.updated:
      self.update()
      return
      
    if self.hl_mode in ('md', 'py', 'c'):
      cur = 0
      while True:
        next_stop = self.expanded_to_pos(cur, self.w)
        #print(f"{idx}:{cur} {next_stop}, {self.get_len()}")
        # Highlight the tab-expanded display slice, not the raw chars: a literal
        # tab byte left in the output advances the display to its own tab stop,
        # misaligning everything after it. (cur is always < len here -- the loop
        # only continues while next_stop < len, and empty lines are never tabbed.)
        if self.tab_detected:
          d_start = self.bdmap[self.cbmap[cur]]
          seg = self.ex_chars[d_start:d_start + self.w]
        else:
          seg = self.substr(cur, next_stop)
        self.hl_bytes[cur] = _hl_line(seg, self.hl_mode)
        if next_stop >= self.get_len():
          break
        cur = next_stop
      

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
    # `str` shadows the builtin here, so the original `type(str) == str` never
    # matched; check against bytes/bytearray instead so a real str is encoded.
    # (MicroPython's bytearray.extend tolerates a str; CPython does not.)
    if not isinstance(str, (bytes, bytearray)):
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
