
import pdeck

def init_custom(km):
  # If you want to change default keymap, edit km.map variable
  
  # Custom feature example
  km.clipboard_to_yank = clipboard_to_yank

  # Custom keymap for custom feature
  km.custom_map['clipboard_to_yank'] = [ b'\x03v' ] 
  
# Copy system clipboard to Yank Buffer
# This is useful when the size of clipboard is big.
def clipboard_to_yank(editor):
  editor.yankbuf.reset_buf()
  str = pdeck.clipboard_paste().decode('utf-8')
  editor.yankbuf.add_str(str)
  editor.set_message("Clipboard copied to yank buffer")

