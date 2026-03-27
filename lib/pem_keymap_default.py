resume_last_file = True

ext_keys = [ b'\x18',b'\x03' ]

custom_map = {
  'dic' : [ b'\x03r' ],
}

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

# ------ custom command examples ------

# dic command executes gpt command to get the meaning of the word at the current cursor then copy the result to yank buffer.

def dic(editor):

  # get symbol at the cursor
  # use custom search_list (separator)
  
  search_list = ( b" ",b"(",b"+",b"-",b"~",b"=",b">",b"<",b"?",b",",b"{",b"}",b"[",b"]",b"|")
  
  pos, sym = editor.file.get_symbol(editor.file_row, editor.file_col,search_list)

  if not sym:
    editor.set_message("Failed to get a symbol")
    return

  # execute gpt command using mockup stream object to redirect the output
  
  import gpt
  import mock_stream
  import pdeck
  st = mock_stream.mock_stream(b'')
  
  pdeck.led(1,60)

  try:
    gpt.main(st, ['gpt', '-n', '-nf', f"What does '{sym}' mean? Answer in short. Do not use syntax highlighting such as **bold**. Just print its meaning, you don't need to start with 'the word means'"])
  except Exception as e:
    print(e)

  pdeck.led(1,0)

  editor.yankbuf.reset_buf()
  editor.yankbuf.add_str(st.get_wbuffer().decode('utf-8'))
  editor.set_message("The result was stored in yank buffer")


