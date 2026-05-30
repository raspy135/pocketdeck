import pdeck
import uQR
import esclib
import argparse

# Programmatic example of using uQR to generate and display a QR code

def display_matrix(matrix):
  # Print text representation to the REPL/terminal console
  print("\nQR Code Text representation:")
  for row in matrix:
    line = "".join(["██" if cell else "  " for cell in row])
    print(line)

class QRCodeLib:
  def __init__(self, text, v, size):
    self.v = v
    self.size = size
    
    # 1. Create a QRCode instance with desired ECC level
    qr = uQR.QRCode(error_correction=uQR.ERROR_CORRECT_M)
    
    # 2. Add text/url data
    qr.add_data(text)
    
    # 3. Compile data and obtain the modules matrix
    self.matrix = qr.get_matrix()
    self.N = len(self.matrix)
    
    # 4. Scale to fit within the square size boundary
    self.box_size = size // self.N
    if self.box_size < 1:
      self.box_size = 1
    self.qr_pixels = self.N * self.box_size

  def draw_qr(self, x, y):
    v = self.v
    # Draw background quiet zone (white box)
    v.set_draw_color(1)
    v.draw_box(x, y, self.qr_pixels, self.qr_pixels)
    
    # Draw dark blocks
    v.set_draw_color(0)
    for r in range(self.N):
      for c in range(self.N):
        if self.matrix[r][c]:
          v.draw_box(
            x + c * self.box_size,
            y + r * self.box_size,
            self.box_size,
            self.box_size
          )

class QRCodeApp:
  def __init__(self, text, vs, size):
    self.vs = vs
    self.v = vs.v
    self.lib = QRCodeLib(text, self.v, size)

  def update(self, e):
    # Center QR code on the 400x240 screen
    x = (400 - self.lib.qr_pixels) // 2
    y = (240 - self.lib.qr_pixels) // 2
    self.lib.draw_qr(x, y)
    self.v.finished()

def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='ChatGPT query' )
  parser.add_argument('content', nargs='*',help='Text for QR code')
  parser.add_argument('-c', '--clipboard', action='store_true', help='Generate QR code from clipboard')
  args = parser.parse_args(args_in[1:])

  text = "IO13 and IO6"
  if args.clipboard:
    text = pdeck.clipboard_paste().decode("utf-8")
  else:    
    if not args.content:
      print("Specify text to convert", file=vs)
      return
    #print(args.content)
    #text = ' '.join(args.content)
    print(text)
    
  print("Generating QR Code for: {}".format(text), file=vs)
  
  # Initialize QR App with maximum size of 240 (fits vertically on screen)
  demo = QRCodeApp(text, vs, 240)
  
  # Optional: Display ascii preview on terminal/REPL
  #display_matrix(demo.lib.matrix)
  
  # Display on screen using virtual screen callback
  el = esclib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  
  # Register callback for frame updates
  v.callback(demo.update)
  
  print("\nQR code generated and displayed on screen.", file=vs)
  print("Press any key to exit.", file=vs)
  
  # Wait for key press to exit
  vs.read(1)
  
  # Clean up callback and restore terminal settings
  v.callback(None)
  v.print(el.display_mode(True))
