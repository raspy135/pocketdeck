import sys
import array
import math
import struct

def parse_obj(filename):
    verts = []
    faces = []
    
    with open(filename, 'r') as f:
        for line in f:
            if line.startswith('v '):
                parts = line.split()
                verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith('f '):
                parts = line.split()[1:]
                p_indices = []
                for p in parts:
                    idx = int(p.split('/')[0])
                    if idx < 0:
                        idx = len(verts) + idx + 1
                    p_indices.append(idx - 1)
                
                for i in range(1, len(p_indices) - 1):
                    faces.append((p_indices[0], p_indices[i], p_indices[i+1]))
                    
    return verts, faces

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Convert OBJ to Gravity 3D Format (G3DF)")
    parser.add_argument("file", help="Input OBJ file")
    parser.add_argument("--out", help="Output G3DF file (.g3df)", required=True)
    args = parser.parse_args()

    verts, faces = parse_obj(args.file)
    
    num_faces = len(faces)
    num_verts = len(verts)
    
    min_v = [float('inf')] * 3
    max_v = [float('-inf')] * 3
    for v in verts:
        for i in range(3):
            min_v[i] = min(min_v[i], v[i])
            max_v[i] = max(max_v[i], v[i])
            
    center = [(min_v[i] + max_v[i]) / 2.0 for i in range(3)]
    
    unique_verts = array.array('f')
    for v in verts:
        unique_verts.extend([v[i] - center[i] for i in range(3)])
    
    indices = array.array('H')
    for f in faces:
        indices.extend(f)
        
    face_normals = array.array('f')
    for f in faces:
        p0 = [verts[f[0]][i] for i in range(3)]
        p1 = [verts[f[1]][i] for i in range(3)]
        p2 = [verts[f[2]][i] for i in range(3)]
        
        u = [p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]]
        w = [p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]]
        nx = u[1]*w[2] - u[2]*w[1]
        ny = u[2]*w[0] - u[0]*w[2]
        nz = u[0]*w[1] - u[1]*w[0]
        n_len = math.sqrt(nx*nx + ny*ny + nz*nz)
        if n_len > 1e-9:
            face_normals.extend([nx/n_len, ny/n_len, nz/n_len])
        else:
            face_normals.extend([0.0, 0.0, 0.0])

    with open(args.out, 'wb') as f:
        # G3DF Header (Magic, Obj Count, Index Offset, Flags)
        f.write(struct.pack('<4s4BIII', b'G3DF', 1, 0, 0, 0, 1, 20, 0))
        
        # Directory Placeholder (CID, Data Offset, Advance, Reserved)
        f.write(b'\0' * 12)
        
        data_offset = f.tell()
        
        # Mesh Header
        f.write(struct.pack('<II', num_faces, num_verts))
        
        # Data Arrays
        unique_verts.tofile(f)
        indices.tofile(f)
        face_normals.tofile(f)
        
        # Write Directory values
        f.seek(20)
        f.write(struct.pack('<IIHH', 0, data_offset, 0, 0))
        
    print(f"G3DF Model Exported: {num_faces} faces, {num_verts} vertices to {args.out}")

if __name__ == '__main__':
    main()
