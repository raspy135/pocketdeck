import pdeck
import uQR
import esclib

# Programmatic example of using uQR to generate and display a QR code

def display_matrix(matrix):
  # Print text representation to the REPL/terminal console
  print("\nQR Code Text representation:")
  for row in matrix:
    line = "".join(["██" if cell else "  " for cell in row])
    print(line)

class QRCodeApp:
  def __init__(self, text, vs):
    self.vs = vs
    self.v = vs.v
    
    # 1. Create a QRCode instance with desired ECC level
    qr = uQR.QRCode(error_correction=uQR.ERROR_CORRECT_M)
    
    # 2. Add text/url data
    qr.add_data(text)
    
    # 3. Compile data and obtain the modules matrix
    self.matrix = qr.get_matrix()
    self.N = len(self.matrix)
    
    # 4. Scale to fit screen
    self.box_size = 240 // self.N
    self.qr_pixels = self.N * self.box_size
    self.margin_x = (400 - self.qr_pixels) // 2
    self.margin_y = (240 - self.qr_pixels) // 2

  def update(self, e):
    # Frame callback: draws the QR code on the display
    v = self.v
    
    # Draw background quiet zone
    v.set_draw_color(1)
    v.draw_box(self.margin_x, self.margin_y, self.qr_pixels, self.qr_pixels)
    
    # Draw dark blocks
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

def main(vs, args):
  text = "https://shop.nunomo.net"
  if len(args) > 1:
    text = args[1]
    
  print("Generating QR Code for: {}".format(text), file=vs)
  
  # Initialize QR Generator demo
  demo = QRCodeApp(text, vs)
  
  # Optional: Display ascii preview on terminal/REPL
  #display_matrix(demo.matrix)
  
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
