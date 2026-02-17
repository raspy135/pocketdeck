import struct
import io


try:
  import deflate
  _HAS_DEFLATE = True
except ImportError:
  _HAS_DEFLATE = False
  import zlib

# 4x4 Bayer ordered dither matrix (threshold values 0-255)
_BAYER = bytes([
    0, 128,  32, 160,
  192,  64, 224,  96,
   48, 176,  16, 144,
  240, 112, 208,  80,
])


try:
  # Viper version — native integers and ptr8 pointer access
  @micropython.viper
  def _unfilter(raw, out, h: int, stride: int, bpp: int):
    r = ptr8(raw)
    o = ptr8(out)
    pos: int = 0
    for y in range(h):
      filt: int = r[pos]
      pos += 1
      src: int = pos
      dst: int = y * stride
      pos += stride

      # Copy raw row into out
      i: int = 0
      while i < stride:
        o[dst + i] = r[src + i]
        i += 1

      if filt == 1:    # Sub
        i = bpp
        while i < stride:
          o[dst + i] = (o[dst + i] + o[dst + i - bpp]) & 0xFF
          i += 1
      elif filt == 2:  # Up
        if y > 0:
          prev: int = (y - 1) * stride
          i = 0
          while i < stride:
            o[dst + i] = (o[dst + i] + o[prev + i]) & 0xFF
            i += 1
      elif filt == 3:  # Average
        prev2: int = (y - 1) * stride if y > 0 else -1
        i = 0
        while i < stride:
          a: int = o[dst + i - bpp] if i >= bpp else 0
          b: int = o[prev2 + i] if prev2 >= 0 else 0
          o[dst + i] = (o[dst + i] + ((a + b) >> 1)) & 0xFF
          i += 1
      elif filt == 4:  # Paeth
        prev3: int = (y - 1) * stride if y > 0 else -1
        i = 0
        while i < stride:
          a = o[dst + i - bpp] if i >= bpp else 0
          b = o[prev3 + i] if prev3 >= 0 else 0
          c: int = o[prev3 + i - bpp] if (prev3 >= 0 and i >= bpp) else 0
          # Inline Paeth predictor
          p: int = a + b - c
          pa: int = p - a if p >= a else a - p
          pb: int = p - b if p >= b else b - p
          pc: int = p - c if p >= c else c - p
          pr: int = 0
          if pa <= pb and pa <= pc: pr = a
          elif pb <= pc: pr = b
          else: pr = c
          o[dst + i] = (o[dst + i] + pr) & 0xFF
          i += 1

except:
  # CPython fallback
  def _paeth(a, b, c):
    p = a + b - c
    pa = p - a if p >= a else a - p
    pb = p - b if p >= b else b - p
    pc = p - c if p >= c else c - p
    if pa <= pb and pa <= pc: return a
    if pb <= pc: return b
    return c

  def _unfilter(raw, out, h, stride, bpp):
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
      filt = raw[pos]
      pos += 1
      row = bytearray(raw[pos:pos + stride])
      pos += stride
      if filt == 1:
        for i in range(bpp, stride):
          row[i] = (row[i] + row[i - bpp]) & 0xFF
      elif filt == 2:
        for i in range(stride):
          row[i] = (row[i] + prev[i]) & 0xFF
      elif filt == 3:
        for i in range(stride):
          a = row[i - bpp] if i >= bpp else 0
          row[i] = (row[i] + ((a + prev[i]) >> 1)) & 0xFF
      elif filt == 4:
        for i in range(stride):
          a = row[i - bpp] if i >= bpp else 0
          b = prev[i]
          c = prev[i - bpp] if i >= bpp else 0
          row[i] = (row[i] + _paeth(a, b, c)) & 0xFF
      out[y * stride:y * stride + stride] = row
      prev = row


try:
  @micropython.viper
  def _to_gray_rgb8(out, gray, w: int, h: int, stride: int):
    s = ptr8(out)
    g = ptr8(gray)
    y: int = 0
    while y < h:
      ro: int = y * stride
      gi: int = y * w
      x: int = 0
      while x < w:
        o: int = ro + x * 3
        g[gi + x] = (s[o] * 77 + s[o + 1] * 150 + s[o + 2] * 29) >> 8
        x += 1
      y += 1

  @micropython.viper
  def _to_gray_rgba8(out, gray, w: int, h: int, stride: int):
    s = ptr8(out)
    g = ptr8(gray)
    y: int = 0
    while y < h:
      ro: int = y * stride
      gi: int = y * w
      x: int = 0
      while x < w:
        o: int = ro + x * 4
        g[gi + x] = (s[o] * 77 + s[o + 1] * 150 + s[o + 2] * 29) >> 8
        x += 1
      y += 1

  @micropython.viper
  def _to_gray_g8(out, gray, w: int, h: int, stride: int):
    s = ptr8(out)
    g = ptr8(gray)
    y: int = 0
    while y < h:
      ro: int = y * stride
      gi: int = y * w
      x: int = 0
      while x < w:
        g[gi + x] = s[ro + x]
        x += 1
      y += 1

  @micropython.viper
  def _scale_nn(src, dst, sw: int, dw: int, dh: int, inv_s: int):
    s = ptr8(src)
    d = ptr8(dst)
    dy: int = 0
    while dy < dh:
      sy: int = (dy * inv_s) >> 16
      sr: int = sy * sw
      dr: int = dy * dw
      dx: int = 0
      while dx < dw:
        d[dr + dx] = s[sr + ((dx * inv_s) >> 16)]
        dx += 1
      dy += 1

  @micropython.viper
  def _dither(gray, xbm, dw: int, dh: int, xs: int, bayer):
    g = ptr8(gray)
    x8 = ptr8(xbm)
    b = ptr8(bayer)
    y: int = 0
    while y < dh:
      gi: int = y * dw
      xr: int = y * xs
      by: int = (y & 3) << 2
      x: int = 0
      while x < dw:
        if g[gi + x] > b[by + (x & 3)]:
          x8[xr + (x >> 3)] |= 0x80 >> (x & 7)
        x += 1
      y += 1

  @micropython.viper
  def _to_gray_indexed8(out, gray, pal, w: int, h: int, stride: int):
    s = ptr8(out)
    g = ptr8(gray)
    p = ptr8(pal)
    y: int = 0
    while y < h:
      ro: int = y * stride
      gi: int = y * w
      x: int = 0
      while x < w:
        pi: int = s[ro + x] * 3
        g[gi + x] = (p[pi] * 77 + p[pi + 1] * 150 + p[pi + 2] * 29) >> 8
        x += 1
      y += 1

  @micropython.viper
  def _to_gray_ga8(out, gray, w: int, h: int, stride: int):
    s = ptr8(out)
    g = ptr8(gray)
    y: int = 0
    while y < h:
      ro: int = y * stride
      gi: int = y * w
      x: int = 0
      while x < w:
        g[gi + x] = s[ro + x * 2]
        x += 1
      y += 1

except:
  def _to_gray_rgb8(out, gray, w, h, stride):
    for y in range(h):
      ro = y * stride; gi = y * w
      for x in range(w):
        o = ro + x * 3
        gray[gi + x] = (out[o] * 77 + out[o+1] * 150 + out[o+2] * 29) >> 8

  def _to_gray_rgba8(out, gray, w, h, stride):
    for y in range(h):
      ro = y * stride; gi = y * w
      for x in range(w):
        o = ro + x * 4
        gray[gi + x] = (out[o] * 77 + out[o+1] * 150 + out[o+2] * 29) >> 8

  def _to_gray_g8(out, gray, w, h, stride):
    for y in range(h):
      ro = y * stride; gi = y * w
      for x in range(w):
        gray[gi + x] = out[ro + x]

  def _scale_nn(src, dst, sw, dw, dh, inv_s):
    for dy in range(dh):
      sr = ((dy * inv_s) >> 16) * sw; dr = dy * dw
      for dx in range(dw):
        dst[dr + dx] = src[sr + ((dx * inv_s) >> 16)]

  def _dither(gray, xbm, dw, dh, xs, bayer):
    for y in range(dh):
      gi = y * dw; xr = y * xs; by = (y & 3) << 2
      for x in range(dw):
        if gray[gi + x] > bayer[by + (x & 3)]:
          xbm[xr + (x >> 3)] |= 0x80 >> (x & 7)

  def _to_gray_indexed8(out, gray, pal, w, h, stride):
    for y in range(h):
      ro = y * stride; gi = y * w
      for x in range(w):
        pi = out[ro + x] * 3
        gray[gi + x] = (pal[pi] * 77 + pal[pi+1] * 150 + pal[pi+2] * 29) >> 8

  def _to_gray_ga8(out, gray, w, h, stride):
    for y in range(h):
      ro = y * stride; gi = y * w
      for x in range(w):
        gray[gi + x] = out[ro + x * 2]


def read(filename, max_w=None, max_h=None, bench=False):
  """Read a PNG file, return (name, width, height, xbm_data, num_frames).
  
  Same tuple format as xbmreader.read()/read_xbmr().
  Color PNG is converted to grayscale, then dithered to 1-bit.
  xbm_data is MSB-first packed (8 pixels per byte), compatible with draw_xbm().
  If max_w/max_h are given, scales down to fit.
  Pass bench=True to print timing for each step.
  """
  from benchmark import benchmark
  bm = benchmark(bench)
  bm.start_bench()
  with open(filename, "rb") as f:
    sig = f.read(8)
    if sig[:4] != b'\x89PNG':
      raise ValueError("Not a PNG file")

    w = h = 0
    bd = ct = 0
    palette = None
    idat_chunks = []

    while True:
      hdr = f.read(8)
      if len(hdr) < 8: break
      length = struct.unpack(">I", hdr[:4])[0]
      ctype = hdr[4:8]
      body = f.read(length)
      f.read(4)  # CRC

      if ctype == b'IHDR':
        w, h, bd, ct = struct.unpack(">IIbB", body[:10])
        if body[12] != 0:
          raise ValueError("Interlaced PNG not supported")
      elif ctype == b'PLTE':
        palette = body
      elif ctype == b'IDAT':
        idat_chunks.append(body)
      elif ctype == b'IEND':
        break

  bm.add_bench('parse')

  # Decompress all IDAT data
  compressed = b''.join(idat_chunks)
  if _HAS_DEFLATE:
    stream = io.BytesIO(compressed)
    d = deflate.DeflateIO(stream, deflate.ZLIB)
    raw = d.read()
  else:
    raw = zlib.decompress(compressed)
  bm.add_bench('decompress')

  # Bytes per pixel and scanline stride
  if ct == 0:    bpp = 1 if bd <= 8 else 2
  elif ct == 2:  bpp = 3 if bd <= 8 else 6
  elif ct == 3:  bpp = 1
  elif ct == 4:  bpp = 2 if bd <= 8 else 4
  elif ct == 6:  bpp = 4 if bd <= 8 else 8
  else: raise ValueError(f"Unsupported color type {ct}")

  stride = (w * bd + 7) // 8 if bd < 8 else w * bpp

  # Step 1: Reverse filters (native)
  out = bytearray(h * stride)
  _unfilter(raw, out, h, stride, bpp)
  del raw
  bm.add_bench('unfilter')

  # Step 2: Convert to grayscale (native fast paths for common types)
  gray = bytearray(w * h)
  if ct == 2 and bd == 8:
    _to_gray_rgb8(out, gray, w, h, stride)
  elif ct == 6 and bd == 8:
    _to_gray_rgba8(out, gray, w, h, stride)
  elif ct == 0 and bd == 8:
    _to_gray_g8(out, gray, w, h, stride)
  elif ct == 3 and bd == 8 and palette:
    _to_gray_indexed8(out, gray, palette, w, h, stride)
  elif ct == 4 and bd == 8:
    _to_gray_ga8(out, gray, w, h, stride)
  else:
    print(f'pngreader: slow fallback ct={ct} bd={bd}')
    # Fallback for indexed, sub-8-bit, 16-bit
    for y in range(h):
      ro = y * stride
      gi = y * w
      for x in range(w):
        if ct == 0:
          if bd == 16: g = out[ro + x * 2]
          else:
            mask = (1 << bd) - 1
            g = ((out[ro + x * bd // 8] >> (8 - bd - (x * bd % 8))) & mask) * (255 // mask)
        elif ct == 2:
          o = ro + x * 6
          g = (out[o] * 77 + out[o + 2] * 150 + out[o + 4] * 29) >> 8
        elif ct == 3:
          if bd == 8: pi = out[ro + x] * 3
          else:
            mask = (1 << bd) - 1
            pi = ((out[ro + x * bd // 8] >> (8 - bd - (x * bd % 8))) & mask) * 3
          g = (palette[pi] * 77 + palette[pi + 1] * 150 + palette[pi + 2] * 29) >> 8
        elif ct == 4:
          g = out[ro + x * bpp]
        elif ct == 6:
          o = ro + x * 8
          g = (out[o] * 77 + out[o + 2] * 150 + out[o + 4] * 29) >> 8
        else: g = 0
        gray[gi + x] = g
  del out
  bm.add_bench('grayscale')

  # Step 3: Scale to fit if specified (native)
  dw, dh = w, h
  if max_w and max_h and (w > max_w or h > max_h):
    s = min(max_w / w, max_h / h)
    dw, dh = int(w * s), int(h * s)
    sc = bytearray(dw * dh)
    inv_s = int((1 << 16) / s)
    _scale_nn(gray, sc, w, dw, dh, inv_s)
    gray = sc
    bm.add_bench('scale')

  # Step 4: Bayer dither to 1-bit XBM (native)
  xs = (dw + 7) // 8
  xbm = bytearray(xs * dh)
  _dither(gray, xbm, dw, dh, xs, _BAYER)
  bm.add_bench('dither')

  name = filename
  try:
    base = filename.replace('\\', '/').split('/')[-1]
    if '.' in base: base = base[:base.rfind('.')]
    name = base
  except: pass

  bm.print_bench()
  return (name, dw, dh, memoryview(bytes(xbm)), 1)
