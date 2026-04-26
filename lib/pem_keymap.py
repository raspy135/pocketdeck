
import pdeck

def init_custom(km):
  # If you want to change default keymap, edit km.map variable
  
  # Custom feature example
  km.clipboard_to_yank = clipboard_to_yank
  km.today = today

  # Custom keymap for custom feature
  km.custom_map['clipboard_to_yank'] = [ b'\x03v' ] 
  km.custom_map['today'] = [ b'\x03d' ] 
  

# today command returns today's date.

import time
import pdeck_utils

def today(editor):
  t = time.gmtime(time.time() + 60*15*pdeck_utils.timezone)
  week_list = ("Mon", "Tue", "Wed" ,"Thu", "Fri", "Sat", "Sun" )
  format_date = f'<{t[0]:04}-{t[1]:02}-{t[2]:02} {week_list[t[6]]}>'
  row = editor.file.rows[editor.file_row]
  row.insert_str(editor.file_col, format_date)
  editor.file_col += len(format_date)
  editor.jump_to_position(editor.file_row, editor.file_col, -1)



# Copy system clipboard to Yank Buffer
# This is useful when the size of clipboard is big.
def clipboard_to_yank(editor):
  editor.yankbuf.reset_buf()
  str = pdeck.clipboard_paste().decode('utf-8')
  editor.yankbuf.add_str(str)
  editor.set_message("Clipboard copied to yank buffer")

