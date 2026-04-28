import esclib as elib
import pdeck
import time
import array
import dsplib as dl
import math

# 2D Square Geometry
VERTS = array.array('f', [
  -1, -1,
   1, -1,
   1,  1,
  -1,  1,
])

INDICES = array.array('H', [
  0, 1, 2,
  0, 2, 3,
])

# Dither values per vertex (1.0 to 16.0)
COLORS = array.array('f', [16.0, 12.0, 8.0, 4.0])

num_faces = len(INDICES) // 3
num_uni_verts = len(VERTS) // 2

class Cube2DDemo:
    def __init__(self, vscreen):
        self.v = vscreen
        self.last_us = time.ticks_us()
        self.angle = 0.0
        
        # 3x3 Matrix for 2D transform
        self.mat = array.array('f', [0.0] * 9)
        self.pos = array.array('f', [0.0, 0.0])
        self.scale = array.array('f', [60.0, 60.0])
        
        # Buffers for project_2d_indexed
        self.out_poly = array.array('h', [0] * (num_faces * 6))
        self.out_dither = array.array('b', [0] * num_faces)
        self.t_verts = array.array('f', [0.0] * (num_uni_verts * 2))
        
        # Indices for draw_2d_faces (identity since no depth sorting is needed for flat 2D)
        self.face_indices = array.array('H', list(range(num_faces)))

    def update(self, e):
        if not self.v.active:
            self.v.finished()
            return
            
        current = time.ticks_us()
        diff = current - self.last_us
        self.last_us = current
        fps = 1000000 // diff if diff > 0 else 0

        self.v.set_dither(16)
        
        self.v.set_font("u8g2_font_profont15_mf")
        self.v.draw_str(5, 15, "2D PROJECT TEST " + str(fps) + " FPS")
        
        # Update rotation
        self.angle += 0.04
        dl.set_transform_matrix_3x3(self.mat, self.angle, self.pos, self.scale)
        
        # Efficiently project 2D vertices to polygon buffer
        # This calculates vertex-based dithering and applies matrix transform
        dl.project_2d_indexed(
            self.mat, VERTS, INDICES, COLORS, 1.0,
            num_faces, num_uni_verts, 200, 120, # center screen
            self.out_poly, self.out_dither, self.t_verts
        )
        
        # Batch draw all faces with their respective dither values
        self.v.draw_2d_faces(self.out_poly, self.face_indices, self.out_dither)
        
        self.v.finished()

def main(vs, args):
    el = elib.esclib()
    v = vs.v
    
    # standard Pocket Deck terminal setup
    v.print(el.erase_screen())
    v.print(el.home())
    v.print(el.display_mode(False)) # switch to graphics mode

    # start callback-based rendering
    v.callback(Cube2DDemo(v).update)
    
    # Wait for 'q' or any character to exit
    vs.read(1)
    
    # cleanup
    v.callback(None)
    v.print(el.display_mode(True)) # switch back to terminal mode
    print("finished.", file=vs)
