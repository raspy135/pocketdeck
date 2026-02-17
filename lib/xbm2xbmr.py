#!/usr/bin/env python3
import sys
import re
import re_findall
import struct
import argparse

vs = None
def print_vs(str):
  print(str, file=vs)
def xbm_to_xbmr(input_path, output_path):
    try:
        with open(input_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print_vs(f"Error reading XBM file: {e}")
        return 1

    #print_vs(content)

    # Extract width and height
    width_match = re.search(r'#define\s+\w+_width\s+(\d+)', content)
    height_match = re.search(r'#define\s+\w+_height\s+(\d+)', content)
    #print(f"{width_match} ")
    if not width_match or not height_match:
        print_vs("Error: Could not find width/height in XBM file.")
        return 1
        
    width = int(width_match.group(1))
    height = int(height_match.group(1))

    # Extract hex data
    # Standard XBM data looks like: static unsigned char name_bits[] = { 0x00, 0x01, ... };
    data_match = re.search(r'\{([\s\w,]+?)\}', content)
    if not data_match:
        print_vs("Error: Could not find data array in XBM file.")
        return 1

    # Convert hex/decimal strings to bytes
    raw_data_str = data_match.group(1)
    regex = re.compile('0x[0-9a-fA-F]+|\d+')
    values = re_findall.findall(regex, raw_data_str)
    #print_vs(f"{values}")
    # Standard XBM is LSB-first. We need MSB-first.
    processed_data = bytearray()
    for val in values:
        # Convert to int (handles 0x hex and decimal)
        byte_val = int(val, 0)
        
        # Reverse bits (LSB first -> MSB first)
        # bin(byte_val)[2:].zfill(8)[::-1] converts 01010110 -> 01101010 -> int 
        # Bit reversal
        reversed_byte = int(''.join(reversed('{:08b}'.format(byte_val))),2)
        processed_data.append(reversed_byte)

    # Prepare header
    # Offset 0: int16_t Reserved (0)
    # Offset 2: int16_t Number of frames (Fixed at 1 for XBM)
    # Offset 4: int16_t Width
    # Offset 6: int16_t Height
    header = struct.pack('<hhhh', 0, 1, width, height)
    
    full_data = header + processed_data

    try:
        with open(output_path, 'wb') as f:
            f.write(full_data)
        print_vs(f"Successfully converted {input_path} to {output_path}")
        print_vs(f"Frames: 1, Size: {width}x{height}")
    except Exception as e:
        print_vs(f"Error writing output file: {e}")
        return 1

def main(vs_in, args_in):
    global vs
    vs = vs_in
    parser = argparse.ArgumentParser(description='Convert standard XBM to XBMR format (flipping bit order).')
    parser.add_argument('input', help='Input XBM file')
    parser.add_argument('output', help='Output XBMR file')
    
    args = parser.parse_args(args_in[1:])
    xbm_to_xbmr(args.input, args.output)
