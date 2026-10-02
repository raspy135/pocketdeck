# tripmap.py — REUSABLE trip-plan engine: real OSM map + step-by-step notes.
#
#   tripmap <trip_name> [-z ZOOM] [-p osm|topo] [-l LEVELS]
#
# loads /sd/py/trip_<name>.py, which must define TRIP (see trip_malibu.py).
# That resource file is the only thing that changes between trips.
#
# The map is a real slippy map: Web Mercator projection, raster tiles pulled
# over HTTPS, converted to 1-bit with the device's own Bayer ditherer
# (pngreader), and blitted with draw_xbm. Stops sit at their geocoded lat/lon,
# so the geography is real: relative positions, distances and the coastline
# are what OpenStreetMap has. Panning between stops is a genuine map pan; the
# zoom auto-fits each hop, like a nav app.
#
# The disk cache holds the DECODED 1-bit bitmap as XBMR, not the server's PNG
# (see TileStore). PNG costs an inflate + unfilter + RGB-to-gray + Bayer pass
# (~0.5 s) on every tile you have already seen; XBMR is the framebuffer's own
# format, so a cache hit is a single sequential read. The dither is baked in,
# which is fine: the PNG is thrown away once decoded, and nothing downstream
# wants the gray source back - tilequant works from the 1-bit ink counts.
#
# House style (dashboard_design.md): inverted header bar, flat boxes and dither
# only, every string measured with get_utf8_width(), profont body/title sizes,
# anm entrance animation, geometry precomputed, and a frame callback that only
# redraws while animating or after input.
#
# Keys:  Up / Right / n = next stop   Down / Left / p = previous stop
#        + / - = zoom in / out     g = refetch tiles     i = flip map polarity
#        d = map tones (4 / 6 / full)   h / e = first / last   r = replay
#        q or B = quit

import os
import math
import time
import struct
import argparse
import anm
import curl as http
import pngreader
import xbmreader
import esclib as elib
import pdeck
import _thread

W = 400
H = 240

BODY_FONT = 'u8g2_font_profont15_mf'
SMALL_FONT = 'u8g2_font_profont11_mf'
TITLE_FONT = 'u8g2_font_profont22_mf'

# ---- map viewport -----------------------------------------------------------
MAP_TOP = 21
MAP_BOT = 93
MAP_H = MAP_BOT - MAP_TOP + 1
MAP_W = W
TILE = 256
FOCUS_X = 200                # the current stop is held near here while panning

# ---- detail panel -----------------------------------------------------------
MARGIN = 6
RIGHT = 394
CHIP_Y = 95
CHIP_H = 16
TITLE_Y = 127
SUB_Y = 141
RULE_Y = 146
BODY_TOP = 159
BODY_LH = 13
BODY_MAX = 4
BAR_Y = 207
TIP_TOP = 215
DIST_W = 80                  # fixed slot for the "49 km drive" read-out

# The firmware paints a screen-number badge in the top-right corner, so the
# header's right edge stays clear of it.
BADGE_W = 42

PROVIDERS = {
  # 'osm' is fast (~130ms/tile) and polite; 'topo' adds relief shading (~310ms).
  'osm': 'https://tile.openstreetmap.org/%d/%d/%d.png',
  'topo': 'https://a.tile.opentopomap.org/%d/%d/%d.png',
}
# Public OSRM demo: real driving geometry for the whole chain of stops in one
# request (plain http, ~0.5s). If it is unreachable the route falls back to
# straight legs, so the app never depends on it.
OSRM = ('http://router.project-osrm.org/route/v1/driving/%s'
        '?overview=simplified&geometries=geojson')
UA = 'PocketDeckTripmap/0.1 (personal handheld trip viewer)'
CACHE_DIR = '/sd/work/tripmap'
ZOOM_MIN = 8
ZOOM_MAX = 15
AUTO_MAX = 14                # never auto-zoom closer than this
# The zoom for a hop is the largest one at which the two stops stay within this
# many world px of each other, so both markers are on screen at once. The strip
# is 400x73, and the focus marker sits at FOCUS_X, which leaves just over 200px
# ahead of it - hence a budget a little above that.
HOP_SPAN = 330

# ---- load queue -------------------------------------------------------------
# Input and page state live on the display task (update()); every blocking step
# - tile HTTP, PNG decode, OSRM route JSON - lives on the app thread
# (loader_loop). The two talk through one guarded list of commands. Measured on
# this device: a cold tile costs ~2.2 s (network + decode), and a hop needs up
# to 6 of them, so a fetch that used to run inside the key loop could swallow a
# key press for 10-20 s. The queue means a press is answered by the panel and
# the pan on the very next frame, and the map fills in behind it.
QUEUE_MAX = 8                # a longer backlog is never drawn - coalesce instead
IDLE_TICK = 12               # app thread's sleep when the queue is empty
DEBUG_LOG = '/sd/work/tripdebug.txt'   # written by the app thread, never a frame

# ---- map tones --------------------------------------------------------------
# `levels` limits how many distinct TONES a tile is drawn with, by re-emitting
# each 4x4 cell's ink count through the same Bayer matrix (tilequant.py). It is
# free at draw time and reversible live: `d` cycles the options, and both the
# full and the reduced copy of every tile are memoized.
#
# THE RULE: reducing the level count must never move pixels sideways. An OSM
# tile is high-key and its counts are a SPIKE, not a spread - the tile under the
# hotel at z13 puts 3339 of 4096 cells at count 13. Spacing 4 tones evenly
# across gray gives counts 0/6/11/16, and nearest-snapping then moves that whole
# background band 13 -> 11: a 69% halftone, i.e. MORE visible lattice, with the
# roads collapsed into it. Measured: 97% of cells translated. That is a
# resolution loss dressed up as a contrast reduction, and it is what the first
# version of this did.
#
# codebook() therefore takes its levels from the TILE'S OWN histogram, always
# anchoring 0 and 16 and putting every interior level on a count the data
# actually occupies. A count that is its own target cannot move, so the mass
# stays exactly where it was and only the sparse intermediate counts
# (anti-aliased edges, haze) merge. Same 4 tones: 11% of cells moved instead of
# 97%, on every tile measured.
#
# Default is 0 = leave the dither as pngreader made it. With a correct codebook,
# fewer tones no longer looks WORSE, but it does not by itself look BETTER
# either - the haze at count 13 is a real 81%-white tone that the codebook now
# faithfully preserves. A genuinely clearer map needs the bright band pushed UP
# to solid 16 while features go down, which is a one-sided map rather than
# nearest-snap and so is a different control. Try `d` and see for yourself.
LEVELS_DEFAULT = 0           # 0 == full 16-level dither
LEVELS_CYCLE = (0, 4, 6, 8)  # 'd' steps through these


# ---- small helpers (rule 2: measure text before you place it) ---------------

def clamp01(t):
  return 0.0 if t < 0 else (1.0 if t > 1 else t)


def right_x(v, edge, text):
  return edge - v.get_utf8_width(text)


def center_x(v, cx, text):
  return cx - v.get_utf8_width(text) // 2


def fit(v, text, max_w):
  if v.get_utf8_width(text) <= max_w:
    return text
  while text and v.get_utf8_width(text + '..') > max_w:
    text = text[:-1]
  return text + '..'


def wrap(v, text, max_w, max_lines):
  lines = []
  cur = ''
  for word in text.split(' '):
    trial = word if not cur else cur + ' ' + word
    if not cur or v.get_utf8_width(trial) <= max_w:
      cur = trial
    else:
      lines.append(cur)
      cur = word
  if cur:
    lines.append(cur)
  if len(lines) > max_lines:
    lines = lines[:max_lines]
    lines[max_lines - 1] = fit(v, lines[max_lines - 1] + ' ..', max_w)
  return lines


def clip(s, n):
  return s[:n]


def blit_tile(x, y, img, t, b):
  """The (x, y, w, h, data) rect for draw_xbm() covering the strip.

  draw_xbm() now clips a negative x itself (the driver drops the off-screen
  columns), so the tile is passed at its real x - which may be negative - and
  the full row width is kept. That removes the old Python-side left crop, the
  byte-grid snap in origin(), and the per-row bytearray copy.

  Only the rows are trimmed here: a 256px tile is at most 73px of strip, so
  blitting the ~180 invisible rows would be pure waste. The slice keeps the
  source's own byte stride, so a partial row still begins at the byte holding
  the first visible pixel - which is why x may now be any pixel, not a
  multiple of 8.

  Returns None when the tile misses the strip entirely.
  """
  w = img[1]
  h = img[2]
  data = img[3]
  nb = (w + 7) >> 3                 # bytes per source row, MSB-first
  if y >= b or y + h <= t:
    return None
  dy = y if y > t else t
  ch = min(b - dy, h - (dy - y))
  if ch <= 0:
    return None
  oy = dy - y
  return (x, dy, w, ch, data[oy * nb:(oy + ch) * nb])


def project(lat, lon):
  # -> (nx, ny) in 0..1, the standard Web Mercator / slippy-map normalisation.
  nx = (lon + 180.0) / 360.0
  lat_r = math.radians(lat)
  ny = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0
  return nx, ny


# ---- optional contrast reduction (the 'levels' option) ---------------------
#
# pngreader dithers with a 4x4 Bayer matrix whose thresholds are the multiples
# of 16 from 0 to 240. That makes the INK COUNT inside each cell a monotone
# readout of the tile's gray (count == ceil(gray/16)), so a 1-bit tile already
# carries ~16 gray levels - and a count can be read back and re-emitted through
# the same matrix. That is how N levels are produced from 16 without touching
# the PNG, the network, or the cache on disk.
#
# Why you would want fewer: on a 400x73 strip the 4x4 lattice IS the image. In
# the flat areas (ocean, a park, a housing grid) the eye reads the dither as
# noise and loses the coastline it was handed. Four levels turn those areas into
# clean white and keep the dither where it earns its keep - shorelines, mid
# tones, road casings.
#
# The kernel lives in tilequant.py, NOT here: a @micropython.viper function
# compiles to native code at import time that 'del sys.modules' cannot reclaim,
# and tripplan.py deliberately re-imports this module on every launch. See the
# header of tilequant.py.
from tilequant import targets_for, codebook, cell_counts, quantize, HAVE_VIPER



class TileStore:
  """Downloads map tiles and decodes them to 1-bit XBM, caching as XBMR.

  Runs on the app thread; the display callback only ever reads whole tuples,
  so a tile is either absent or complete - never half-written.
  """

  MEM_MAX = 48               # 48 x 8 KB of decoded tiles (~400 KB), then FIFO
  FAIL_MAX = 4               # give up on one tile after this many tries

  def __init__(self, provider, tag, levels=None):
    # Normalise before the name is used anywhere: provider now appears in the
    # cache filename, and an unknown one must not be stored under its own name
    # while being fetched from the default server.
    if provider not in PROVIDERS:
      provider = 'osm'
    self.provider = provider
    self.url = PROVIDERS[provider]
    self.tag = tag
    # Two memos: `mem` always holds the full 16-level decode, `qmem` the version
    # limited to `levels`. Quantizing at decode would mean a re-read of every
    # cached tile (~0.5 s each, before the XBMR cache made it ~40 ms) whenever
    # the setting changes; keeping both makes the toggle instant so the two can
    # be compared side by side. The extra cost is one 8 KB buffer per tile in
    # use, and the file on disk is never rewritten.
    self.levels = levels
    self.mem = {}
    self.qmem = {}
    # key -> the tile's 4x4 ink-count histogram. Measuring costs a Python pass
    # over 4096 cells; the codebook derived from it is 17 entries and free. So
    # cache the measurement and recompute the codebook on every level change,
    # which lets `d` cycle counts without ever re-reading a tile.
    self.hist = {}
    self.order = []
    self.failed = {}
    self.last_err = None
    try:
      os.mkdir(CACHE_DIR)
    except OSError:
      pass

  def path(self, z, x, y):
    # The provider is part of the name, not just the URL. Both styles describe
    # the same ground at the same zoom and x/y, so without it a trip opened once
    # as 'osm' served its cached image to '-p topo' forever: the PNG magic bytes
    # match, so get() accepted the wrong picture and never asked the topo server.
    # Measured: a topo request against an osm-cached tile returned in 324 ms with
    # the file mtime unchanged; from a clean cache the same tile took 4674 ms.
    #
    # .xbmr, not .png: the cache stores the DECODED 1-bit bitmap. The extension
    # is also the cache format version - a change to pngreader's dither or scale
    # must move to .xbmr2, since old files would keep serving the old look.
    return '%s/%s_%s_%d_%d_%d.xbmr' % (CACHE_DIR, self.provider, self.tag, z, x,
                                       y)

  def png_path(self, z, x, y):
    # The pre-XBMR cache. Read once to migrate, then deleted.
    return '%s/%s_%s_%d_%d_%d.png' % (CACHE_DIR, self.provider, self.tag, z, x,
                                      y)

  def read_cache(self, p):
    """A cached XBMR tile, or None if the file is missing or unusable.

    read_xbmr() hands back a memoryview over everything after the 8-byte
    header, so a truncated file (normal: 'q' during a fetch) or trailing
    garbage would decode as a wrong-size bitmap and blit as noise. Size and
    header are checked here instead, which turns both into a clean miss.
    """
    try:
      if os.stat(p)[6] != 8 + (TILE * TILE // 8):
        raise OSError('cached xbmr is %d bytes, want %d' %
                      (os.stat(p)[6], 8 + TILE * TILE // 8))
      img = xbmreader.read_xbmr(p)
    except (OSError, ValueError) as e:
      self.last_err = '%s: %s' % (p.split('/')[-1], repr(e))
      return None
    if img[1] != TILE or img[2] != TILE or img[4] != 1:
      self.last_err = '%s: header %dx%d x%d frames' % (p.split('/')[-1], img[1],
                                                       img[2], img[4])
      return None
    return img

  def write_cache(self, p, img):
    """Persist a decoded tile as XBMR, atomically.

    XBMR's header is (reserved, frames, width, height) as little-endian
    int16 - the same order struct.unpack('<hhhh') reads in read_xbmr(). Write
    to .part and rename so a tile is either absent or complete on disk, the
    same invariant the in-RAM memo keeps.
    """
    tmp = p + '.part'
    try:
      with open(tmp, 'wb') as f:
        f.write(struct.pack('<hhhh', 0, 1, img[1], img[2]))
        f.write(bytes(img[3]))
      os.rename(tmp, p)
    except OSError:
      try:
        os.remove(tmp)
      except OSError:
        pass

  def migrate(self, z, x, y):
    """Decode a pre-XBMR cached PNG into the new cache. One time, no network.

    Without this, upgrading would re-download every tile already on the SD
    card - a cold tile is ~2.2 s and a hop needs up to 6 of them. Returns the
    decoded image, or None if there is no PNG to migrate.
    """
    pp = self.png_path(z, x, y)
    try:
      if os.stat(pp)[6] < 100:
        raise OSError('cached png is empty')
    except OSError:
      return None
    try:
      img = pngreader.read(pp)
    except Exception as e:
      self.last_err = 'migrate %s: %s' % (pp.split('/')[-1], repr(e))
      return None
    self.write_cache(self.path(z, x, y), img)
    try:
      os.remove(pp)
    except OSError:
      pass
    return img

  def get(self, z, x, y):
    """Ensure the tile is decoded, then return the bitmap to blit.

    The memo check lives in src() so the level setting is applied in exactly
    one place; a cached tile still costs nothing but a dict lookup.
    """
    key = (z, x, y)
    t = self.mem.get(key)
    if t is not None:
      return self.src(key)
    # A failed tile is retried on the next request rather than blacklisted for
    # the session. OSM sheds the occasional request (rate limit, TLS hiccup),
    # and a permanent refusal would leave a black hole in the map that the user
    # has to restart the app to clear. Successes are on disk, so a retry costs
    # at most one more HTTP call - and FAIL_MAX stops a dead network from
    # stalling the key loop on every frame.
    if self.failed.get(key, 0) >= self.FAIL_MAX:
      return None
    p = self.path(z, x, y)
    img = self.read_cache(p)
    if img is None:
      img = self.migrate(z, x, y)
    if img is None:
      try:
        status, hdr, body = http.request(self.url % (z, x, y), user_agent=UA,
                                         timeout=20)
        if status.find('200') < 0 or len(body) < 100:
          raise OSError('tile http %s' % clip(status, 12))
        # Decode the fresh PNG once, then keep the bitmap and not the PNG: the
        # inflate + dither is the expensive half, and it never has to run twice.
        tmp = p + '.png.part'
        with open(tmp, 'wb') as f:
          f.write(body)
        img = pngreader.read(tmp)
        try:
          os.remove(tmp)
        except OSError:
          pass
        self.write_cache(p, img)
      except Exception as e:
        self.failed[key] = self.failed.get(key, 0) + 1
        self.last_err = '%s: %s' % (key, repr(e))
        return None
    self._remember(key, img)
    # Warm the reduced-tone copy immediately: this is the app thread, and
    # draw_map() reads through src(), which must not measure or quantize.
    self.warm(key)
    return self.src(key)

  def src(self, key):
    """The bitmap to blit for `key`, honouring the current level setting.

    Pure memo read: warm() does the work. draw_map() calls this from the display
    callback, so nothing expensive may happen here - an unwarmed tile just falls
    back to the full-dither bitmap for a frame or two rather than stalling the
    frame loop on a histogram pass.
    """
    img = self.mem.get(key)
    if img is None or not self.levels:
      return img
    q = self.qmem.get(key)
    return img if q is None else q

  def warm(self, key):
    """Prepare the reduced-tone copy of one tile. App thread only.

    The codebook comes from the TILE'S OWN histogram, not from an even split of
    the gray axis - see tilequant.codebook(). Computing it costs a histogram pass
    (~4096 cells) plus a ~20ms viper kernel, so it runs here, once per tile per
    setting, and is remembered even when the answer is 'this tile already fits
    the budget' (targets None -> qmem holds the original bitmap).
    """
    img = self.mem.get(key)
    if img is None:
      return
    if not self.levels:
      self.qmem.pop(key, None)
      return
    if key in self.qmem:
      return
    h = self.hist.get(key)
    if h is None:
      h = cell_counts(img[3], img[1], img[2])
      self.hist[key] = h
    t = codebook(h, self.levels)
    self.qmem[key] = img if t is None else quantize(img, t)

  def set_levels(self, levels):
    """Change the tone budget. No re-decode, no network, and deliberately NO
    re-warm: warm_all() is a histogram pass per tile, far too much for a frame,
    so the caller re-warms on the app thread. src() falls back to the full
    dither bitmap until then, so the map stays readable while it catches up."""
    if levels == self.levels:
      return
    self.levels = levels
    self.qmem = {}

  def warm_all(self):
    """Warm every decoded tile. Called after a level change and after prefetch,
    so the display callback never meets an unwarmed tile."""
    if not self.levels:
      return
    for key in list(self.mem.keys()):
      self.warm(key)

  def _remember(self, key, img):
    # A long trip can wander over dozens of tiles; the decoded bitmaps are
    # 8 KB each, so keep a bounded FIFO (~400 KB). Everything stays on disk in
    # CACHE_DIR, so an eviction costs a re-read, never a re-download.
    if key not in self.mem:
      self.order.append(key)
      if len(self.order) > self.MEM_MAX:
        for old in self.order[:len(self.order) - self.MEM_MAX]:
          self.mem.pop(old, None)
          self.qmem.pop(old, None)     # the quantized copy is worthless alone
          self.hist.pop(old, None)     # re-measured if the tile ever returns
        self.order = self.order[-self.MEM_MAX:]
    self.mem[key] = img


class TripMap:
  def __init__(self, vs, trip, zoom=None, provider=None, levels=None):
    self.vs = vs
    self.v = vs.v
    self.trip = trip
    self.stops = trip['stops']
    self.n = len(self.stops)
    self.provider = provider or trip.get('provider', 'osm')
    # levels: how many tones to draw the tiles with. 0/None = the full
    # 16-level dither pngreader produces (the default). The plan file can ask
    # for a number ('levels: 4') and the command line can override it (-l),
    # same precedence as provider/zoom.
    lv = levels if levels is not None else trip.get('levels')
    if lv is None:
      lv = LEVELS_DEFAULT
    self.levels = lv
    self.tiles = TileStore(self.provider, trip.get('tag', 'trip'), self.levels)
    self.invert = trip.get('invert', True)
    # hop index -> (list of normalised polyline points, driving km). Filled in
    # lazily as you travel; a missing hop just draws a straight leg.
    self.routes = {}
    self.routes_tried = {}
    self.drive_km = {}
    self.base_zoom = zoom or trip.get('zoom', 13)
    self.zoom = self.base_zoom
    # fixed_zoom: the user asked for one scale for the whole session (-z), so
    # paging must not re-fit. Without -z the zoom is auto-fitted per stop and
    # a manual +/- is only a temporary override for the stop you are on.
    self.fixed_zoom = zoom is not None
    self.auto_zoom = not self.fixed_zoom

    # real geography: project every stop once (rule 6 - precompute geometry)
    self.proj = [project(s[7], s[8]) for s in self.stops]

    self.index = 0
    self.direction = 1
    # The viewport centre is kept in NORMALISED world units (0..1), not pixel
    # offsets: a hop can change zoom, and only normalised coords survive the
    # change of scale. World px = n * TILE * 2**z, computed per frame.
    self.cnx = self.proj[0][0]
    self.cny = self.proj[0][1]
    self.from_nx = self.cnx
    self.from_ny = self.cny
    self.to_nx = self.cnx
    self.to_ny = self.cny
    self.dirty = True
    self.seq = anm.anm_sequencer()
    self.anim = None

    # ---- load queue (display task -> app thread) --------------------------
    # Everything blocking (tile HTTP, PNG decode, OSRM JSON) is handed to the
    # app thread through this mailbox, so the display task can answer a key
    # press the same frame it reads it. `cmds` is the pending work, `load_gen`
    # identifies the newest viewport, and a stale load abandons itself between
    # tiles: after a burst of presses only the last one is still worth fetching.
    self.lock = _thread.allocate_lock()
    self.cmds = []
    self.load_gen = 0
    self.stopped = False
    self.running = True       # cleared by the display task on quit
    self.busy = False         # loader is inside a blocking call (for `g`)
    self.gap = None           # last frame's missing-tile window, for `g`

    # The very first viewport goes on the queue instead of being fetched here:
    # the panel and the header can draw the moment main() returns, and the map
    # fills in as the tiles land. Fetching inline cost the opening frame ~13s.
    self.queue_stop(0, False)
    self.play(0)

  # ---- projection ---------------------------------------------------------

  def wx(self, i, z):
    return self.proj[i][0] * TILE * (2.0 ** z)

  def wy(self, i, z):
    return self.proj[i][1] * TILE * (2.0 ** z)

  def hop_dist(self, a, b, z):
    dx = self.wx(a, z) - self.wx(b, z)
    dy = self.wy(a, z) - self.wy(b, z)
    return math.sqrt(dx * dx + dy * dy)

  def fit_zoom(self, a, b):
    # Biggest zoom at which the whole hop still fits the viewport. Capped at
    # AUTO_MAX: two stops a few hundred metres apart would otherwise fill a
    # frame of empty ocean, and a hop that small reads better in context.
    top = min(ZOOM_MAX, AUTO_MAX)
    for z in range(top, ZOOM_MIN - 1, -1):
      if self.hop_dist(a, b, z) <= HOP_SPAN:
        return z
    return ZOOM_MIN

  def zoom_for(self, i):
    """The zoom of stop i - a function of i alone, so a stop always looks the
    same however you arrive at it.

    goto() used to call fit_zoom(prev, i), fitting the hop you had just
    travelled. hop_dist() is symmetric but the PAIR is not, so stepping onto
    Goleta Beach from the museum framed it at z14 while stepping back onto it
    from dinner framed it at z12: six of the seven interior stops in sb-solo-sat
    disagreed. Paging forward then back snapped the scale twice per hop.

    The pair chosen here is the leg BEFORE the stop in plan order (i-1, i),
    which is exactly what draw_panel() quotes as the distance, so the scale and
    the number agree - and hops_for() already makes sure that leg's road data is
    fetched whether you arrive forwards or backwards.

    Stop 0 keeps the plan's own `zoom:` value: that number exists to frame the
    whole trip on the opening view, and holding it here means returning to the
    first stop shows what you first saw rather than a close-up of one block.
    """
    if self.n < 2 or i <= 0:
      return self.base_zoom
    return self.fit_zoom(i - 1, i)

  # ---- tile loading (runs on the app thread, never in the draw callback) --

  def origin(self, nx, ny, z):
    # viewport top-left in world px; the current stop sits under FOCUS_X.
    # draw_xbm() clips a negative x itself, so x is left as the exact pixel -
    # no byte-grid snap (that only existed to make the Python crop exact).
    s = TILE * (2.0 ** z)
    return nx * s - FOCUS_X, ny * s - (MAP_TOP + MAP_H / 2.0)

  def tile_range(self, ox, oy, z):
    # exact cover of the strip - no padding, so a 400x73 viewport is at most
    # 3x2 tiles (~6 fetches) instead of a padded 5x4 ring
    n = int(2 ** z)
    xs = int(math.floor(ox / TILE))
    xe = int(math.floor((ox + MAP_W - 1) / TILE))
    ys = int(math.floor(oy / TILE))
    ye = int(math.floor((oy + MAP_H - 1) / TILE))
    return xs, xe, ys, ye, n

  def cover_keys(self, nx, ny, z):
    """The tile keys a viewport centred on nx,ny needs. Pure math, no I/O.

    Split out of fetch_cover() on purpose: this runs on the DISPLAY TASK inside
    update(), so it must not touch the network. It turns a key press into a list
    of keys to queue, without blocking the frame that answers the key press.
    """
    ox, oy = self.origin(nx, ny, z)
    xs, xe, ys, ye, n = self.tile_range(ox, oy, z)
    keys = []
    for tx in range(xs, xe + 1):
      for ty in range(ys, ye + 1):
        if tx < 0 or ty < 0 or tx > n or ty > n:
          continue
        keys.append((z, tx, ty))
    return keys

  def fetch_cover(self, keys, gen=None):
    """Download + decode the given tiles. App thread only.

    Checks between every tile, not once per cover: a cover is up to 6 tiles and
    a cold tile costs ~2.2 s, so a check only at the top would still hold the
    loader - and with it the quit key - for over ten seconds.
    """
    for key in keys:
      if self.stopped or (gen is not None and self.is_stale(gen)):
        # A newer viewport or a quit landed while this was in flight. Tiles
        # already on disk cost nothing next time, so abandoning is cheap.
        return
      self.tiles.get(*key)
      # Demand a repaint PER TILE. Loading is asynchronous now, so a tile can
      # arrive long after the frame that would have shown it has been drawn -
      # without this the map sits hatched until the next key press. The display
      # task runs at ~150 callbacks/s, so each tile shows up as it lands and the
      # strip visibly fills in instead of snapping.
      self.dirty = True

  # ---- the load queue -------------------------------------------------------
  #
  # Producer: the display task, in response to a key. Consumer: the app thread.
  # One rule makes this safe - the lock covers ONLY the queue list and the
  # generation counter. It is never held across an HTTP request or a PNG decode,
  # because that would hand the display task a multi-second wait on a lock and
  # put us straight back where we started. The tile memos are single dict
  # writes, which are atomic on their own, so a reader sees a tile as either
  # absent or complete - the same invariant TileStore already relied on.

  def _enqueue(self, cmd):
    self.lock.acquire()
    try:
      if len(self.cmds) >= QUEUE_MAX:
        # A burst of presses the loader has not caught up with. Keeping the
        # newest viewport is what the user is looking at, so drop the oldest
        # rather than growing a queue that is already stale.
        del self.cmds[0]
      self.cmds.append(cmd)
    finally:
      self.lock.release()

  def _dequeue(self):
    self.lock.acquire()
    try:
      return self.cmds.pop(0) if self.cmds else None
    finally:
      self.lock.release()

  def is_stale(self, gen):
    self.lock.acquire()
    try:
      return gen != self.load_gen
    finally:
      self.lock.release()

  def queue_stop(self, i, also_from=True, prev=None):
    """Ask the app thread to load stop i. Display task: math only, never I/O."""
    self.lock.acquire()
    self.load_gen += 1
    gen = self.load_gen
    self.lock.release()
    z = self.zoom
    keys = self.cover_keys(self.proj[i][0], self.proj[i][1], z)
    if also_from:
      # Cover the viewport we are leaving as well, so the slide is painted the
      # whole way instead of panning into holes.
      for k in self.cover_keys(self.cnx, self.cny, z):
        if k not in keys:
          keys.append(k)
    self._enqueue(('load', gen, keys, self.hops_for(i, prev)))
    return gen

  def hops_for(self, i, prev=None):
    """The route hops worth pulling for stop i. Display task: math only.

    Road geometry is decoration, not layout, so only fetch the hops you can
    actually see. A jump from first to last spans a dozen hops; the loader works
    through this list in order and can be cancelled between any two of them.
    The panel quotes the distance of hop (index-1) - the leg you just travelled
    - so that one must be in the window even when stepping backwards, where
    range(prev, i) would otherwise miss it entirely. `prev` has to be passed in:
    goto() has already moved self.index to i by the time it asks.
    """
    if prev is None:
      prev = i
    lo, hi = (prev, i) if prev < i else (i, prev)
    hops = list(range(lo, hi))
    if 0 <= i - 1 < self.n - 1 and i - 1 not in hops:
      hops.append(i - 1)
    hops.sort(key=lambda h: min(abs(h - i), abs(h + 1 - i)))
    return hops[:3]

  # ---- road geometry ------------------------------------------------------

  def route_path(self, i):
    return '%s/%s_r%d.json' % (CACHE_DIR, self.tiles.tag, i)

  def fetch_route(self, i):
    """Ask OSRM for the real drive from stop i to stop i+1.

    Cached on disk, so a trip you have looked at once opens instantly. Returns
    a list of normalised points (possibly empty -> the caller draws a straight
    leg). Called from the app thread, never from the draw callback.
    """
    if i in self.routes or self.routes_tried.get(i):
      return self.routes.get(i)
    self.routes_tried[i] = 1
    a = self.stops[i]
    b = self.stops[i + 1]
    path = self.route_path(i)
    pts = None
    try:
      pts = self._read_route(path)
    except OSError:
      pts = None
    if pts is None:
      try:
        coords = '%s,%s;%s,%s' % (a[8], a[7], b[8], b[7])
        status, hdr, body = http.request(OSRM % coords, user_agent=UA,
                                         timeout=25)
        if status.find('200') < 0:
          return None
        with open(path, 'wb') as f:
          f.write(body)
        pts = self._read_route(path)
      except Exception:
        return None
    if not pts:
      return None
    self.routes[i] = pts
    # The road usually lands a second after the pan began, i.e. after the frame
    # was drawn. Flag the screen dirty so the real line replaces the straight
    # placeholder without waiting for the next key press.
    self.dirty = True
    return pts

  def _read_route(self, path):
    import json
    d = json.loads(open(path, 'rb').read())
    coords = d['routes'][0]['geometry']['coordinates']
    pts = [project(c[1], c[0]) for c in coords]
    # distance of the actual drive, in km, for the panel read-out
    self.drive_km[path] = d['routes'][0]['distance'] / 1000.0
    return pts

  # ---- animation ----------------------------------------------------------

  def play(self, direction):
    self.direction = direction or 1
    self.from_nx, self.from_ny = self.cnx, self.cny
    self.to_nx, self.to_ny = self.proj[self.index]
    self.anim = anm.anm_object(700, {'t': [anm.linear, 0.0, 1.0]})
    self.seq.register('go', self.anim)
    self.dirty = True

  def _animating(self):
    return self.anim is not None and self.anim.get_time() < 1.0

  def _t(self):
    return clamp01(self.anim.t) if self.anim is not None else 1.0

  def goto(self, i):
    """Page transition. Runs on the DISPLAY TASK, so this touches no I/O: it
    moves the page state, starts the pan and hands the loading to the app
    thread. The old version prefetched here, which is why a page press cost up
    to 20 s of dead keyboard - and would now have cost it to every screen."""
    i = max(0, min(self.n - 1, i))
    prev = self.index
    if i == prev:
      self.play(0)
      self.queue_stop(i, False)
      return
    self.index = i
    if not self.fixed_zoom:
      # zoom_for(i) depends on i alone - never on `prev` - so the same stop
      # always frames the same way whichever direction you paged in from.
      # This also re-enables autozoom after a manual +/-: set_zoom() only
      # overrides the scale of the stop you are on, and arriving somewhere new
      # is a new question about scale, so the answer is recomputed here.
      self.auto_zoom = True
      self.zoom = self.zoom_for(i)
    # Start the pan before the load is queued: the map slides on the frames the
    # display task produces while the tiles arrive behind it.
    self.play(1 if i > prev else -1)
    self.queue_stop(i, True, prev)

  # ---- drawing ------------------------------------------------------------

  def draw_header(self):
    v = self.v
    v.set_draw_color(1)
    v.set_dither(16)
    v.draw_box(0, 0, W, 20)
    v.set_draw_color(0)
    v.set_font(BODY_FONT)
    # Right edge stops short of BADGE_W: the firmware composites a screen-number
    # badge over that corner and it would land on top of anything we draw there.
    edge = W - BADGE_W
    # the tone count rides along so the `d` setting is never a mystery
    tag = 'z%d%s  %d/%d' % (self.zoom, self.tone_tag(), self.index + 1, self.n)
    title = fit(v, self.trip.get('title', 'TRIP'), 150)
    tag_w = v.get_utf8_width(tag)
    # facts fill whatever gap is left between the title and the pager - all
    # measured, so nothing on the inverted bar can collide or run off
    gap_l = 6 + v.get_utf8_width(title) + 8
    gap_r = edge - 8 - tag_w
    facts = '  '.join(self.trip.get('facts', ()))
    if facts:
      v.set_font(SMALL_FONT)
      facts = fit(v, facts, max(0, gap_r - gap_l))
      fw = v.get_utf8_width(facts)
      if fw:
        v.draw_str(gap_l + (gap_r - gap_l - fw) // 2, 15, facts)
      v.set_font(BODY_FONT)
    v.draw_str(6, 15, title)
    v.draw_str(edge - tag_w, 15, tag)
    v.set_draw_color(1)

  def draw_map(self):
    v = self.v
    t = self._t()
    slide = anm.ease_out(clamp01(t / 0.8))
    self.cnx = self.from_nx + (self.to_nx - self.from_nx) * slide
    self.cny = self.from_ny + (self.to_ny - self.from_ny) * slide
    z = self.zoom

    ox, oy = self.origin(self.cnx, self.cny, z)
    _z = z

    v.set_draw_color(1)
    xs, xe, ys, ye, maxn = self.tile_range(ox, oy, z)
    have = 0
    total = 0
    for tx in range(xs, xe + 1):
      for ty in range(ys, ye + 1):
        if tx < 0 or ty < 0 or tx > maxn or ty > maxn:
          continue
        total += 1
        # src(), not mem.get(): this is where the level setting takes effect.
        # It is a memo read for every tile that prefetch() already warmed, so
        # the quantize pass never runs inside the display callback.
        img = self.tiles.src((z, tx, ty))
        sx = int(tx * TILE - ox)
        sy = int(ty * TILE - oy)
        if img is None:
          continue
        have += 1
        blit_rect = blit_tile(sx, sy, img, MAP_TOP, MAP_BOT + 1)
        if blit_rect is None:
          continue
        cx, cy, cwid, chgt, cdata = blit_rect
        if self.invert:
          # Web tiles are drawn for paper: land is near-white, and the roads,
          # labels and coastlines are the DARK features. pngreader turns
          # brightness into ink, so a plain blit washes the strip out. Filling
          # the tile white first and blitting in colour 0 flips it into a
          # glowing line map on black - all in C, no per-pixel work in Python.
          # A negative cx is fine: draw_box clips like draw_xbm does.
          v.set_draw_color(1)
          v.draw_box(cx, cy, cwid, chgt)
          v.set_draw_color(0)
          v.draw_xbm(cx, cy, cwid, chgt, cdata)
          v.set_draw_color(1)
        else:
          v.draw_xbm(cx, cy, cwid, chgt, cdata)
    # Recorded on EVERY frame, not only on a gap. An earlier version only wrote
    # it when have < total, so once the map finished the last gap-stamped frame
    # stayed on record and `g` reported a hole that had already been filled.
    self.gap = None if have >= total else (z, xs, xe, ys, ye, have, total)
    if have < total:
      # Gaps are now the NORMAL state for a second or two at a time: the loader
      # fills them in asynchronously. So nothing expensive may happen here - the
      # old version wrote /sd/work/tripdebug.txt on every frame that had a gap,
      # which is an SD write on the display task several times a second. Record
      # the gap in memory instead; `g` dumps it from the app thread.
      # hatch the gaps so a loading map looks deliberate, not broken
      v.set_dither(6)
      for tx in range(xs, xe + 1):
        for ty in range(ys, ye + 1):
          if self.tiles.mem.get((z, tx, ty)) is not None:
            continue
          v.draw_box(int(tx * TILE - ox), int(ty * TILE - oy), TILE, TILE)
      v.set_dither(16)

    # route. Each leg follows the real roads OSRM returned; legs whose drive
    # was never fetched fall back to a straight line between the two stops.
    pts = []
    for i in range(self.n):
      pts.append((int(self.wx(i, z) - ox), int(self.wy(i, z) - oy)))
    for i in range(self.n - 1):
      v.set_dither(16 if i < self.index else 9)
      road = self.routes.get(i)
      if road:
        px = int(road[0][0] * TILE * (2.0 ** z) - ox)
        py = int(road[0][1] * TILE * (2.0 ** z) - oy)
        for q in road[1:]:
          qx = int(q[0] * TILE * (2.0 ** z) - ox)
          qy = int(q[1] * TILE * (2.0 ** z) - oy)
          v.draw_line(px, py, qx, qy)
          px, py = qx, qy
      else:
        v.draw_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
      v.set_dither(16)

    # markers, current one last and largest
    for i in range(self.n):
      sx, sy = pts[i]
      if sx < -20 or sx > W + 20 or sy < MAP_TOP - 20 or sy > MAP_BOT + 20:
        continue
      if i == self.index:
        ring = int(7 + 12 * (1.0 - anm.ease_out(clamp01((t - 0.3) / 0.65))))
        if t < 1.0:
          v.set_draw_color(0)
          v.draw_circle(sx, sy, ring + 3, 15)
          v.set_draw_color(1)
          v.set_dither(13)
          v.draw_circle(sx, sy, ring, 15)
          v.set_dither(16)
        v.set_draw_color(0)
        v.draw_disc(sx, sy, 6, 15)          # punched halo keeps it legible
        v.set_draw_color(1)
        v.draw_disc(sx, sy, 3, 15)
        v.set_font(BODY_FONT)
        self._boxed_label(sx - 4, sy - 9, fit(v, self.stops[i][1], 92), top=True)
      elif self.is_leg(i):
        # A drive leg is a point ON the route, not a place to visit, so an
        # unselected leg is a plain tick: no numbered disc, no label. The route
        # still passes through it, which is the whole point - PCH -> 101 ->
        # hotel bends, and two stops joined by a straight line would lie about
        # it. The CURRENT stop keeps the full highlight even when it is a leg
        # (the branch above is untouched), because you paged there and need to
        # see where you landed.
        v.set_draw_color(0)
        v.draw_disc(sx, sy, 3, 15)
        v.set_draw_color(1)
        v.draw_circle(sx, sy, 1, 15)
      else:
        v.set_draw_color(0)
        v.draw_disc(sx, sy, 4, 15)
        v.set_draw_color(1)
        if i < self.index:
          v.draw_disc(sx, sy, 2, 15)
        else:
          v.draw_circle(sx, sy, 2, 15)
        if abs(i - self.index) == 1:
          v.set_font(SMALL_FONT)
          label = fit(v, self.stops[i][1], 58)
          self._boxed_label(sx - 2, sy + 14, label, top=True)

    v.set_draw_color(1)
    v.draw_frame(0, MAP_TOP, W, MAP_H)
    v.set_font(SMALL_FONT)
    #self._boxed_label(7, 32, self.trip.get('map_note', 'OpenStreetMap'))
    v.set_font(BODY_FONT)

    # Tiles and route legs are not clipped by the hardware, so wipe everything
    # below the strip before the panel draws. (The header wipes the top.)
    v.set_draw_color(0)
    v.draw_box(0, MAP_BOT + 1, W, H - MAP_BOT - 1)
    v.set_draw_color(1)

  def _boxed_label(self, x, y, text, top=False):
    # y is the baseline: clear behind the glyphs so labels beat the busy tiles
    v = self.v
    w = v.get_utf8_width(text)
    x = max(2, min(W - 2 - w, x))
    v.set_draw_color(0)
    v.draw_box(x - 2, y - 10, w + 4, 13)
    v.set_draw_color(1)
    v.draw_str(x, y, text)

  def _mask(self, row, y_top, y_bot):
    # Staggered wipe reveal: the text is drawn first, then the part the wipe
    # has not reached is punched clear. Next stop wipes L->R, previous R->L.
    if not self.animating:
      return
    reveal = self.reveal
    r = reveal[row] if row < len(reveal) else 1.0
    if r >= 1.0:
      return
    v = self.v
    span = int(r * (RIGHT - MARGIN))
    v.set_draw_color(0)
    if self.direction >= 0:
      v.draw_box(MARGIN + span, y_top, W, y_bot - y_top)
    else:
      v.draw_box(0, y_top, RIGHT - span, y_bot - y_top)
    v.set_draw_color(1)

  def draw_panel(self, animating):
    v = self.v
    t = self._t()
    when, label, title, cat, addr, body, tip = self.stops[self.index][:7]

    v.set_font(BODY_FONT)
    lines = wrap(v, body, RIGHT - MARGIN, BODY_MAX)
    reveal = []
    for i in range(len(lines) + 3):
      reveal.append(anm.ease_out(clamp01((t - 0.26 - i * 0.06) / 0.4)))

    # Reveal state lives on self so the wipe helper is a plain method call:
    # MicroPython's handling of nested closures here is fragile.
    self.animating = animating
    self.reveal = reveal

    tw = v.get_utf8_width(when) + 12
    v.set_dither(16)
    v.draw_rbox(MARGIN, CHIP_Y, tw, CHIP_H, 3)
    v.set_draw_color(0)
    v.draw_str(MARGIN + 6, CHIP_Y + 12, when)
    v.set_draw_color(1)

    cx = MARGIN + tw + 6
    cw = v.get_utf8_width(cat) + 10
    v.draw_rframe(cx, CHIP_Y, cw, CHIP_H, 3)
    v.draw_str(cx + 5, CHIP_Y + 12, cat)
    mask = self._mask
    mask(0, CHIP_Y - 3, CHIP_Y + CHIP_H + 3)

    v.set_font(TITLE_FONT)
    v.draw_str(MARGIN, TITLE_Y, fit(v, title, RIGHT - MARGIN))
    mask(1, TITLE_Y - 18, TITLE_Y + 5)

    # address on the left, hop distance right-aligned - measured so the two
    # never collide or push the address off the edge
    dist = ''
    if self.index > 0:
      road = self.drive_km.get(self.route_path(self.index - 1))
      km = road if road else self.km(self.index - 1, self.index)
      # Two stops at the same place (the sunset is on Leo Carrillo's beach)
      # should not announce a zero-length drive.
      if km >= 0.6:
        dist = ('%.0f km drive' % road) if road else ('%.1f km direct' % km)
      else:
        dist = 'same spot'
    # The distance gets a FIXED slot rather than its own measured width, so
    # the address truncates at the same column on every stop - a layout that
    # shifts by a few pixels per hop reads as jitter, not as design.
    v.set_font(SMALL_FONT)
    avail = RIGHT - MARGIN - DIST_W
    v.draw_str(MARGIN, SUB_Y, fit(v, addr, avail))
    if dist:
      v.draw_str(RIGHT - v.get_utf8_width(dist), SUB_Y, dist)
    mask(2, SUB_Y - 10, SUB_Y + 4)

    v.set_font(BODY_FONT)
    v.set_dither(11)
    v.draw_h_line(MARGIN, RULE_Y, RIGHT - MARGIN)
    v.set_dither(16)

    for i, line in enumerate(lines):
      v.draw_str(MARGIN, BODY_TOP + i * BODY_LH, line)
      mask(i + 3, BODY_TOP + i * BODY_LH - 12, BODY_TOP + i * BODY_LH + 4)

    frac = self.index / float(self.n - 1)
    v.set_dither(5)
    v.draw_h_line(MARGIN, BAR_Y, RIGHT - MARGIN)
    v.set_dither(16)
    v.draw_h_line(MARGIN, BAR_Y, int((RIGHT - MARGIN) * frac))
    for i in range(self.n):
      tx = MARGIN + int((RIGHT - MARGIN) * i / float(self.n - 1))
      v.draw_v_line(tx, BAR_Y - 2, 5)
    v.draw_disc(MARGIN + int((RIGHT - MARGIN) * frac), BAR_Y, 3, 15)

    # Footer band: no background at all. clear_buffer() already leaves it white,
    # and the pale dither that used to fill this band read as if the TIP text
    # itself were halftoned - the lattice sat right under the small font. So the
    # band keeps only its solid black rule; the tip is plain black on white.
    # (Do NOT "fix" this with draw_box under set_dither(16) while color is 1 -
    # that fills with black, not white.)
    v.set_dither(16)
    v.draw_h_line(0, TIP_TOP, W)
    v.set_font(SMALL_FONT)
    v.draw_str(MARGIN, H - 5, fit(v, 'TIP: ' + tip, RIGHT - MARGIN))
    v.set_font(BODY_FONT)

  def is_leg(self, i):
    """True when stop i is a drive waypoint, not a destination.

    tripplan.py adds an optional 10th field ('drive: true'); a plain
    trip_<name>.py resource is a 9-tuple and is never a leg, so this stays
    backwards compatible by length-testing rather than by dict lookup.
    """
    s = self.stops[i]
    return len(s) > 9 and s[9]

  def km(self, a, b):
    # great-circle distance between two stops - real mileage, not map px
    la1, lo1 = self.stops[a][7], self.stops[a][8]
    la2, lo2 = self.stops[b][7], self.stops[b][8]
    p = math.pi / 180.0
    dl = math.sin((la2 - la1) * p / 2) ** 2
    dl += math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(dl), math.sqrt(1 - dl))

  def draw(self):
    v = self.v
    animating = self._animating()
    v.clear_buffer()
    self.draw_map()
    self.draw_panel(animating)
    self.draw_header()
    v.finished()

  def update(self, e):
    """The frame callback: runs on the DISPLAY TASK. Reads input and moves page
    state here, but never downloads anything - every byte of I/O goes out on the
    queue for the app thread. This is what keeps a key press answering in the
    same frame it is read, even while 6 tiles are in flight."""
    if not self.v.active:
      # Inactive: no input, no drawing, but still hand the queue nothing. The
      # loader keeps draining what was already asked for, which is fine.
      self.v.finished()
      return
    k = self.poll_key()
    if k:
      self.on_key(k)
    self.seq.update(time.ticks_ms())
    if e or self.dirty or self._animating():
      self.draw()
      self.dirty = False
    else:
      self.v.finished()

  # ---- input --------------------------------------------------------------

  def poll_key(self):
    """Non-blocking key read, same idiom as graph.py:read_key().

    read_nb(1) takes one byte without waiting, and vs.poll() says whether the
    REST of an escape sequence has landed yet. Only pull the tail when poll()
    says it is there: vs.read() blocks, and blocking inside a frame callback
    stalls the display task for every screen, which is the exact failure this
    rework exists to remove. A lone Esc therefore reads as b'\\x1b' (ignored
    here) instead of waiting on bytes that will never come.
    """
    ret = self.v.read_nb(1)
    if not ret or ret[0] <= 0:
      return None
    k = ret[1].encode('ascii')
    if k == b'\x1b':
      seq = [k]
      if self.vs.poll():
        seq.append(self.vs.read(1).encode('ascii'))
      if len(seq) > 1 and seq[-1] == b'[' and self.vs.poll():
        seq.append(self.vs.read(1).encode('ascii'))
      return b''.join(seq)
    return k

  def on_key(self, k):
    """Handle one key. Display task: page state and queue commands ONLY - no
    file, no network, no per-tile requantize. Each of those is a command."""
    if k == b'q' or k == b'\x08':
      self.quit()
    elif k in (b'\x1b[A', b'\x1b[C', b'n'):
      self.goto(self.index + 1)
    elif k in (b'\x1b[B', b'\x1b[D', b'p'):
      self.goto(self.index - 1)
    elif k == b'h':
      self.goto(0)
    elif k == b'e':
      self.goto(self.n - 1)
    elif k == b'r':
      self.play(0)
    elif k == b'+' or k == b'=':
      self.set_zoom(self.zoom + 1)
    elif k == b'-':
      self.set_zoom(self.zoom - 1)
    elif k == b'g':
      # Retry the tiles that hit FAIL_MAX. Ordering matters and both halves are
      # queued from here: the retry command clears the loader's failure counts,
      # and only then does a fresh load get enqueued, so the loader never
      # short-circuits the tiles we are asking it to give up. Building the new
      # viewport on the display task (cover_keys is pure math) keeps every
      # mutation of shared view state single-threaded.
      self._enqueue(('retry', None))
      self.queue_stop(self.index, False)
      self.dirty = True
    elif k == b'i':
      # flip map polarity: line-map-on-black vs raw tile brightness.
      # Polarity is chosen at blit time, so no tile has to be re-decoded.
      self.invert = not self.invert
      self.dirty = True
    elif k == b'd':
      # cycle the tile tone count (4 -> 6 -> full). Both copies of every tile
      # are memoized, so the visible change is instant; the requantize that
      # fills in the reduced copies is the loader's job.
      self.cycle_levels()

  def quit(self):
    """Stop the app. Sets the flags rather than unwinding anything: the loader
    notices between tiles and returns, and main()'s finally restores the text
    console. A tile already in flight still has to finish its HTTP call, so
    quitting during a fetch costs up to one tile (~2 s), not the whole queue."""
    self.running = False
    self.stopped = True

  def set_levels(self, levels):
    """Change the tile tone count. No re-decode, no network, no re-fetch.

    TileStore.set_levels() only drops the reduced-tone memo (cheap). Re-warming
    is a histogram pass per tile, so that goes to the loader as a command.
    Until it runs, src() falls back to the full-dither bitmap - the map is
    readable the whole time.
    """
    if levels == self.levels:
      return
    self.levels = levels
    self.tiles.set_levels(levels)
    self._enqueue(('warm', None))
    self.dirty = True

  def cycle_levels(self):
    # Off-cycle values (a plan may ask for any 2..16) join the cycle at its
    # start rather than being skipped forever.
    try:
      i = LEVELS_CYCLE.index(self.levels)
    except ValueError:
      i = -1
    self.set_levels(LEVELS_CYCLE[(i + 1) % len(LEVELS_CYCLE)])

  def tone_tag(self):
    """The header's tone-count hint, so the current `d` setting is visible."""
    if not self.levels:
      return ''
    return '  %dt' % self.levels

  def set_zoom(self, z):
    z = max(ZOOM_MIN, min(ZOOM_MAX, z))
    if z == self.zoom:
      return
    # A manual zoom is an override of THIS stop only, not a mode switch: the
    # next stop re-fits itself (goto() turns autozoom back on). Pinning the
    # whole session still works, with -z on the command line.
    self.auto_zoom = False
    self.zoom = z
    # The new scale needs a fresh set of tiles; the old ones are already on disk
    # and the queue's generation counter retires whatever was in flight.
    self.queue_stop(self.index, False)
    self.play(0)

  # ---- the app thread: everything that blocks -----------------------------

  def dump_debug(self):
    """Write the last frame's missing-tile window to SD. App thread only.

    Replaces the version of this that ran inside draw_map(): with asynchronous
    loading, a frame with gaps is the normal case for a second or two at a time,
    so writing a file there meant an SD write several times a second on the
    display task.
    """
    try:
      f = open(DEBUG_LOG, 'w')
      f.write('gap=%r\n' % (self.gap,))
      f.write('zoom=%d stopped=%s load_gen=%s\n' %
              (self.zoom, self.stopped, self.load_gen))
      f.write('failed=%r\n' % (list(self.tiles.failed.items())[:20],))
      f.write('last_err=%s\n' % getattr(self.tiles, 'last_err', None))
      f.write('mem=%d queued=%d\n' % (len(self.tiles.mem), len(self.cmds)))
      # 'busy' distinguishes a loader that is still working from one that is
      # wedged or dead: busy=1 with a gap means an HTTP call is in flight right
      # now, busy=0 with a gap and queued=0 means the queue really is drained.
      f.write('busy=%s q=%r\n' % (self.busy, self.cmds[:6]))
      f.close()
    except Exception:
      pass

  def loader_loop(self):
    """Drains the command queue. This IS the app thread (main() calls it), so
    curl, pngreader and the OSRM request block here and never in a frame.

    MicroPython threads share one interpreter and switch at bytecode
    boundaries, so this is cooperative, not parallel: it buys input latency and
    continuous animation, not extra bandwidth. That is the right trade - the
    bug was a long I/O wait sitting on the thread that had to read keys.

    `IDLE_TICK` paces the empty-queue case. Busy-polling the list instead would
    starve the display task whose frames we restructured all this to protect.
    """
    while True:
      if not self.running:
        return
      cmd = self._dequeue()
      if cmd is None:
        pdeck.delay_tick(IDLE_TICK)
        continue
      op = cmd[0]
      if op == 'retry':
        # `g`: give the tiles that hit FAIL_MAX another chance. Only the clear
        # happens here - the replacement load was queued by the display task
        # right behind this command. The last frame's gap window is dumped now
        # rather than in draw_map(), because an SD write on the display task
        # stalls every screen on the device.
        self.dump_debug()
        self.tiles.failed.clear()
        continue
      if op == 'warm':
        self.tiles.warm_all()
        self.dirty = True
        continue
      gen = cmd[1]
      if gen is not None and self.is_stale(gen):
        continue
      self.busy = True
      try:
        # Tiles before roads: the basemap is the picture, the route line is
        # decoration that may land a second later.
        self.fetch_cover(cmd[2], gen)
        if op == 'load':
          for h in cmd[3]:
            if self.stopped or self.is_stale(gen):
              break
            self.fetch_route(h)
      finally:
        self.busy = False


def load_trip(name):
  # Drop any cached copy so editing the trip file takes effect on the next run.
  import sys
  modname = 'trip_' + name
  if modname in sys.modules:
    del sys.modules[modname]
  trip = getattr(__import__(modname), 'TRIP')
  trip.setdefault('tag', clip(name.replace('-', '_'), 12))
  return trip


def main(vs, args):
  v = vs.v
  # NB: the device argparse is a reduced clone - no prog=, no choices=.
  parser = argparse.ArgumentParser(
    description='Browse a trip plan over a real OpenStreetMap basemap.')
  parser.add_argument('trip', nargs='?', default='malibu',
                      help='trip name: loads /sd/py/trip_<name>.py')
  parser.add_argument('-z', '--zoom', type=int, default=None,
                      help='fixed map zoom (default: auto-fit each hop)')
  parser.add_argument('-p', '--provider', default=None,
                      help='tile style: osm or topo (default: from trip file)')
  parser.add_argument('-l', '--levels', type=int, default=None,
                      help='tile tone count (4 = default, 0 = full 16)')
  opts = parser.parse_args(args[1:])

  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  try:
    trip = load_trip(opts.trip)
  except Exception as e:
    v.print(el.display_mode(True))
    print('tripmap: cannot load trip_%s.py (%r)' % (opts.trip, e), file=vs)
    return
  app = TripMap(vs, trip, opts.zoom, opts.provider, opts.levels)
  # Split threads: the display task owns update() (input + page state + draw),
  # this app thread owns every blocking byte of I/O. Registering the callback
  # before the loop starts means the first viewport is already queued and the
  # opening frame is instant.
  v.callback(app.update)
  try:
    app.loader_loop()
  finally:
    v.callback(None)
    v.print(el.display_mode(True))
