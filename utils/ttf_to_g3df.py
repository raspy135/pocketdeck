import os
import sys
import array
import math
import struct
import argparse

try:
  from fontTools.ttLib import TTFont
  from fontTools.pens.basePen import BasePen
except ImportError:
  print("Error: 'fontTools' library is required. Install it using: pip install fonttools")
  sys.exit(1)

try:
  from earcut.earcut import earcut
except ImportError:
  print("Error: 'earcut' library is required. Install it using: pip install earcut")
  sys.exit(1)

# --- Geometry Utilities ---

class PathCollector(BasePen):
  def __init__(self, glyphSet):
    BasePen.__init__(self, glyphSet)
    self.contours = []
    self.current_contour = []

  def _moveTo(self, p):
    if self.current_contour: self.contours.append(self.current_contour)
    self.current_contour = [p]

  def _lineTo(self, p): self.current_contour.append(p)

  def _curveToOne(self, p1, p2, p3):
    steps = 6
    curr = self.current_contour[-1]
    for i in range(1, steps + 1):
      t = i / steps
      x = (1-t)**3 * curr[0] + 3*t*(1-t)**2 * p1[0] + 3*t**2*(1-t) * p2[0] + t**3 * p3[0]
      y = (1-t)**3 * curr[1] + 3*t*(1-t)**2 * p1[1] + 3*t**2*(1-t) * p2[1] + t**3 * p3[1]
      self.current_contour.append((x, y))

  def _qCurveToOne(self, p1, p2):
    steps = 6
    curr = self.current_contour[-1]
    for i in range(1, steps + 1):
      t = i / steps
      x = (1-t)**2 * curr[0] + 2*t*(1-t) * p1[0] + t**2 * p2[0]
      y = (1-t)**2 * curr[1] + 2*t*(1-t) * p1[1] + t**2 * p2[1]
      self.current_contour.append((x, y))

  def _closePath(self):
    if self.current_contour:
      if len(self.current_contour) > 1 and self.current_contour[0] == self.current_contour[-1]:
        self.current_contour.pop()
      self.contours.append(self.current_contour)
      self.current_contour = []

def get_area(contour):
  area = 0
  for i in range(len(contour)):
    p1, p2 = contour[i], contour[(i + 1) % len(contour)]
    area += (p1[0] * p2[1] - p2[0] * p1[1])
  return area / 2.0

def is_point_in_polygon(p, polygon):
  num = len(polygon)
  i, j = 0, num - 1
  res = False
  for i in range(num):
    pi, pj = polygon[i], polygon[j]
    if ((pi[1] > p[1]) != (pj[1] > p[1])) and \
       (p[0] < (pj[0] - pi[0]) * (p[1] - pi[1]) / (pj[1] - pi[1] + 1e-9) + pi[0]):
      res = not res
    j = i
  return res

def process_glyph(font, char, scale=0.01, y_offset=0):
  glyph_name = font.getBestCmap().get(ord(char))
  if not glyph_name: return None
  glyph_set = font.getGlyphSet()
  glyph = glyph_set[glyph_name]
  pen = PathCollector(glyph_set)
  glyph.draw(pen)
  advance = glyph.width * scale
  if not pen.contours: return [], [], [], advance

  # Clean and categorize contours by area
  contour_data = []
  for c in pen.contours:
    # Clean duplicates in path to avoid earcut zero-length edges
    clean_c = []
    for i, p in enumerate(c):
        next_p = c[(i+1)%len(c)]
        if abs(p[0]-next_p[0]) > 1e-4 or abs(p[1]-next_p[1]) > 1e-4:
            clean_c.append(p)
    if len(clean_c) < 3: continue
    
    area = get_area(clean_c)
    if abs(area) < 1e-3: continue
    contour_data.append((clean_c, area))
    
  if not contour_data: return [], [], [], advance
  
  # Standard heuristic: largest area defines the "Outer" winding direction
  largest_c, largest_area = max(contour_data, key=lambda x: abs(x[1]))
  outer_is_positive = (largest_area > 0)
  
  outers = [c for c, area in contour_data if (area > 0) == outer_is_positive]
  holes = [c for c, area in contour_data if (area > 0) != outer_is_positive]
  
  # Assign each hole to its containing outer contour
  hole_assignments = {i: [] for i in range(len(outers))}
  for h in holes:
    best_outer = -1
    # 1. Ray-cast to find which outer actually contains the hole
    for i, outer in enumerate(outers):
      if is_point_in_polygon(h[0], outer):
        best_outer = i
        break
    
    # 2. Fallback to closest point if ray-casting misses (e.g. points at exact boundary)
    if best_outer == -1:
      best_dist = float('inf')
      for i, outer in enumerate(outers):
        for po in outer:
          dist = (po[0]-h[0][0])**2 + (po[1]-h[0][1])**2
          if dist < best_dist:
            best_dist, best_outer = dist, i
            
    if best_outer != -1:
      hole_assignments[best_outer].append(h)

  center_x = glyph.width / 2.0
  all_v3, all_faces = [], []
  total_verts = 0
  
  # Triangulate each outer shape individually
  for i, outer in enumerate(outers):
    flat_vertices = []
    hole_indices = []
    
    # 1. Map outer points
    for p in outer:
      flat_vertices.extend([p[0] - center_x, p[1] - y_offset])
      
    # 2. Map holes and store start indices
    my_holes = hole_assignments.get(i, [])
    for h in my_holes:
      hole_indices.append(len(flat_vertices) // 2)
      for p in h:
        flat_vertices.extend([p[0] - center_x, p[1] - y_offset])
        
    # --- Mapbox Earcut Engine ---
    tri_indices = earcut(flat_vertices, hole_indices, 2)
    
    # Translate back to 3D Vertex Buffer
    for v_idx in range(len(flat_vertices) // 2):
      all_v3.append((flat_vertices[v_idx*2] * scale, flat_vertices[v_idx*2+1] * scale, 0.0))
      
    # Translate back to Face Buffer
    for f_idx in range(0, len(tri_indices), 3):
      i0 = tri_indices[f_idx] + total_verts
      i1 = tri_indices[f_idx+1] + total_verts
      i2 = tri_indices[f_idx+2] + total_verts
      # Output in (0, 2, 1) mapping for backface culling visibility
      all_faces.append((i0, i2, i1))
      
    total_verts += (len(flat_vertices) // 2)

  # Calculate Normals
  normals = []
  for f in all_faces:
    p0, p1, p2 = all_v3[f[0]], all_v3[f[1]], all_v3[f[2]]
    ux, uy, uz = p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]
    vx, vy, vz = p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]
    nx, ny, nz = uy*vz - uz*vy, uz*vx - ux*vz, ux*vy - uy*vx
    nlen = math.sqrt(nx*nx + ny*ny + nz*nz)
    if nlen > 1e-9: normals.append((nx/nlen, ny/nlen, nz/nlen))
    else: normals.append((0, 0, 0))
    
  return all_v3, all_faces, normals, advance

def main():
  parser = argparse.ArgumentParser(description="Convert TTF to Gravity 3D Font (G3DF)")
  parser.add_argument("ttf", help="Source TTF file")
  parser.add_argument("--out", default="font.g3df", help="Output file")
  parser.add_argument("--chars", default="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ,.?!:;""'()[]{}<>|^&%#@~`", help="Chars to include")
  parser.add_argument("--scale", type=float, default=0.01, help="Scale factor")
  args = parser.parse_args()

  font = TTFont(args.ttf)
  y_offset = 360 
  if 'OS/2' in font:
    os2 = font['OS/2']
    if hasattr(os2, 'sCapHeight') and os2.sCapHeight > 0: y_offset = os2.sCapHeight / 2.0
    elif hasattr(os2, 'sTypoAscender'): y_offset = os2.sTypoAscender / 2.0
  elif 'hhea' in font: y_offset = font['hhea'].ascent / 2.0
    
  objs = []
  print(f"Processing {len(args.chars)} characters...")
  for char in args.chars:
    res = process_glyph(font, char, args.scale, y_offset)
    if res:
      v, f, n, adv = res
      objs.append({'id': ord(char), 'v': v, 'f': f, 'n': n, 'advance': int(adv * 100)})

  with open(args.out, 'wb') as outes:
    count = len(objs)
    header = struct.pack('<4s4BIII', b'G3DF', 1, 0, 0, 0, count, 20, 0)
    outes.write(header)
    outes.write(b'\0' * (count * 12))
    
    directory = []
    for obj in objs:
      data_offset = outes.tell()
      outes.write(struct.pack('<II', len(obj['f']), len(obj['v'])))
      va = array.array('f')
      for vx, vy, vz in obj['v']: va.extend([vx, vy, vz])
      va.tofile(outes)
      ia = array.array('H')
      for f0, f1, f2 in obj['f']: ia.extend([f0, f1, f2])
      ia.tofile(outes)
      na = array.array('f')
      for nx, ny, nz in obj['n']: na.extend([nx, ny, nz])
      na.tofile(outes)
      directory.append(struct.pack('<IIHH', obj['id'], data_offset, obj['advance'], 0))

    outes.seek(20)
    for entry in directory: outes.write(entry)

  print(f"G3DF Font Created: {args.out} with {count} characters.")

if __name__ == "__main__":
  main()
