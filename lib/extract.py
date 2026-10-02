# extract - pull readable plain text out of an HTML or RSS file.
# Strips tags/CDATA/entities, dedupes near-identical blocks.
# Usage: extract file [max_chars_per_block]

def unescape(s):
  for a, b in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
               ('&quot;', '"'), ('&#39;', "'"), ('&nbsp;', ' ')]:
    s = s.replace(a, b)
  return s

def find_blocks(data, open_tags, close_tags):
  out = []
  for ot in open_tags:
    i = 0
    while True:
      a = data.find(ot, i)
      if a < 0:
        break
      b = -1
      for ct in close_tags:
        j = data.find(ct, a + len(ot))
        if j >= 0 and (b < 0 or j < b):
          b = j
      if b < 0:
        break
      out.append(data[a + len(ot):b])
      i = b + 1
  return out

def re_sub_tags(text):
  # Linear, single pass: split on '<' (C-level), drop up to the next '>'.
  # Avoids the old out += ... loop, which was O(n^2) in MicroPython.
  segs = text.split('<')
  # Text before the first '<' holds no tag, so a lone '>' there (e.g. from a
  # '&gt;' entity) must be kept, not mistaken for a tag close.
  parts = [segs[0]]
  for seg in segs[1:]:
    i = seg.find('>')
    if i >= 0:
      seg = seg[i + 1:]
    if seg:
      parts.append(seg)
  return ' '.join(parts)

def clean(text, limit):
  # Unescape first, exactly like the original, so entities (e.g. &nbsp;)
  # are resolved before whitespace is collapsed. Only the final collapse
  # is done on the truncated slice instead of the whole block.
  text = unescape(text)
  text = text.replace('<![CDATA[', ' ').replace(']]>', ' ')
  text = re_sub_tags(text)
  return ' '.join(text[:limit].split())

def main(vs, args):
  if len(args) < 2:
    print('usage: extract file [max_chars_per_block]', file=vs)
    return
  path = args[1]
  limit = int(args[2]) if len(args) > 2 else 7000
  try:
    f = open(path, 'r')
  except OSError:
    print('cannot open', path, file=vs)
    return
  data = f.read()
  f.close()
  if '<item' in data or '<entry' in data or 'rss' in data[:300]:
    blocks = find_blocks(data, ['<content:encoded', '<description'],
                         ['</content:encoded>', '</description>'])
  else:
    blocks = [data]
  seen = set()
  n = 0
  for b in blocks:
    text = clean(b, limit)
    key = text[:80]
    if not text or key in seen:
      continue
    seen.add(key)
    n += 1
    vs.write(text)
    vs.write('\n' + '=' * 60 + '\n')
  print('blocks written:', n, file=vs)
