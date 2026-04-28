import esclib as elib
import pdeck
import time
import array
import dsplib as dl
import math

def generate_sphere(radius, latitudes, longitudes):
    v_raw = []
    indices_raw = []
    
    # Generate unique vertices
    for i in range(latitudes + 1):
        lat0 = math.pi * (-0.5 + float(i) / latitudes)
        z0 = radius * math.sin(lat0)
        zr0 = radius * math.cos(lat0)
        
        for j in range(longitudes):
            lng = 2 * math.pi * float(j) / longitudes
            x = zr0 * math.cos(lng)
            y = zr0 * math.sin(lng)
            v_raw.append([x, y, z0])
                
    # Generate faces (indices)
    for i in range(latitudes):
        for j in range(longitudes):
            first = i * longitudes + j
            second = first + longitudes
            if j == longitudes - 1:
                first_next = i * longitudes
                second_next = first_next + longitudes
            else:
                first_next = first + 1
                second_next = second + 1
            
            # Triangle 1
            indices_raw.append((first, second, first_next))
            # Triangle 2
            indices_raw.append((second, second_next, first_next))
                
    # Convert to compact arrays
    num_uni_verts = len(v_raw)
    num_faces = len(indices_raw)
    
    unique_verts = array.array('f', [0.0] * (num_uni_verts * 3))
    for i, p in enumerate(v_raw):
        unique_verts[i*3 : i*3+3] = array.array('f', p)
        
    indices = array.array('H', [0] * (num_faces * 3))
    for i, f in enumerate(indices_raw):
        indices[i*3 : i*3+3] = array.array('H', f)
        
    # Pre-calculate face normals
    face_normals = array.array('f', [0.0] * (num_faces * 3))
    for i, f in enumerate(indices_raw):
        p0, p1, p2 = v_raw[f[0]], v_raw[f[1]], v_raw[f[2]]
        u = [p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]]
        w = [p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]]
        nx = u[1]*w[2] - u[2]*w[1]
        ny = u[2]*w[0] - u[0]*w[2]
        nz = u[0]*w[1] - u[1]*w[0]
        n_len = math.sqrt(nx*nx + ny*ny + nz*nz)
        if n_len > 1e-9:
            face_normals[i*3 : i*3+3] = array.array('f', [-nx/n_len, -ny/n_len, -nz/n_len])
            
    return num_faces, num_uni_verts, unique_verts, indices, face_normals

# 10x10 resolution = 200 faces, roughly 110 unique vertices
num_faces, num_uni_verts, unique_verts, indices, face_normals = generate_sphere(1.0, 10, 10)

class SphereIndexedDemo:
    def __init__(self, vscreen):
        self.v = vscreen
        self.min_fps = 100
        self.last_us = time.ticks_us()
        self.rot_x = 0.0
        self.rot_y = 0.0
        self.rot_z = 0.0

        self.matrix = array.array('f', [0.0]*16)
        self.light = array.array('f', [0.5, 0.5, -1.0]) 
        self.out_poly = array.array('h', [0]* (num_faces * 6))
        self.out_dither = array.array('b', [0]* num_faces)
        self.face_indices = array.array('H', range(num_faces))
        self.depths = array.array('i', [0] * num_faces)

        # Transformation Inputs
        self.v_rot = array.array('f', [0.0, 0.0, 0.0])
        self.v_pos = array.array('f', [0.0, 0.0, 180.0]) # Z_OFFSET = 180
        self.v_scale = array.array('f', [90.0, 90.0, 90.0]) # SCALE = 70

        # Scratchpad buffers for indexed transformation
        self.temp_verts = array.array('f', [0.0] * (num_uni_verts * 3))
        self.temp_norms = array.array('f', [0.0] * (num_faces * 3))

        self.mv_poly = memoryview(self.out_poly)

    def update(self, e):
        if not self.v.active:
            self.v.finished(); return
            
        current = time.ticks_us(); diff = current - self.last_us; self.last_us = current
        fps = 1000000 // diff if diff > 0 else 0
        self.min_fps = fps if fps < self.min_fps else self.min_fps
        
        self.v.set_dither(16); self.v.set_draw_color(1)
        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(400-100, 15, f"{str(fps)} FPS, min {str(self.min_fps)}")
        self.v.draw_str(5, 15, "INDEXED SPHERE")
        
        self.rot_x -= 0.02; self.rot_y += 0.03
        self.v_rot[0], self.v_rot[1] = self.rot_x, self.rot_y
        dl.set_transform_matrix_4x4(self.matrix, self.v_rot, self.v_pos, self.v_scale)

        # Call the new fast indexed engine
        dl.project_3d_indexed(self.matrix, unique_verts, indices, face_normals, self.light,
                            num_faces, num_uni_verts, 
                            120.0, 200.0, 120.0, # fov, cx, cy
                            self.out_poly, self.out_dither, self.depths,
                            self.temp_verts, self.temp_norms)

        dl.sort_indices(self.face_indices, self.depths)

        for i in self.face_indices:
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

    obj = SphereIndexedDemo(v)
    v.callback(obj.update)
    vs.read(1)
    v.callback(None)

    v.print(el.display_mode(True))
    print("finished.", file=vs)
