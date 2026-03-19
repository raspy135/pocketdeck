
resume_last_file = True

ext_keys = [ b'\x18' ]
map = {
  'quit': [ b'\x18\x03' ],
  'save': [ b'\x18\x13' ],
  'open': [ b'\x18\x06' ],
  'close': [ b'\x18k' ],
  'switch': [ b'\x18b' ],
  'kill': [ b'\x0b' ],
  'delete': [ b'\x04', b'\x1b[3~'],  
  'search': [ b'\x13' ],
  'rev_search': [ b'\x12'],
  'ime_jp_toggle': [ b'\x1b`',b'\x1b~'],
  'replace': [ b'\x1b%' ],
  'mark': [ b'\x1b\x20' ],
  'walk_forward': [ b'\x1b\x27' ],
  'walk_back': [ b'\x1b;' ],
  'goto_line': [ b'\x1bg'],
  'ref_def': [ b'\x1b.' ],
  'ref_sym': [ b'\x1b/' ],
  'top': [ b'\x1b<' ],
  'bottom': [ b'\x1b>' ],
  'recover_yank': [ b'\x1by' ],
  'top_line': [ b'\x01', b'\x1b[1~'],
  'bottom_line': [ b'\x05', b'\x1b[4~' ],
  'yank': [ b'\x19' ],
  'redraw': [ b'\x0c' ],
  'up' : [b'\x1b[A', b'\x10'],
  'down': [b'\x1b[B', b'\x0e'],
  'left': [b'\x1b[D', b'\x02'],
  'right': [b'\x1b[C', b'\x06'],
  'delete': [ b'\x1b[3~', b'\x04'],
  'bs': [ b'\x08'],
  'enter': [ b'\r',b'\x0a'],
  'pagedown': [b'\x1b[6~'],
  'pageup': [b'\x1b[5~'],
  
}

