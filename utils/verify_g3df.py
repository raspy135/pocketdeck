import struct
import array
import os
import sys

def verify(filename):
  if not os.path.exists(filename):
    print(f"Error: File '{filename}' not found.")
    return

  size = os.path.getsize(filename)
  print(f"Inspecting G3DF: {filename} ({size} bytes)")
  
  with open(filename, 'rb') as f:
    header = f.read(20)
    if len(header) < 20 or header[:4] != b'G3DF':
      print("Error: Invalid G3DF magic!")
      return
    
    magic, v1, v2, v3, v4, count, index_off, flags = struct.unpack('<4s4BIII', header)
    print(f"Magic: {magic.decode()}")
    print(f"Version: {v1}")
    print(f"Features: {v2:02x}{v3:02x}{v4:02x}")
    print(f"Glyph Count: {count}")
    print(f"Index Offset: {index_off}")
    
    f.seek(index_off)
    directory = []
    for i in range(count):
      entry = f.read(12)
      if len(entry) < 12:
        print("Error: Directory truncated!")
        break
      cid, off, adv, res = struct.unpack('<IIHH', entry)
      directory.append({'id': cid, 'off': off, 'adv': adv})
    
    print("\nCharacter Directory:")
    for d in directory:
      char = chr(d['id']) if 32 <= d['id'] <= 126 else f"#{d['id']}"
      f.seek(d['off'])
      mesh_header = f.read(8)
      if len(mesh_header) < 8:
        print(f"  [{char}] @ {d['off']}: ERROR: Unexpected EOF reading mesh header")
        continue
        
      num_f, num_v = struct.unpack('<II', mesh_header)
      print(f"  [{char}] @ {d['off']}: Verts:{num_v}, Faces:{num_f}, Adv:{d['adv']}")
      
      # Basic check on data sizes
      expected_size = 8 + (num_v * 3 * 4) + (num_f * 3 * 2) + (num_f * 3 * 4)
      # 8 (header) + verts (float*3) + indices (uint16*3) + normals (float*3)
      
      if d['off'] + expected_size > size:
        print(f"    WARNING: Mesh data for '{char}' exceeds file size!")
      
      if num_v == 0 or num_f == 0:
        print(f"    WARNING: Glyph '{char}' has NO geometry (is it a space?)")

if __name__ == "__main__":
  fname = sys.argv[1] if len(sys.argv) > 1 else "fonts/mirandasans.g3df"
  verify(fname)
