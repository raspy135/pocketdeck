# extract - pull readable plain text out of an HTML or RSS file.
# Strips tags/CDATA/entities, dedupes near-identical blocks.
# Usage: extract file [max_chars_per_block] [-m min_chars] [-a]
#
# HTML pages are handled in a single pass: <head>, <script>, <style>, <svg>,
# <form> etc. are dropped as whole sections, then elements whose opening tag
# mentions a boilerplate marker (cookie banner, share bar...) are dropped, and
# the rest is split on block-level tags so only prose paragraphs are kept.
# -m sets the minimum paragraph length (default 40), -a keeps every block.
#
# Performance notes (this runs on an ESP32-class MCU):
#  * Everything is scanned as bytes, not str. On this firmware
#    str.find(sub, start) gets slower the larger `start` is (the tail is
#    re-scanned), so a find-loop over a document is O(n^2); bytes.find() is
#    linear, and bytes ops are ~3x cheaper. One data.split(b'<') therefore
#    replaces all the repeated find() scans.
#  * No regular expressions anywhere.

BLOCK_TAGS = (
  'p', 'br', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'td', 'tr', 'blockquote', 'figcaption', 'section', 'article',
  'header', 'footer', 'ul', 'ol', 'table', 'hr', 'dt', 'dd',
  'pre', 'main', 'aside', 'nav', 'dl', 'caption',
)

DROP_TAGS = (
  'head', 'script', 'style', 'noscript', 'svg', 'template',
  'iframe', 'form', 'button', 'select', 'nav',
)

MARKER_TAGS = ('div', 'section', 'aside', 'footer', 'nav', 'ul')

SKIP_MARKERS = (b'cmplz', b'cookie', b'consent-banner', b'grecaptcha',
                b'newsletter-signup', b'sharedaddy', b'jp-relatedposts',
                b'screen-reader-text', b'breadcrumb', b'wp-block-buttons')

RSS_TAGS = (b'content:encoded', b'description')

# Tag names are looked for in the first NAME_LIM bytes of each piece.
NAME_LIM = 24

BLOCK_SET = frozenset(t.encode() for t in BLOCK_TAGS)
DROP_SET = frozenset(t.encode() for t in DROP_TAGS)
MARKER_SET = frozenset(t.encode() for t in MARKER_TAGS)

ENTITIES = (('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
            ('&quot;', '"'), ('&#39;', "'"), ('&apos;', "'"),
            ('&#039;', "'"), ('&nbsp;', ' '), ('&hellip;', '...'),
            ('&mdash;', '-'), ('&ndash;', '-'), ('&rsquo;', "'"),
            ('&lsquo;', "'"), ('&ldquo;', '"'), ('&rdquo;', '"'),
            ('&copy;', '(c)'), ('&trade;', '(tm)'), ('&deg;', ' deg'))


def unescape(s):
  if '&' not in s:
    return s
  for a, b in ENTITIES:
    if a in s:
      s = s.replace(a, b)
  return s


def unescape_numeric(s):
  # &#8217; / &#x2019; style references, handled without a regex engine.
  if '&#' not in s:
    return s
  out = []
  i = 0
  n = len(s)
  while True:
    a = s.find('&#', i)
    if a < 0:
      out.append(s[i:])
      break
    e = s.find(';', a)
    if e < 0 or e - a > 9:
      out.append(s[i:a + 2])
      i = a + 2
      continue
    body = s[a + 2:e]
    try:
      code = int(body[1:], 16) if body[:1] in ('x', 'X') else int(body)
    except ValueError:
      code = 0
    if 31 < code < 0x3000:
      out.append(s[i:a])
      out.append(chr(code))
      i = e + 1
    else:
      out.append(s[i:a + 2])
      i = a + 2
  return ''.join(out)


def re_sub_tags(text):
  # Safety net: no '<' should be left in a block, but be robust.
  if '<' not in text:
    return text
  segs = text.split('<')
  parts = [segs[0]]
  for seg in segs[1:]:
    i = seg.find('>')
    if i >= 0:
      seg = seg[i + 1:]
    if seg:
      parts.append(seg)
  return ' '.join(parts)


def clean(block, limit):
  # block is bytes; decode once, then unescape.
  try:
    text = block.decode('utf-8', 'replace')
  except TypeError:
    text = block.decode()
  text = unescape(text)
  text = unescape_numeric(text)
  if '<![CDATA[' in text or ']]>' in text:
    text = text.replace('<![CDATA[', ' ').replace(']]>', ' ')
  text = re_sub_tags(text)
  text = ' '.join(text.split())
  return text[:limit]


def html_blocks(data):
  # Single pass over data.split(b'<'): drop whole sections, drop boilerplate
  # elements, split the remaining text on block-level tags.
  parts = data.split(b'<')
  blocks = []
  buf = []
  if parts[0]:
    buf.append(parts[0])
  skip = None        # tag name being dropped wholesale
  depth = 0
  mskip = None       # tag name dropped because of a boilerplate marker
  mdepth = 0
  for k in range(1, len(parts)):
    seg = parts[k]
    e = seg.find(b'>')
    if e < 0:
      # A '<' inside an attribute value ("media=(width < 40rem)") splits a
      # tag in two; the piece before the real '>' is tag junk, so drop it.
      # Only at the very end of the document can this be real text.
      if k == len(parts) - 1 and seg:
        buf.append(b'<' + seg)
      continue
    text = seg[e + 1:]
    if e < NAME_LIM:
      h = seg[:e]
    else:
      h = seg[:NAME_LIM]
    if h[:1] == b'/':
      closing = True
      h = h[1:]
    else:
      closing = False
    name = h.split(None, 1)[0].lower()
    if name[-1:] == b'/':
      name = name[:-1]
    if skip is not None:
      if name == skip:
        if closing:
          depth -= 1
          if depth <= 0:
            skip = None
        else:
          depth += 1
      continue
    if mskip is not None:
      if name == mskip:
        if closing:
          mdepth -= 1
          if mdepth <= 0:
            mskip = None
        else:
          mdepth += 1
      continue
    if name:
      if not closing:
        if name in DROP_SET:
          skip = name
          depth = 1
          continue
        if name in MARKER_SET:
          tag = seg[:e].lower()
          hit = False
          for m in SKIP_MARKERS:
            if m in tag:
              hit = True
              break
          if hit:
            mskip = name
            mdepth = 1
            continue
      if name in BLOCK_SET:
        if buf:
          blocks.append(b''.join(buf))
          buf = []
    if text:
      buf.append(text)
  if buf:
    blocks.append(b''.join(buf))
  return blocks


def rss_blocks(data):
  # RSS/Atom: the bodies of <content:encoded> / <description> elements.
  out = []
  buf = None
  for seg in data.split(b'<')[1:]:
    e = seg.find(b'>')
    if e < 0:
      if buf is not None:
        buf.append(b'<' + seg)
      continue
    if e < NAME_LIM:
      h = seg[:e]
    else:
      h = seg[:NAME_LIM]
    if h[:1] == b'/':
      closing = True
      h = h[1:]
    else:
      closing = False
    name = h.split(None, 1)[0].lower()
    if name[-1:] == b'/':
      name = name[:-1]
    if name in RSS_TAGS:
      if closing:
        if buf is not None:
          out.append(b''.join(buf))
          buf = None
      elif buf is None:
        buf = []
        text = seg[e + 1:]
        if text:
          buf.append(text)
      continue
    if buf is not None:
      text = seg[e + 1:]
      if text:
        buf.append(text)
  if buf is not None:
    out.append(b''.join(buf))
  return out


def is_rss(data):
  return b'<item' in data or b'<entry' in data or b'rss' in data[:300]


def main(vs, args):
  if len(args) < 2:
    print('usage: extract file [max_chars_per_block] [-m min_chars] [-a]',
          file=vs)
    return
  path = None
  limit = 7000
  minlen = 40
  for a in args[1:]:
    if a == '-a':
      minlen = 0
    elif a == '-m':
      pass
    elif a.startswith('-m') and len(a) > 2:
      minlen = int(a[2:])
    elif a.isdigit():
      limit = int(a)
    else:
      path = a
  if path is None:
    print('usage: extract file [max_chars_per_block] [-m min_chars] [-a]',
          file=vs)
    return
  try:
    f = open(path, 'rb')
  except OSError:
    print('cannot open', path, file=vs)
    return
  data = f.read()
  f.close()
  rss = is_rss(data)
  if rss:
    blocks = rss_blocks(data)
  else:
    blocks = html_blocks(data)
  del data
  seen = set()
  n = 0
  for b in blocks:
    text = clean(b, limit)
    # An RSS item body is one self-contained block, so a short headline or
    # summary (e.g. Japanese, 30-40 chars) is still wanted there.
    if len(text) < minlen and not (rss and minlen <= 40 and text):
      continue
    key = text[:80]
    if key in seen:
      continue
    seen.add(key)
    n += 1
    vs.write(text)
    vs.write('\n')
  print('blocks written:', n, file=vs)
