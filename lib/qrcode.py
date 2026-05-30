import pdeck
import esclib
import uQR
import argparse

class QRApp:
  def __init__(self, vs, text, ecc_str, size_val):
    self.vs = vs
    self.v = vs.v
    self.text = text
    self.ecc_str = ecc_str
    self.size_val = size_val
    self.error = None
    self.matrix = None
    self.box_size = 4
    
    ecc_map = {
      'L': uQR.ERROR_CORRECT_L,
      'M': uQR.ERROR_CORRECT_M,
      'Q': uQR.ERROR_CORRECT_Q,
      'H': uQR.ERROR_CORRECT_H
    }
    ecc_level = ecc_map.get(ecc_str.upper(), uQR.ERROR_CORRECT_M)
    
    try:
      # Create QR code with border=4 (standard quiet zone)
      qr = uQR.QRCode(version=None, error_correction=ecc_level, box_size=1, border=4)
      qr.add_data(text)
      self.matrix = qr.get_matrix()
      self.N = len(self.matrix)
      
      # Center and scale to fit 400x240 screen
      max_pixels = 240
      if size_val is not None and size_val > 0:
        self.box_size = size_val
      else:
        self.box_size = max(1, max_pixels // self.N)
        
      self.qr_pixels = self.N * self.box_size
      self.margin_y = (240 - self.qr_pixels) // 2
      self.margin_x = (400 - self.qr_pixels) // 2
    except Exception as e:
      self.error = str(e)
      
  def update(self, e):
    v = self.v
    
    if self.error:
      v.set_font("u8g2_font_profont15_mf")
      v.set_draw_color(1)
      v.draw_str(10, 40, "QR Code Error:")
      v.draw_str(10, 60, self.error)
      v.finished()
      return
      
    # Draw background (white box covering the QR code + border area)
    v.set_draw_color(1)
    v.draw_box(self.margin_x, self.margin_y, self.qr_pixels, self.qr_pixels)
    
    # Draw black modules
    v.set_draw_color(0)
    for r in range(self.N):
      for c in range(self.N):
        if self.matrix[r][c]:
          v.draw_box(
            self.margin_x + c * self.box_size,
            self.margin_y + r * self.box_size,
            self.box_size,
            self.box_size
          )
    v.finished()

def main(vs, args_in):
  parser = argparse.ArgumentParser(description="Generate and display a QR Code centered on screen")
  parser.add_argument("text", nargs="*", help="Text/URL to encode. If omitted, reads clipboard")
  parser.add_argument("-c", "--clipboard", action="store_true", help="Read from clipboard")
  parser.add_argument("-e", "--ecc", default="M", help="Error correction: L, M, Q, H (default: M)")
  parser.add_argument("-s", "--size", type=int, default=None, help="Pixel size per module (default: auto)")
  
  args = parser.parse_args(args_in[1:])
  
  # Validation of ECC level
  ecc = args.ecc.upper()
  if ecc not in ("L", "M", "Q", "H"):
    print("Error: Invalid ECC level. Use L, M, Q, or H.", file=vs)
    return
    
  text = ""
  if args.clipboard:
    text = pdeck.clipboard_paste()
    if not text:
      print("Clipboard is empty!", file=vs)
      return
  elif args.text:
    text = " ".join(args.text)
  else:
    # Fallback to clipboard if no arguments are provided
    text = pdeck.clipboard_paste()
    if not text:
      print("Usage: qrcode [text] or use -c for clipboard. (Clipboard is currently empty)", file=vs)
      return
      
  # Clear screen and cursor
  el = esclib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  
  app = QRApp(vs, text, ecc, args.size)
  v.callback(app.update)
  
  # Wait for key press to dismiss
  vs.read(1, 50)
  
  # Clean up
  v.callback(None)
  v.print(el.display_mode(True))
