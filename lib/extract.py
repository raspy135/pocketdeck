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

def clean(text):
  text = text.replace('<![CDATA[', ' ').replace(']]>', ' ')
  text = re_sub_tags(text)
  return ' '.join(text.split())

def re_sub_tags(text):
  out = ''
  i = 0
  while True:
    a = text.find('<', i)
    if a < 0:
      return out + text[i:]
    b = text.find('>', a)
    if b < 0:
      return out + text[i:]
    out += text[i:a] + ' '
    i = b + 1

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
    text = clean(unescape(b))
    key = text[:80]
    if not text or key in seen:
      continue
    seen.add(key)
    n += 1
    vs.write(text[:limit])
    vs.write('\n' + '=' * 60 + '\n')
  print('blocks written:', n, file=vs)
