# tripgeo.py - geocode the places in a trip plan, with validation.
#
#   tripgeo "Zuma Beach, Malibu" "El Matador State Beach" "Leo Carrillo"
#   tripgeo -b 33.98,34.12,-118.99,-118.20 "Zuma Beach" ...
#   tripgeo -f /sd/work/places.txt          <- one query per line
#
# The tripplan skill runs this before it writes a plan, because the markdown
# has to carry a decimal lat/lon per stop (the viewer never geocodes, so it can
# work offline). A bare name is not proof of a place: Nominatim will happily
# return a Zuma in Montana. So every row is checked two ways and prints a
# verdict you can read at a glance:
#
#   ok    name overlaps the query AND the fix falls inside -b
#   far   inside the bbox but the name does not look like the query
#   OUT   name matches but the fix is outside the bbox  <- wrong town
#   FAIL  no answer, or both checks failed
#
# Nominatim's usage policy: one request per second, a real User-Agent, and no
# bulk geocoding. RATE enforces the gap; a trip is ~13 queries, which is fine.
# Results are cached in /sd/work/tripgeo.json, so re-running a plan costs
# nothing and a typo fix only asks for the one new place.

import os
import json
import time
import argparse
import curl as http

UA = 'PocketDeckTripplan/0.1 (personal handheld trip viewer)'
GEO = 'https://nominatim.openstreetmap.org/search?q=%s&format=json&limit=3'
CACHE = '/sd/work/tripgeo.json'
RATE = 1.15                 # seconds between live requests (policy: <= 1/sec)
STOPWORDS = ('the', 'beach', 'state', 'park', 'cafe', 'bar', 'and', 'of')


def encode(s):
  out = []
  for ch in s:
    o = ord(ch)
    if (48 <= o <= 57) or (65 <= o <= 90) or (97 <= o <= 122) or ch in '._~-':
      out.append(ch)
    elif ch == ' ':
      out.append('+')
    elif o < 128:
      out.append('%%%02X' % o)
    else:
      # utf-8, 2 or 3 bytes for the accents a place name can carry
      for b in ch.encode('utf-8'):
        out.append('%%%02X' % b)
  return ''.join(out)


def words(s):
  out = []
  for w in s.lower().replace(',', ' ').replace('.', ' ').split(' '):
    if w and w not in STOPWORDS:
      out.append(w)
  return out


def name_match(q, got_name, display):
  """How many of the query's words show up in the answer's name/address."""
  qw = words(q)
  if not qw:
    return 0.0
  hay = ' '.join(words(got_name)) + ' ' + ' '.join(words(display))
  hit = 0
  for w in qw:
    if w in hay:
      hit += 1
  return hit / float(len(qw))


def in_box(lat, lon, box):
  if box is None:
    return True
  la_s, la_n, lo_w, lo_e = box
  return la_s <= lat <= la_n and lo_w <= lon <= lo_e


def load_cache():
  try:
    f = open(CACHE, 'r')
    try:
      return json.loads(f.read())
    finally:
      f.close()
  except Exception:
    return {}


def save_cache(c):
  try:
    os.mkdir('/sd/work')
  except OSError:
    pass
  with open(CACHE, 'w') as f:
    f.write(json.dumps(c))


def ask(q):
  status, hdr, body = http.request(GEO % encode(q), user_agent=UA, timeout=25)
  if status.find('200') < 0:
    raise Exception('http %s' % status)
  return json.loads(body)


def main(vs, args_in):
  p = argparse.ArgumentParser(description='Geocode trip places with validation')
  p.add_argument('query', nargs='*', help='place name(s), most specific last')
  p.add_argument('-f', '--file', default=None, help='read one query per line')
  p.add_argument('-b', '--bbox', default=None,
                 help='sanity box: south,north,west,east (decimal degrees)')
  p.add_argument('-n', '--ncache', action='store_true', help='ignore the cache')
  p.add_argument('-v', '--verbose', action='store_true',
                 help='also print the display name of the best hit')
  opts = p.parse_args(args_in[1:])

  qs = list(opts.query)
  if opts.file:
    f = open(opts.file, 'r')
    try:
      for line in f.read().split('\n'):
        if line.strip() and not line.startswith('#'):
          qs.append(line.strip())
    finally:
      f.close()
  if not qs:
    print('usage: tripgeo [-b s,n,w,e] [-v] "place" ["place"...]  (or -f file)',
          file=vs)
    return
  box = None
  if opts.bbox:
    try:
      v = [float(x) for x in opts.bbox.split(',')]
    except ValueError:
      print('tripgeo: -b needs 4 decimal numbers, got "%s"' % opts.bbox, file=vs)
      return
    if len(v) != 4:
      print('tripgeo: -b needs south,north,west,east', file=vs)
      return
    box = (min(v[0], v[1]), max(v[0], v[1]), min(v[2], v[3]), max(v[2], v[3]))

  cache = {} if opts.ncache else load_cache()
  hits = 0
  for q in qs:
    try:
      rows = cache.get(q)
      if rows is None:
        time.sleep(RATE)
        rows = ask(q)
        cache[q] = rows
        hits += 0
      else:
        hits += 1
    except Exception as e:
      print('%-40s FAIL  %r' % (q[:40], e), file=vs)
      continue
    if not rows:
      print('%-40s FAIL  no answer' % q[:40], file=vs)
      continue
    best = None
    for r in rows:
      try:
        lat = float(r['lat'])
        lon = float(r['lon'])
      except (KeyError, ValueError):
        continue
      nm = r.get('name', '') or ''
      disp = r.get('display_name', '') or ''
      m = name_match(q, nm, disp)
      inbox = in_box(lat, lon, box)
      score = m + (0.5 if inbox else 0.0)
      if best is None or score > best[0]:
        best = (score, lat, lon, nm, disp, m, inbox,
                r.get('type', ''), r.get('addresstype', ''))
      # the first answer is usually the intended one; stop early when it
      # satisfies both checks so a 3-row reply cannot pick a weaker match
      if m >= 1.0 and inbox:
        break
    if best is None:
      print('%-40s FAIL  no usable lat/lon' % q[:40], file=vs)
      continue
    (score, lat, lon, nm, disp, m, inbox, typ, atyp) = best
    if m >= 0.5 and inbox:
      verdict = 'ok  '
    elif inbox:
      verdict = 'far '
    elif m >= 0.5:
      verdict = 'OUT '
    else:
      verdict = 'FAIL'
    print('%s %-38s %9.4f %10.4f  %-18s %s' %
          (verdict, q[:38], lat, lon, clip(nm or typ, 18),
           ('match %.0f%%' % (100 * m))), file=vs)
    if opts.verbose:
      print('       %s' % clip(disp, 150), file=vs)
    if verdict != 'ok  ':
      print('       -> do NOT write these coords; refine the query (add the '
            'city/county) or ask the user', file=vs)
  if not opts.ncache:
    save_cache(cache)
    if hits:
      print('(%d from cache, %d fetched)' % (hits, len(qs) - hits), file=vs)


def clip(s, n):
  return s[:n]
