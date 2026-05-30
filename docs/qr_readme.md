# QR Code Generator for Pocket Deck

Pocket Deck includes a built-in QR Code Generator utility and a library to generate and display QR codes directly on the monochrome LCD screen.

---

## Command Line Utility

The `qrcode` command generates a QR Code from text or URL inputs and displays it centered on the display. It auto-scales to fit the screen.

### Syntax

```bash
qrcode [text...] [options]
```

If no arguments are provided, `qrcode` will automatically fallback to reading content from the system clipboard.

### Options

| Option | Shorthand | Description |
|---|---|---|
| `--clipboard` | `-c` | Read text/URL from the clipboard instead of command arguments. |
| `--ecc <level>` | `-e <level>` | Error correction level: `L`, `M`, `Q`, `H` (default: `M`). |
| `--size <pixels>`| `-s <pixels>`| Manual pixel size per module (default: auto-calculated). |

### CLI Examples

1. **Generate from argument string:**
   ```bash
   qrcode https://shop.nunomo.net
   ```

2. **Generate from multi-word text string:**
   ```bash
   qrcode "Hello, this is a message from Pocket Deck"
   ```

3. **Generate from current clipboard contents:**
   ```bash
   qrcode -c
   ```

4. **Generate using high error correction level (H):**
   ```bash
   qrcode https://shop.nunomo.net -e H
   ```

---

## Programmatic API (`uQR` Library)

Developers can use the `uQR` module to generate QR codes programmatically inside custom applications.

### Class: `uQR.QRCode`

#### Constructor
```python
import uQR
qr = uQR.QRCode(version=None, error_correction=uQR.ERROR_CORRECT_M, box_size=1, border=4)
```
- `version`: Specify an integer from 1 to 40 to force a version size. Pass `None` to auto-fit the data.
- `error_correction`: Error correction constant:
  - `uQR.ERROR_CORRECT_L` (7% recovery)
  - `uQR.ERROR_CORRECT_M` (15% recovery, default)
  - `uQR.ERROR_CORRECT_Q` (25% recovery)
  - `uQR.ERROR_CORRECT_H` (30% recovery)
- `border`: The thickness of the quiet zone/border around the QR code in modules (default: 4).

#### Methods

- **`qr.add_data(data)`**: Appends a string of text or URL data to the QR code.
- **`qr.get_matrix()`**: Compiles the data and returns a 2D list of booleans representing the QR matrix (`True` for dark modules, `False` for light modules).

### Code Example

Below is a minimal script demonstrating how to generate a QR matrix and draw it on the Pocket Deck display using a frame callback:

```python
import pdeck
import uQR

def main(vs, args):
    # 1. Initialize QRCode
    qr = uQR.QRCode(error_correction=uQR.ERROR_CORRECT_M)
    qr.add_data("https://shop.nunomo.net")
    
    # 2. Get the matrix (2D list of booleans)
    matrix = qr.get_matrix()
    N = len(matrix)
    
    # 3. Calculate positioning
    box_size = 240 // N
    qr_pixels = N * box_size
    margin_x = (400 - qr_pixels) // 2
    margin_y = (240 - qr_pixels) // 2

    # 4. Define the drawing callback
    def draw_callback(e):
        v = pdeck.vscreen()
        # Draw quiet zone (white background box)
        v.set_draw_color(1)
        v.draw_box(margin_x, margin_y, qr_pixels, qr_pixels)
        
        # Draw dark blocks
        v.set_draw_color(0)
        for r in range(N):
            for c in range(N):
                if matrix[r][c]:
                    v.draw_box(margin_x + c*box_size, margin_y + r*box_size, box_size, box_size)
        v.finished()

    # 5. Setup display
    v = vs.v
    v.callback(draw_callback)
    
    # 6. Wait for a key press to exit
    vs.read(1, 50)
    v.callback(None)
```
