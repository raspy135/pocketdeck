import time
import pdeck_utils
import pdeck

def init_custom(km):
  km.speech_to_text = stt
  km.toggle_checkbox = toggle_checkbox
  km.custom_map['toggle_checkbox'] = [b'\x03l']
  km.custom_map['speech_to_text'] = [b'\x03s']
  
def stt(editor):
  import stt
  import mock_stream
  import pdeck
  if not pdeck.wifi_connected:
    editor.set_message("No Wifi")
    return
  st = mock_stream.mock_stream(b'', editor.v)
  editor.set_message("Any key to stop record")
  editor.refresh_screen()
  
  pdeck.led(2,40)
  stt.main(st,['stt','-s','-d','60'])
  pdeck.led(2,0)

  newstr = st.get_wbuffer().decode('utf-8')
  newstr = newstr.replace("\r\n", "\n").replace("\r", "\n")
  #print(newstr)
  editor.dmod = True
  lines = newstr.split('\n')
  lines = lines[1:]
  newstr = ' '.join(lines)
  row = editor.file.rows[editor.file_row]
  row.insert_str(editor.file_col, newstr)
  editor.file_col += len(newstr)
  editor.jump_to_position(editor.file_row, editor.file_col, -1)
  
  
  
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

