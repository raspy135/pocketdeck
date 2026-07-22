# screenrec.py - record the screen to a .pdsr file on the SD card.
#
# Capturing locally sidesteps the netserver screencast entirely: no Wi-Fi
# traffic, so a recording can run alongside heavy network use (e.g. gpt agent
# turns) without competing for the Wi-Fi driver's TX buffers. Convert the
# recording to a GIF (or PNG frames) on a PC with utils/pdsr2gif.py.
#
# The recorder captures whatever screen is in the FOREGROUND, one frame at a
# time via display_take_screenshot (same path as gpt's capture_screen), so the
# usual workflow is: start it on a spare shell screen, switch to the screen you
# want to record, and switch back (any key stops it) - or just let -t expire.
#
# The recording loop is steady-state ZERO-allocation so it can never trigger a
# GC pause mid-take: the capture buffer and timestamp scratch are preallocated,
# the arithmetic is all small-int, f.write() goes through the FIL's own sector
# buffer (FatFS, not the MP heap), and read_nb returns the None singleton while
# this screen is in the background - the normal recording state. Only with this
# screen foreground (i.e. when you are back to stop it) does read_nb build its
# (n, str) tuple.
#
# File format (.pdsr, little-endian):
#   header: b"PDSR"  u8 version(=1)  u16 width  u16 height
#   frames: u32 t_ms (since start)  followed by stride*height bytes of the
#           1bpp MSB-first capture buffer (stride = width // 8)

import time
import os
import gc
import argparse
import pdeck
import pdeck_utils as pu

MAGIC = b"PDSR"
VERSION = 1
W = 400
H = 240
STRIDE = W // 8
FRAME_BYTES = STRIDE * H


def _le16(n):
  return bytes([n & 0xff, (n >> 8) & 0xff])


def default_filename():
  try:
    os.mkdir("/sd/rec")
  except OSError:
    pass
  t = time.gmtime(time.time() + pu.timezone * 60 * 15)
  return "/sd/rec/rec%02d%02d_%02d%02d%02d.pdsr" % (t[1], t[2], t[3], t[4], t[5])


def main(vs, args_in):
  parser = argparse.ArgumentParser(description="Record the screen to SD as .pdsr (convert on a PC with utils/pdsr2gif.py)")
  parser.add_argument("out", nargs="?", default=None, help="Output file (default /sd/rec/recMMDD_HHMMSS.pdsr)")
  parser.add_argument("-f", "--fps", type=float, default=5.0, help="Frames per second (default 5)")
  parser.add_argument("-t", "--time", type=float, default=30.0, help="Duration in seconds; 0 = record until a key is pressed (default 30)")
  parser.add_argument("-s", "--screen", type=int, default=None, help="Switch to this screen (0-based) before recording")
  args = parser.parse_args(args_in[1:])

  fps = args.fps if args.fps > 0 else 5.0
  interval = int(1000.0 / fps)
  limit_ms = int(args.time * 1000) if args.time > 0 else 0
  path = args.out or default_filename()

  if args.screen is not None:
    pdeck.change_screen(args.screen)
    pdeck.show_screen_num()
    pdeck.delay_tick(40)  # one frame for the target to render

  # Non-blocking key check so "any key stops recording" works. Only available
  # when the stream is backed by a vscreen (the normal device shell); without
  # it the -t limit is the only stop.
  v_in = vs.v if hasattr(vs, "v") else None

  buf = bytearray(FRAME_BYTES)
  ts = bytearray(4)  # scratch for the little-endian frame timestamp
  # pdeck.take_screenshot (module-level, newer firmware) captures the
  # just-presented PHYSICAL frame no matter which screen is foreground, so the
  # recorder keeps working after you switch away. The vscreen method fallback
  # (older firmware) only captures while this screen itself is foreground -
  # every frame recorded elsewhere counts as missed.
  shot = getattr(pdeck, "take_screenshot", None)
  if shot is None:
    shot = pdeck.vscreen().take_screenshot
    print("Note: firmware lacks pdeck.take_screenshot; recording works only "
          "while THIS screen is foreground.", file=vs)
  frames = 0
  misses = 0

  try:
    f = open(path, "wb")
  except OSError as e:
    print("Cannot open %s: %s" % (path, e), file=vs)
    return
  try:
    f.write(MAGIC)
    f.write(bytes([VERSION]))
    f.write(_le16(W))
    f.write(_le16(H))
    print("Recording to %s at %.4g fps (%s). Any key here stops." %
          (path, fps, ("until keypress" if limit_ms == 0 else "%.4gs" % args.time)), file=vs)
    # Bind everything the loop needs to locals, then collect, so the take
    # starts with a fresh heap and the loop itself never allocates.
    write = f.write
    ticks_ms = time.ticks_ms
    ticks_diff = time.ticks_diff
    sleep_ms = time.sleep_ms
    gc.collect()
    t0 = ticks_ms()
    while True:
      now = ticks_diff(ticks_ms(), t0)
      if limit_ms and now >= limit_ms:
        break
      if v_in is not None:
        ret = v_in.read_nb(1)  # None (no alloc) while this screen is backgrounded
        if ret and ret[0] > 0:
          break
      if shot(0, 0, W, H, buf):
        ts[0] = now & 0xff
        ts[1] = (now >> 8) & 0xff
        ts[2] = (now >> 16) & 0xff
        ts[3] = (now >> 24) & 0xff
        write(ts)
        write(buf)
        frames += 1
      else:
        misses += 1  # display busy this tick; drop the frame and carry on
      # Pace to the target fps, accounting for how long the capture took.
      spent = ticks_diff(ticks_ms(), t0) - now
      if spent < interval:
        sleep_ms(interval - spent)
  except OSError as e:
    print("Write failed (%s); stopping - partial recording kept." % e, file=vs)
  except KeyboardInterrupt:
    pass
  finally:
    f.close()
  try:
    size = os.stat(path)[6]
  except OSError:
    size = 0
  print("Saved %s: %d frame(s), %d bytes%s." %
        (path, frames, size, (", %d missed" % misses) if misses else ""), file=vs)
  print("Convert on a PC: python utils/pdsr2gif.py <file> -o out.gif", file=vs)
