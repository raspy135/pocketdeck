# dl - chunked HTTP download over a raw socket (http:// only).
# Use when curl fails on very large pages: it downloads in Range chunks,
# each in its own connection, so one bad chunk only loses that chunk.
# Usage: dl http://host/path out_file [total_bytes] [chunk_bytes]
# Without total_bytes it probes it with a 1-byte Range request (Content-Range).

import socket

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/120.0"
DEFAULT_CHUNK = 150000

def parse_url(url):
  rest = url[7:] if url.startswith('http://') else url
  host, _, path = rest.partition('/')
  port = 80
  if ':' in host:
    host, _, p = host.partition(':')
    port = int(p)
  return host, port, '/' + path

def recv_body(sock, head_buf):
  p = head_buf.find(b'\r\n\r\n')
  if p < 0:
    raise RuntimeError('no headers')
  head = head_buf[:p].decode()
  body = head_buf[p + 4:]
  cl = None
  crange_total = None
  chunked = False
  for line in head.split('\r\n'):
    k, _, v = line.partition(':')
    k = k.strip().lower()
    v = v.strip()
    if k == 'content-length':
      cl = int(v)
    elif k == 'content-range':
      crange_total = int(v.rpartition('/')[2])
    elif k == 'transfer-encoding' and 'chunked' in v.lower():
      chunked = True
  if chunked:
    out = b''
    while True:
      nl = body.find(b'\r\n')
      while nl < 0:
        d = sock.recv(4096)
        if not d:
          break
        body += d
        nl = body.find(b'\r\n')
      if nl < 0:
        raise RuntimeError('bad chunked stream')
      size = int(body[:nl].split(b';')[0].strip(), 16)
      if size == 0:
        break
      need = nl + 2 + size + 2
      while len(body) < need:
        d = sock.recv(4096)
        if not d:
          break
        body += d
      out += body[nl + 2:nl + 2 + size]
      body = body[nl + 2 + size + 2:]
    return out, crange_total
  if cl is not None:
    while len(body) < cl:
      d = sock.recv(4096)
      if not d:
        break
      body += d
    return body[:cl], crange_total
  while True:
    try:
      d = sock.recv(4096)
    except OSError:
      break
    if not d:
      break
    body += d
  return body, crange_total

def http_range(host, port, path, start, end):
  sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
  sock.settimeout(90)
  sock.connect((host, port))
  try:
    if start is None:
      rng = ''
    else:
      rng = 'Range: bytes=%d-%d\r\n' % (start, end)
    req = ('GET %s HTTP/1.1\r\nHost: %s\r\nUser-Agent: %s\r\n'
           'Connection: close\r\nAccept: */*\r\n%s\r\n' % (path, host, UA, rng))
    sock.send(req)
    buf = b''
    while buf.find(b'\r\n\r\n') < 0 or len(buf) < 12:
      d = sock.recv(2048)
      if not d:
        break
      buf += d
    body, total = recv_body(sock, buf)
    return body, total
  finally:
    sock.close()

def main(vs, args):
  if len(args) < 3:
    print('usage: dl http://host/path out_file [total_bytes] [chunk_bytes]', file=vs)
    return
  host, port, path = parse_url(args[1])
  out_path = args[2]
  chunk = int(args[4]) if len(args) > 4 else DEFAULT_CHUNK
  if len(args) > 3:
    total = int(args[3])
  else:
    probe, total = http_range(host, port, path, 0, 0)
    if not total:
      print('server has no Content-Range; pass total_bytes explicitly', file=vs)
      return
  print('total size:', total, file=vs)
  f = open(out_path, 'wb')
  start = 0
  while start < total:
    end = min(start + chunk - 1, total - 1)
    data, _ = http_range(host, port, path, start, end)
    if not data:
      print('EMPTY chunk %d-%d, stopping' % (start, end), file=vs)
      break
    f.write(data)
    start += len(data)
    print('chunk ok up to %d / %d' % (start, total), file=vs)
  f.close()
  print('DONE wrote', out_path, start, 'bytes', file=vs)
