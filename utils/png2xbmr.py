import os
import sys
import struct
import argparse
from PIL import Image

def png_to_xbmr(input_path, output_path, export_xbm=False, bit_swap=False):
    try:
        img = Image.open(input_path)
    except Exception as e:
        print(f"Error opening image: {e}")
        sys.exit(1)

    width, height = img.size
    
    # Check if we have transparency
    has_alpha = False
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        has_alpha = True
        
    num_frames = 2 if has_alpha and not (export_xbm or bit_swap) else 1
    
    def get_frame_data(image_channel, lsb_first=False):
        """Convert a single monochrome channel to bit pattern."""
        pixels = image_channel.load()
        data = bytearray()
        
        for y in range(height):
            current_byte = 0
            bit_pos = 0 if lsb_first else 7
            for x in range(width):
                # Using 128 as threshold for monochrome
                pixel_val = pixels[x, y]
                if pixel_val > 127: # White / opaque
                    current_byte |= (1 << bit_pos)
                
                if lsb_first:
                    bit_pos += 1
                    if bit_pos > 7:
                        data.append(current_byte)
                        current_byte = 0
                        bit_pos = 0
                else:
                    bit_pos -= 1
                    if bit_pos < 0:
                        data.append(current_byte)
                        current_byte = 0
                        bit_pos = 7
            
            # Append last byte of the row if not full
            if (lsb_first and bit_pos != 0) or (not lsb_first and bit_pos != 7):
                data.append(current_byte)
        return data

    if export_xbm or bit_swap:
        # XBM format (C header)
        # Standard XBM is LSB-first, bit_swap=True means MSB-first
        monochrome_img = img.convert('L')
        lsb_first = not bit_swap
        data = get_frame_data(monochrome_img, lsb_first=lsb_first)
        
        # Get basename for C identifiers
        base_name = os.path.splitext(os.path.basename(output_path))[0]
        # Replace non-alphanumeric characters with underscores
        base_name = "".join([c if c.isalnum() else "_" for c in base_name])
        
        xbm_content = f"#define {base_name}_width {width}\n"
        xbm_content += f"#define {base_name}_height {height}\n"
        xbm_content += f"static unsigned char {base_name}_bits[] = {{\n"
        
        hex_data = []
        for i, b in enumerate(data):
            hex_data.append(f"0x{b:02x}")
            if (i + 1) % 12 == 0:
                hex_data[-1] += ","
                hex_data.append("\n  ")
            elif i < len(data) - 1:
                hex_data[-1] += ", "
        
        xbm_content += "  " + "".join(hex_data)
        xbm_content += "\n};\n"
        
        try:
            with open(output_path, 'w') as f:
                f.write(xbm_content)
            mode_str = "Bit-swapped XBM" if bit_swap else "Standard XBM"
            print(f"Successfully converted {input_path} to {output_path} ({mode_str})")
            print(f"Size: {width}x{height}")
        except Exception as e:
            print(f"Error writing output file: {e}")
            sys.exit(1)
            
    else:
        # Custom XBMR format (Binary, MSB-first)
        header = struct.pack('<hhhh', 0, num_frames, width, height)
        
        monochrome_img = img.convert('L')
        frame1 = get_frame_data(monochrome_img, lsb_first=False)
        
        full_data = header + frame1
        
        if has_alpha:
            if img.mode == 'RGBA':
                alpha = img.split()[-1]
            elif img.mode == 'LA':
                alpha = img.split()[-1]
            else: # Palette with transparency
                alpha = img.convert('RGBA').split()[-1]
                
            frame2 = get_frame_data(alpha, lsb_first=False)
            full_data += frame2

        try:
            with open(output_path, 'wb') as f:
                f.write(full_data)
            print(f"Successfully converted {input_path} to {output_path}")
            print(f"Frames: {num_frames}, Size: {width}x{height}")
        except Exception as e:
            print(f"Error writing output file: {e}")
            sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Convert PNG to XBMR or standard XBM format.')
    parser.add_argument('input', help='Input PNG file')
    parser.add_argument('output', help='Output file')
    parser.add_argument('--xbm', '-x', action='store_true', help='Export as standard XBM (C header)')
    parser.add_argument('--xbms', '-s', action='store_true', help='Export as bit-swapped XBM (C header, MSB-first)')
    
    args = parser.parse_args()
    png_to_xbmr(args.input, args.output, export_xbm=args.xbm, bit_swap=args.xbms)
