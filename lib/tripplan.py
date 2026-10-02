# tripplan.py - turn a Markdown trip plan into the tripmap engine's data.
#
#   tripplan malibu                 <- /sd/Documents/trips/malibu.md
#                                      (or the shipped /sd/lib/data/trips/malibu.md)
#   tripplan /sd/Documents/trips/kyoto.md
#   tripplan malibu --check         <- validate and report, do not draw
#   tripplan malibu --dump          <- print the TRIP dict the engine gets
#   tripplan --list
#
# The document is the plan you (or the AI) write: prose for a human, plus
# machine fields inside ```tripplan fences. The parser reads ONLY the fences
# and the '## ' headings; every other line is decoration it never looks at.
# That keeps the round trip deterministic: no NLP on headings, no guessing,
# and a missing field is a printed error instead of a wrong map.
#
# Format contract (see /sd/Documents/skills/tripplan.md):
#
#   # TRIP TITLE                  <- header bar, <= 21 chars
#   ```tripplan                   <- first fence, before any '##' = trip meta
#   facts: LOW 12:14  SET 18:53   <- repeatable, becomes a tuple
#   provider: osm | topo
#   zoom: 13
#   levels: 4                     <- optional tile tone count (0 = full 16)
#   map_note: Map data (c) OpenStreetMap
#   ```
#
#   ## Surf: Zuma Beach           <- stop title, <= 32 chars
#   ```tripplan
#   when: 9:45                    <- key at column 0
#   label: Zuma                   <- the map marker word, <= 13 chars
#   cat: SURF
#   addr: 30000 PCH               <- <= 51 chars
#   lat: 34.0214393               <- REQUIRED: the app never geocodes, so it
#   lon: -118.8310349                works offline on the beach
#   body: Wide sand, sand bottom,  <- <= 220 chars (55/line x 4). Continuation
#     a tower every few hundred      lines are INDENTED; joining them back
#     yards.                         with one space rebuilds the value.
#   tip: Leash is not optional     <- <= 54 chars
#   drive: true                   <- optional. A leg, not a place: the panel
#                                     and the route still use it, the map
#                                     draws no numbered marker (tripmap.py)
#   ```
#
# Coordinates were geocoded by the tripplan skill and validated against the
# place name and the trip bounding box before they were written here.

import os
import argparse

TRIP_DIR = '/sd/Documents/trips'
# Folders searched in order for a plan name: the user's own trips first, then
# the sample plans shipped with the app. A file dropped in TRIP_DIR always
# shadows the shipped one of the same name.
TRIP_DIRS = (TRIP_DIR, '/sd/lib/data/trips')
FENCE = '```tripplan'

# Hard panel budgets, measured on the device with get_utf8_width():
# each is the longest value that survives the slot's font and the fit()
# truncation. Over budget is a warning (the engine clips with ' ..'), a
# missing field is an error (the engine would index a short tuple).
BUDGET = {
  'when': 10,    # profont15 chip
  'label': 13,   # profont15, current marker fits 92px
  'title': 32,   # profont22 title line, 388px
  'cat': 14,     # profont15 framed chip
  'addr': 51,    # profont11, 80px reserved for the drive read-out
  'body': 220,   # profont15, 55 chars/line x BODY_MAX 4
  'tip': 54,     # profont11, after the engine's 'TIP: ' prefix
  'trip_title': 21,
  'map_note': 40,
}
REQ_STOP = ('when', 'label', 'cat', 'addr', 'body', 'tip', 'lat', 'lon')
OPT_STOP = ('drive',)
META_KEYS = ('facts', 'provider', 'zoom', 'map_note', 'tag', 'invert', 'title',
             'levels')
# 'facts' may repeat; each line adds one element to the tuple.
LIST_KEYS = ('facts',)


def clip(s, n):
  return s[:n]


def isfile(p):
  # This MicroPython build has no os.path. stat() proves it exists, and
  # listdir() proves it is not a directory - both raise OSError otherwise,
  # which holds on the device and on the CPython emulator.
  try:
    os.stat(p)
  except OSError:
    return False
  try:
    os.listdir(p)
  except OSError:
    return True
  return False


class PlanError(Exception):
  pass


# ---- fence reading ---------------------------------------------------------

def is_key(raw):
  # A field line starts at column 0. Anything indented is a continuation of
  # the previous value, which is what lets a 220-char body be written wrapped.
  return raw[:1] not in ('', ' ', '\t')


def read_block(body, out):
  """Merge one fence body into the dict `out`. Returns out."""
  key = None
  for raw in body:
    if not raw.strip():
      key = None                      # a blank line ends the value
      continue
    if raw[0] == '#':
      key = None
      continue
    if not is_key(raw):
      if key is not None:
        out[key] = out[key] + ' ' + raw.strip()
      continue
    if ':' not in raw:
      key = None
      continue
    k, v = raw.split(':', 1)
    key = k.strip().lower()
    v = v.strip()
    if key in LIST_KEYS and key in out:
      out[key] = out[key] + [v]
    else:
      out[key] = [v] if key in LIST_KEYS else v
  return out


def read_fences(lines):
  """-> list of (line_no, field dict), in document order, for every fence."""
  blocks = []
  i = 0
  n = len(lines)
  while i < n:
    if lines[i].strip() == FENCE:
      j = i + 1
      body = []
      closed = False
      while j < n:
        if lines[j].strip() == '```':
          closed = True
          break
        body.append(lines[j].rstrip())
        j += 1
      if not closed:
        raise PlanError('line %d: %s fence is never closed' % (i + 1, FENCE))
      blocks.append((i + 1, read_block(body, {})))
      i = j + 1
      continue
    i += 1
  return blocks


def headings(lines):
  """-> list of (line_no, level, text) for '# ' and '## ' only."""
  out = []
  for i, raw in enumerate(lines):
    s = raw.rstrip()
    if s.startswith('## '):
      out.append((i + 1, 2, s[3:].strip()))
    elif s.startswith('# '):
      out.append((i + 1, 1, s[2:].strip()))
  return out


# ---- parsing ---------------------------------------------------------------

def parse(text, name='trip'):
  """Markdown text -> (trip dict, warnings). Raises PlanError on anything the
  engine could not draw."""
  lines = text.split('\n')
  hs = headings(lines)
  blocks = read_fences(lines)

  trip_title = None
  for (ln, lvl, txt) in hs:
    if lvl == 1:
      trip_title = txt
      break
  if not trip_title:
    # No H1: fall back to the file name rather than drawing a blank bar.
    trip_title = name.replace('-', ' ').upper()

  meta = {}
  stops = []
  # A fence before the first '## ' is trip metadata; each '## ' starts a stop
  # and takes the next fence under it.
  sec = [(ln, txt) for (ln, lvl, txt) in hs if lvl == 2]
  for (ln, fields) in blocks:
    owner = None
    for (sln, txt) in sec:
      if sln < ln:
        owner = (sln, txt)
    if owner is None:
      meta.update(fields)
      continue
    if fields.get('__stop') != owner[0]:
      stops.append({'title': owner[1], '__stop': owner[0]})
    cur = stops[-1]
    for k, v in fields.items():
      if k in cur and k in LIST_KEYS:
        cur[k] = cur[k] + v
      else:
        cur[k] = v

  errors, warns = [], []
  if not sec:
    errors.append('no "## " stop headings found')
  for i, (ln, txt) in enumerate(sec):
    if i >= len(stops) or stops[i].get('__stop') != ln:
      stops.insert(i, {'title': txt, '__stop': ln})
      errors.append('line %d: stop "%s" has no %s block' % (ln, clip(txt, 24), FENCE))

  out_stops = []
  for s in stops:
    ln = s.get('__stop', 0)
    label = clip(s.get('label', s.get('title', '?')), 16)
    missing = [k for k in REQ_STOP if not s.get(k)]
    if missing:
      errors.append('stop "%s" (line %d) missing: %s' %
                    (label, ln, ', '.join(missing)))
      continue
    try:
      lat = float(s['lat'])
      lon = float(s['lon'])
    except ValueError:
      errors.append('stop "%s" (line %d): lat/lon must be decimal degrees, '
                    'got %s / %s' % (label, ln, s.get('lat'), s.get('lon')))
      continue
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
      errors.append('stop "%s" (line %d): lat/lon out of range (%.4f, %.4f)' %
                    (label, ln, lat, lon))
      continue
    for k in ('when', 'label', 'title', 'cat', 'addr', 'body', 'tip'):
      v = s.get(k, '')
      if len(v) > BUDGET[k]:
        warns.append('stop "%s": %s is %d chars, panel fits %d - the rest '
                     'will be clipped' % (label, k, len(v), BUDGET[k]))
    tup = (s['when'], s['label'], s.get('title', ''), s['cat'], s['addr'],
           s['body'], s['tip'], lat, lon)
    if truthy(s.get('drive')):
      # 10th element: tripmap.py draws a leg waypoint, not a numbered marker.
      tup = tup + (1,)
    out_stops.append(tup)

  if len(out_stops) < 2:
    errors.append('need at least 2 usable stops, got %d' % len(out_stops))

  facts = meta.get('facts')
  if facts is None:
    facts = ()
  elif isinstance(facts, str):
    facts = (facts,)
  else:
    facts = tuple(facts)
  if len(trip_title) > BUDGET['trip_title']:
    warns.append('trip title is %d chars, the header bar fits %d' %
                 (len(trip_title), BUDGET['trip_title']))
  #note = meta.get('map_note', 'Map data (c) OpenStreetMap')
  provider = meta.get('provider', 'osm')
  if provider not in ('osm', 'topo'):
    errors.append('provider must be osm or topo, got "%s"' % provider)
  zoom = meta.get('zoom')
  if zoom is not None:
    try:
      zoom = int(zoom)
    except ValueError:
      errors.append('zoom must be an integer, got "%s"' % meta.get('zoom'))
      zoom = None
    else:
      if zoom < 8 or zoom > 18:
        errors.append('zoom %d outside the engine range 8..18' % zoom)

  # levels = how many tones the map tiles collapse to. A plan can pick its own
  # ("levels: 6" for a coastline-heavy trip, "levels: 0" to keep all 16); the
  # engine's `d` key cycles 4 -> 6 -> full live, so this is only a starting
  # point. Out of range is an error rather than a silent clamp: "levels: 1"
  # would draw a pure black-or-white map with no dither at all.
  levels = meta.get('levels')
  if levels is not None:
    try:
      levels = int(levels)
    except ValueError:
      errors.append('levels must be an integer 0 or 2..16, got "%s"'
                    % meta.get('levels'))
      levels = None
    else:
      if levels != 0 and (levels < 2 or levels > 16):
        errors.append('levels %d must be 0 (full dither) or 2..16' % levels)
        levels = None

  # Raise, never draw a truncated map: a stop dropped for a missing field would
  # silently shift every numbered marker and every hop distance, which is much
  # harder to notice on screen than one line of text.
  if errors:
    raise PlanError('\n  '.join([''] + errors))

  trip = {
    'title': trip_title,
    'facts': facts,
    'provider': provider,
    'map_note': '', #note,
    'stops': tuple(out_stops),
    # Cache dir names every tile file: keep it short (tripmap clips to 12) and
    # stable, so a trip you have opened once never re-downloads.
    'tag': clip(sanitize(meta.get('tag') or name), 12),
  }
  if zoom is not None:
    trip['zoom'] = zoom
  if levels is not None:
    trip['levels'] = levels
  if truthy(meta.get('invert')) is not None:
    trip['invert'] = truthy(meta.get('invert'))
  return trip, warns


_OK = {}
for _c in 'abcdefghijklmnopqrstuvwxyz0123456789_':
  _OK[_c] = _c


def sanitize(s):
  # MicroPython's str has no isalnum() here, so keep an explicit table.
  out = []
  for ch in s.lower():
    out.append(_OK.get(ch, '_'))
  return ''.join(out)


def truthy(v):
  if v is None:
    return None
  s = str(v).strip().lower()
  if s in ('true', 'yes', '1', 'on'):
    return True
  if s in ('false', 'no', '0', 'off'):
    return False
  return None


# ---- file / command line ---------------------------------------------------

def find(name):
  """A trip name -> the first matching .md file across TRIP_DIRS, or None."""
  for d in TRIP_DIRS:
    p = '%s/%s.md' % (d, name)
    if isfile(p):
      return p
  return None


def resolve(arg):
  """A trip name or a path -> an existing .md file name."""
  if arg.endswith('.md') or '/' in arg:
    p = arg if arg.startswith('/') else os.getcwd() + '/' + arg
    if not isfile(p):
      # 'malibu.md' typed from anywhere still finds the trips folder, then the
      # sample folder shipped with the app.
      base = p.split('/')[-1]
      found = find(base[:-3] if base.endswith('.md') else base)
      if found:
        return found
      raise PlanError('no such file: %s' % arg)
    return p
  p = find(arg)
  if p:
    return p
  raise PlanError('no trip %s - not found in %s (try --list)' %
                  (arg, ', '.join(TRIP_DIRS)))


def name_of(path):
  b = path.split('/')[-1]
  if b.endswith('.md'):
    b = b[:-3]
  return b


def load(path):
  f = open(path, 'r')
  try:
    text = f.read()
  finally:
    f.close()
  return parse(text, name_of(path))


def list_trips():
  # Same precedence as resolve(): a user plan shadows a shipped one of the
  # same name, so the list never shows the same trip twice.
  out = []
  for d in TRIP_DIRS:
    try:
      names = os.listdir(d)
    except OSError:
      continue
    for n in sorted(names):
      if n.endswith('.md') and n[:-3] not in out:
        out.append(n[:-3])
  return out


def show_trip(vs, trip):
  print('TRIP = {', file=vs)
  print("  'title': %r," % trip['title'], file=vs)
  print("  'facts': %r," % (trip['facts'],), file=vs)
  print("  'provider': %r, 'tag': %r," % (trip['provider'], trip['tag']), file=vs)
  print("  'zoom': %r, 'levels': %r, 'map_note': %r," %
        (trip.get('zoom'), trip.get('levels'), trip['map_note']),
        file=vs)
  print("  'stops': (", file=vs)
  for s in trip['stops']:
    print('    %r,' % (s,), file=vs)
  print('  ),', file=vs)
  print('}', file=vs)


def main(vs, args_in):
  parser = argparse.ArgumentParser(
    description='Browse a Markdown trip plan over a real OpenStreetMap basemap.',vs=vs)
  parser.add_argument('trip', nargs='?', default=None,
                      help='trip name in %s, or a path to a .md file' % TRIP_DIR)
  parser.add_argument('-z', '--zoom', type=int, default=None,
                      help='fixed map zoom, pinned for the whole session '
                           '(default: auto-fit each stop)')
  parser.add_argument('-p', '--provider', default='topo',
                      help='tile style: osm or topo (overrides the plan)')
  parser.add_argument('-l', '--levels', type=int, default=None,
                      help='tile tone count (plan default 4; 0 = full 16)')
  parser.add_argument('--list', action='store_true',
                      help='list the plans in %s' % TRIP_DIR)
  parser.add_argument('--check', action='store_true',
                      help='validate the plan and exit without drawing')
  parser.add_argument('--dump', action='store_true',
                      help='print the TRIP dict the engine receives')
  opts = parser.parse_args(args_in[1:])

  if opts.list:
    ts = list_trips()
    if not ts:
      print('no plans in %s' % ', '.join(TRIP_DIRS), file=vs)
    for t in ts:
      print(t, file=vs)
    return
  if not opts.trip:
    print('usage: tripplan [name|path.md] [-z N] [-p osm|topo] [-l N] '
          '[--list] [--check] [--dump]', file=vs)
    return
  try:
    path = resolve(opts.trip)
    trip, warns = load(path)
  except PlanError as e:
    print('tripplan: %s' % e, file=vs)
    return
  if warns:
    for w in warns:
      print('warn: %s' % w, file=vs)
  if opts.dump:
    show_trip(vs, trip)
    return
  if opts.check:
    print('OK  %s  %d stops  tag=%s  provider=%s' %
          (path, len(trip['stops']), trip['tag'], trip['provider']), file=vs)
    return

  # The engine takes the dict directly, so trip_<name>.py is no longer needed.
  # Drop the cached copy first: a shell that ran tripmap before it was edited
  # keeps the OLD module, and MicroPython's import cache would then hand this
  # call a stale TripMap whose line numbers no longer match the file on disk
  # (the 'function takes 5 positional arguments' crash). Same idiom as
  # tripmap.load_trip() uses for trip_<name>.py. --check/--dump never touch the
  # engine, so only the GUI path needs this.
  import sys
  import esclib as elib
  if 'tripmap' in sys.modules:
    del sys.modules['tripmap']
  import tripmap
  v = vs.v
  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  try:
    app = tripmap.TripMap(vs, trip, opts.zoom, opts.provider, opts.levels)
    # Display task draws and reads keys; this app thread loads everything.
    v.callback(app.update)
    try:
      app.loader_loop()
    finally:
      v.callback(None)
  finally:
    v.print(el.display_mode(True))
