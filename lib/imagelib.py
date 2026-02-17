# imagelib.py - Image manipulation for XBM image tuples
# Works with tuples from xbmreader.read() / pngreader.read():
#   (name, width, height, xbm_data, num_frames)
# xbm_data is 1-bit MSB-first packed (8 pixels per byte)

try:
  import micropython
  @micropython.viper
  def _crop_frame(src, dst, sw: int, cx: int, cy: int, cw: int, ch: int):
    """Crop one frame from src into dst. All XBM MSB-first."""
    s = ptr8(src)
    d = ptr8(dst)
    ss: int = (sw + 7) >> 3   # source stride (bytes per row)
    ds: int = (cw + 7) >> 3   # dest stride
    y: int = 0
    while y < ch:
      sr: int = (cy + y) * ss
      dr: int = y * ds
      x: int = 0
      while x < cw:
        sx: int = cx + x
        # Read source bit
        bit: int = (s[sr + (sx >> 3)] >> (7 - (sx & 7))) & 1
        # Set dest bit
        if bit:
          d[dr + (x >> 3)] |= 0x80 >> (x & 7)
        x += 1
      y += 1

  @micropython.viper
  def _scale_frame(src, dst, sw: int, sh: int, dw: int, dh: int):
    s = ptr8(src)
    d = ptr8(dst)
    ss: int = (sw + 7) >> 3
    ds: int = (dw + 7) >> 3
    inv_sx: int = (sw << 16) // dw
    inv_sy: int = (sh << 16) // dh
    dy: int = 0
    while dy < dh:
      sy: int = (dy * inv_sy) >> 16
      sr: int = sy * ss
      dr: int = dy * ds
      dx: int = 0
      while dx < dw:
        sx: int = (dx * inv_sx) >> 16
        bit: int = (s[sr + (sx >> 3)] >> (7 - (sx & 7))) & 1
        if bit:
          d[dr + (dx >> 3)] |= 0x80 >> (dx & 7)
        dx += 1
      dy += 1

except:
  def _crop_frame(src, dst, sw, cx, cy, cw, ch):
    ss = (sw + 7) // 8
    ds = (cw + 7) // 8
    for y in range(ch):
      sr = (cy + y) * ss
      dr = y * ds
      for x in range(cw):
        sx = cx + x
        bit = (src[sr + (sx >> 3)] >> (7 - (sx & 7))) & 1
        if bit:
          dst[dr + (x >> 3)] |= 0x80 >> (x & 7)

  def _scale_frame(src, dst, sw: int, sh: int, dw: int, dh: int):
    ss = (sw + 7) // 8
    ds = (dw + 7) // 8
    inv_sx = (sw << 16) // dw
    inv_sy = (sh << 16) // dh
    for dy in range(dh):
      sy = (dy * inv_sy) >> 16
      sr = sy * ss
      dr = dy * ds
      for dx in range(dw):
        sx = (dx * inv_sx) >> 16
        bit = (src[sr + (sx >> 3)] >> (7 - (sx & 7))) & 1
        if bit:
          dst[dr + (dx >> 3)] |= 0x80 >> (dx & 7)


def crop(image, x, y, w, h):
  """Crop a region from an image tuple.
  
  image: (name, width, height, data, num_frames)
  Returns: new image tuple with cropped region.
  """
  name, iw, ih, data, nf = image

  # Clamp to image bounds
  if x < 0: w += x; x = 0
  if y < 0: h += y; y = 0
  if x + w > iw: w = iw - x
  if y + h > ih: h = ih - y
  if w <= 0 or h <= 0:
    return (name, 0, 0, b'', nf)

  frame_src = (iw + 7) // 8 * ih
  frame_dst = (w + 7) // 8 * h
  out = bytearray(frame_dst * nf)

  for f in range(nf):
    src_off = f * frame_src
    dst_off = f * frame_dst
    src_view = memoryview(data)[src_off:src_off + frame_src]
    dst_view = memoryview(out)[dst_off:dst_off + frame_dst]
    _crop_frame(src_view, dst_view, iw, x, y, w, h)

  return (name, w, h, memoryview(bytes(out)), nf)


def scale(image, new_w, new_h):
  """Scale an image tuple to new dimensions (nearest-neighbor).

  image: (name, width, height, data, num_frames)
  Returns: new image tuple at new_w x new_h.
  """
  name, iw, ih, data, nf = image
  if new_w <= 0 or new_h <= 0:
    return (name, 0, 0, b'', nf)

  frame_src = (iw + 7) // 8 * ih
  frame_dst = (new_w + 7) // 8 * new_h
  out = bytearray(frame_dst * nf)

  for f in range(nf):
    src_off = f * frame_src
    dst_off = f * frame_dst
    src_view = memoryview(data)[src_off:src_off + frame_src]
    dst_view = memoryview(out)[dst_off:dst_off + frame_dst]
    _scale_frame(src_view, dst_view, iw, ih, new_w, new_h)

  return (name, new_w, new_h, memoryview(bytes(out)), nf)
