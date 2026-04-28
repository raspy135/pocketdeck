import esclib as elib
import pdeck
import time
import array
import dsplib as dl
import math

# 1. Unique Vertices for a Cube (only 8 points!)
unique_v_raw = [
    [-1, -1, -1], [ 1, -1, -1], [ 1,  1, -1], [-1,  1, -1],
    [-1, -1,  1], [ 1, -1,  1], [ 1,  1,  1], [-1,  1,  1]
]
num_uni_verts = len(unique_v_raw)
unique_verts = array.array('f', [0.0] * (num_uni_verts * 3))
for i, v in enumerate(unique_v_raw):
    unique_verts[i*3 : i*3+3] = array.array('f', v)

# 2. Face Indices (12 triangles, 36 indices)
# Each triple points to indices in unique_verts
face_indices_raw = [
    (0, 1, 2), (2, 3, 0), # Front
    (1, 5, 6), (6, 2, 1), # Right
    (7, 6, 5), (5, 4, 7), # Back
    (4, 0, 3), (3, 7, 4), # Left
    (4, 5, 1), (1, 0, 4), # Bottom
    (3, 2, 6), (6, 7, 3)  # Top
]
num_faces = len(face_indices_raw)
indices = array.array('H', [0] * (num_faces * 3))
for i, f in enumerate(face_indices_raw):
    indices[i*3 : i*3+3] = array.array('H', f)

# 3. Face Normals (one per triangle)
face_normals = array.array('f', [0.0] * (num_faces * 3))
for i, f in enumerate(face_indices_raw):
    p0, p1, p2 = unique_v_raw[f[0]], unique_v_raw[f[1]], unique_v_raw[f[2]]
    u = [p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]]
    w = [p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]]
    nx = u[1]*w[2] - u[2]*w[1]
    ny = u[2]*w[0] - u[0]*w[2]
    nz = u[0]*w[1] - u[1]*w[0]
    n_len = math.sqrt(nx*nx + ny*ny + nz*nz)
    face_normals[i*3 : i*3+3] = array.array('f', [-nx/n_len, -ny/n_len, -nz/n_len])

class CubeIndexedDemo:
    def __init__(self, vscreen):
        self.v = vscreen
        self.last_us = time.ticks_us()
        self.rot_x = 0.0
        self.rot_y = 0.0
        self.rot_z = 0.0

        self.matrix = array.array('f', [0.0]*16)
        self.light = array.array('f', [0.5, 0.7, -1.0])
        self.out_poly = array.array('h', [0]* (num_faces * 6))
        self.out_dither = array.array('b', [0]* num_faces)
        self.sort_indices = array.array('H', range(num_faces))
        self.depths = array.array('i', [0] * num_faces)
        
        # Transformation Inputs
        self.v_rot = array.array('f', [0.0, 0.0, 0.0])
        self.v_pos = array.array('f', [0.0, 0.0, 120.0]) # Z_OFFSET = 120
        self.v_scale = array.array('f', [40.0, 40.0, 40.0]) # SCALE = 40

        # Scratchpad buffers for indexed transformation
        self.temp_verts = array.array('f', [0.0] * (num_uni_verts * 3))
        self.temp_norms = array.array('f', [0.0] * (num_faces * 3))

        self.mv_poly = memoryview(self.out_poly)

    def update(self, e):
        if not self.v.active:
            self.v.finished(); return
            
        current = time.ticks_us(); diff = current - self.last_us; self.last_us = current
        fps = 1000000 // diff if diff > 0 else 0

        self.v.set_dither(16); self.v.set_draw_color(1)
        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(5, 15, "INDEXED CUBE " + str(fps) + " FPS")
        
        self.rot_x += 0.03; self.rot_y += 0.05
        self.v_rot[0], self.v_rot[1] = self.rot_x, self.rot_y
        dl.set_transform_matrix_4x4(self.matrix, self.v_rot, self.v_pos, self.v_scale)

        # New Indexed API Call
        dl.project_3d_indexed(self.matrix, unique_verts, indices, face_normals, self.light,
                            num_faces, num_uni_verts, 
                            120.0, 200.0, 120.0, # fov, cx, cy
                            self.out_poly, self.out_dither, self.depths,
                            self.temp_verts, self.temp_norms)

        dl.sort_indices(self.sort_indices, self.depths)

        for i in self.sort_indices:
            d = self.out_dither[i]
            if d >= 0:
                self.v.set_dither(d)
                self.v.draw_polygon(self.mv_poly[i*6 : i*6 + 6])
        self.v.finished()

def main(vs, args):
  el = elib.esclib()
  v = vs.v
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  vs.v.callback(CubeIndexedDemo(vs.v).update)
  vs.read(1)
  vs.v.callback(None)
  v.print(el.display_mode(True))
  print("finished.", file=vs)
