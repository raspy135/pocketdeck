import time
import pdeck_utils
import pdeck

def init_custom(km):
  km.toggle_checkbox = toggle_checkbox
  km.custom_map['toggle_checkbox'] = [b'\x03l']
  
def toggle_checkbox(editor):
  row = editor.file.rows[editor.file_row]
  ret = row.search(0,'[',1)
  if ret[0] == None:
    return
  checkbox = row.substr(ret[0],ret[0]+3)
  if len(checkbox) != 3:
    return
  if checkbox[2] != ord(']'):
    return
  if not checkbox[1] in b' Xx':
    return
  newchar = b" " if checkbox[1] != ord(" ") else b"X"
   
  newchars = row.substr(0,ret[0]) + b"[" + newchar + b"]" + row.substr(ret[0]+3,-1) 
  row.update_str(newchars)

