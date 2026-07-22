# pdsr2gif.py - convert a Pocket Deck screen recording (.pdsr, written by the
# on-device screenrec app) into an animated GIF, or dump the frames as PNGs.
#
# Format (little-endian): b"PDSR" u8 version u16 width u16 height, then per
# frame: u32 t_ms followed by (width // 8) * height bytes of 1bpp MSB-first
# pixels (bit = 1 means a drawn pixel).
#
# The output is constant-frame-rate: the recorded timeline is resampled onto a
# fixed grid using each frame's timestamp, duplicating the previous frame
# wherever the recorder dropped or delayed one under load. This keeps the GIF
# in sync with wall time - per-frame GIF durations are 10ms-granular, so
# encoding the raw (jittery) deltas would accumulate drift over a long take.
# Durations are laid on the cumulative grid, keeping total rounding error
# under 10ms no matter how long the recording is.
#
# Usage:
#   python -B pdsr2gif.py rec0717_1530.pdsr                # -> rec0717_1530.gif
#   python -B pdsr2gif.py rec.pdsr -o demo.gif --scale 2 --fps 10
#   python -B pdsr2gif.py rec.pdsr --png-dir frames/       # for ffmpeg etc.

import argparse
import os
import struct
import sys

from PIL import Image


def read_pdsr(path):
  """Return (width, height, [(t_ms, frame_bytes), ...])."""
  with open(path, "rb") as f:
    data = f.read()
  if len(data) < 9 or data[:4] != b"PDSR":
    raise SystemExit("%s: not a .pdsr file" % path)
  version = data[4]
  if version != 1:
    raise SystemExit("%s: unsupported version %d" % (path, version))
  w, h = struct.unpack_from("<HH", data, 5)
  stride = w // 8
  frame_bytes = stride * h
  frames = []
  off = 9
  while off + 4 + frame_bytes <= len(data):
    (t_ms,) = struct.unpack_from("<I", data, off)
    off += 4
    frames.append((t_ms, data[off:off + frame_bytes]))
    off += frame_bytes
  if off != len(data):
    print("warning: %d trailing byte(s) ignored (truncated last frame?)"
          % (len(data) - off), file=sys.stderr)
  return w, h, frames


def to_image(raw, w, h, dark, scale):
  # Raw mode "1" maps bit=1 to white; ";I" inverts so drawn pixels are black
  # on white (the pngwriter default), unless --dark asks for the native look.
  img = Image.frombytes("1", (w, h), raw, "raw", "1" if dark else "1;I")
  if scale > 1:
    img = img.resize((w * scale, h * scale), Image.NEAREST)
  return img


def resample(frames, fps):
  """Map the recorded timeline onto a fixed fps grid. Returns a list of source
  frame indices, one per output frame: the latest source frame at or before
  each grid tick (i.e. dropped/late frames become duplicates of the previous
  one). The first tick always shows frame 0."""
  interval = 1000.0 / fps
  total = frames[-1][0]
  n_out = max(1, int(round(total / interval)) + 1)
  picks = []
  j = 0
  for i in range(n_out):
    t = i * interval
    while j + 1 < len(frames) and frames[j + 1][0] <= t:
      j += 1
    picks.append(j)
  return picks


def grid_durations_ms(n_out, fps):
  """Per-frame durations on the cumulative grid, snapped to the GIF's 10ms
  granularity so rounding error never accumulates: duration i spans from
  round(t_i) to round(t_{i+1}) rather than round(t_{i+1} - t_i)."""
  interval = 1000.0 / fps
  edges = [int(round(i * interval / 10.0)) * 10 for i in range(n_out + 1)]
  return [max(10, edges[i + 1] - edges[i]) for i in range(n_out)]


def main():
  parser = argparse.ArgumentParser(description="Convert a .pdsr screen recording to a constant-frame-rate GIF or PNG frames")
  parser.add_argument("input", help=".pdsr file from the device's screenrec app")
  parser.add_argument("-o", "--output", default=None, help="Output GIF (default: input name with .gif)")
  parser.add_argument("--fps", type=float, default=None, help="Output frame rate (default: derived from the median recorded frame interval)")
  parser.add_argument("--scale", type=int, default=1, help="Integer upscale factor (nearest-neighbor)")
  parser.add_argument("--dark", action="store_true", help="White-on-black (native polarity) instead of black-on-white")
  parser.add_argument("--png-dir", default=None, help="Dump the resampled PNG frame sequence to this directory instead of a GIF")
  args = parser.parse_args()

  w, h, frames = read_pdsr(args.input)
  if not frames:
    raise SystemExit("%s: no complete frames" % args.input)

  fps = args.fps
  if not fps:
    deltas = sorted(frames[i + 1][0] - frames[i][0] for i in range(len(frames) - 1))
    median = deltas[len(deltas) // 2] if deltas else 200
    fps = 1000.0 / max(1, median)
    # The median interval carries capture jitter; when it lands near a round
    # rate (the recorder's nominal -f), snap to it.
    snapped = round(fps)
    if snapped >= 1 and abs(fps - snapped) / snapped < 0.05:
      fps = float(snapped)
  picks = resample(frames, fps)
  dups = len(picks) - len(set(picks))
  print("%s: %dx%d, %d source frame(s), %.1fs -> %d frame(s) at %.4g fps (%d duplicate fill(s))"
        % (args.input, w, h, len(frames), frames[-1][0] / 1000.0,
           len(picks), fps, dups))

  # Decode each source frame once; duplicates reuse the same Image object.
  cache = {}
  def frame_image(idx):
    if idx not in cache:
      cache[idx] = to_image(frames[idx][1], w, h, args.dark, args.scale)
    return cache[idx]

  if args.png_dir:
    os.makedirs(args.png_dir, exist_ok=True)
    for i, idx in enumerate(picks):
      frame_image(idx).save(os.path.join(args.png_dir, "frame%05d.png" % i))
    print("Wrote %d PNGs to %s" % (len(picks), args.png_dir))
    print("ffmpeg example: ffmpeg -framerate %.4g -i %s/frame%%05d.png out.mp4"
          % (fps, args.png_dir.rstrip("/")))
    return

  durations = grid_durations_ms(len(picks), fps)
  pal = {}
  for idx in set(picks):
    pal[idx] = frame_image(idx).convert("P")
  seq = [pal[idx] for idx in picks]
  out = args.output or os.path.splitext(args.input)[0] + ".gif"
  seq[0].save(out, save_all=True, append_images=seq[1:],
              duration=durations, loop=0, optimize=True)
  print("Wrote %s (%d bytes)" % (out, os.stat(out).st_size))


if __name__ == "__main__":
  main()
