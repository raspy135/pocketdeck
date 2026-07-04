import sys
import argparse
import socket
import ssl
try:
  import ubinascii
except ImportError:
  import binascii as ubinascii

_VERSION = "Pocket Deck curl 0.2"

def print_vs(vs, s=""):
  try:
    vs.write(str(s) + "\n")
  except Exception:
    print(s)

def _split_url(url):
  scheme = "http"
  rest = url

  p = url.find("://")
  if p >= 0:
    scheme = url[:p].lower()
    rest = url[p + 3:]

  slash = rest.find("/")
  if slash >= 0:
    hostport = rest[:slash]
    path = rest[slash:]
  else:
    hostport = rest
    path = "/"

  if not hostport:
    raise ValueError("URL has no host")

  host = hostport
  port = 443 if scheme == "https" else 80

  # Basic IPv6 bracket form is not supported in this tiny clone.
  colon = hostport.rfind(":")
  if colon > 0:
    port_s = hostport[colon + 1:]
    if port_s:
      try:
        port = int(port_s)
        host = hostport[:colon]
      except Exception:
        host = hostport

  if scheme != "http" and scheme != "https":
    raise ValueError("Unsupported scheme: " + scheme)

  return scheme, host, port, path

def _parse_header_line(line):
  p = line.find(":")
  if p <= 0:
    raise ValueError("Bad header, expected 'Name: value': " + line)
  name = line[:p].strip()
  value = line[p + 1:].strip()
  if not name:
    raise ValueError("Empty header name")
  return name, value

def _sock_write(sock, data):
  # MicroPython sockets have write(); CPython/emulator sockets use sendall().
  try:
    sock.write(data)
  except AttributeError:
    sock.sendall(data)

def _read_chunk(sock, n):
  out = bytearray(n)
  view = memoryview(out)
  read = 0
  while read < n:
    try:
      r = sock.readinto(view[read:])
    except AttributeError:
      r = None
    if r is None:
      try:
        chunk = sock.read(n - read)
      except AttributeError:
        chunk = sock.recv(n - read)
      if not chunk:
        break
      out[read:read + len(chunk)] = chunk
      read += len(chunk)
    else:
      if r == 0:
        break
      read += r
  return bytes(out[:read])

def _read_until_headers(sock):
  buf = bytearray()
  while True:
    try:
      chunk = sock.read(256)
    except AttributeError:
      chunk = sock.recv(256)
    if not chunk:
      break
    buf += chunk
    hpos, hlen = _find_header_end(bytes(buf))
    if hpos >= 0:
      return bytes(buf[:hpos]), bytes(buf[hpos + hlen:])
  return bytes(buf), b""

def _read_all(sock, chunk_size=1024, max_bytes=200000):
  parts = []
  total = 0
  while total < max_bytes:
    try:
      b = sock.read(min(chunk_size, max_bytes - total))
    except AttributeError:
      b = sock.recv(min(chunk_size, max_bytes - total))
    if not b:
      break
    parts.append(bytes(b))
    total += len(b)
  return b"".join(parts)

def _find_header_end(data):
  p = data.find(b"\r\n\r\n")
  if p >= 0:
    return p, 4
  p = data.find(b"\n\n")
  if p >= 0:
    return p, 2
  return -1, 0

def _decode_chunked(body):
  pos = 0
  out = b""

  while True:
    line_end = body.find(b"\r\n", pos)
    sep_len = 2
    if line_end < 0:
      line_end = body.find(b"\n", pos)
      sep_len = 1
    if line_end < 0:
      break

    line = body[pos:line_end]
    semi = line.find(b";")
    if semi >= 0:
      line = line[:semi]

    try:
      size = int(line.strip(), 16)
    except Exception:
      break

    pos = line_end + sep_len
    if size == 0:
      break

    out += body[pos:pos + size]
    pos += size

    if body[pos:pos + 2] == b"\r\n":
      pos += 2
    elif body[pos:pos + 1] == b"\n":
      pos += 1

  return out

def _headers_to_dict(header_text):
  lines = header_text.split("\n")
  status = lines[0].strip() if lines else ""
  headers = {}

  for line in lines[1:]:
    line = line.strip()
    if not line:
      continue
    p = line.find(":")
    if p > 0:
      k = line[:p].strip().lower()
      v = line[p + 1:].strip()
      headers[k] = v

  return status, headers

def _arg_get(args, names, default=None):
  # Depending on option spelling, values are stored under the option name.
  # This helper keeps the call site robust for short/long option names.
  for name in names:
    try:
      return getattr(args, name)
    except Exception:
      pass

  try:
    d = args.__dict__
    for name in names:
      if name in d:
        return d[name]
  except Exception:
    pass

  return default

def _status_code(status):
  # "HTTP/1.1 301 Moved Permanently" -> 301 (0 if unparsable)
  try:
    return int(status.split(" ")[1])
  except Exception:
    return 0

def _resolve_location(base_url, loc):
  # Resolve a redirect Location against the URL that produced it.
  if loc.startswith("http://") or loc.startswith("https://"):
    return loc
  scheme, host, port, path = _split_url(base_url)
  default_port = 443 if scheme == "https" else 80
  origin = scheme + "://" + host
  if port != default_port:
    origin += ":" + str(port)
  if loc.startswith("/"):
    return origin + loc
  # Relative: resolve against the current path's directory.
  slash = path.rfind("/")
  base_dir = path[:slash + 1] if slash >= 0 else "/"
  return origin + base_dir + loc

def _remote_filename(url):
  # Filename for -O: last path segment, query stripped; index.html fallback.
  try:
    _, _, _, path = _split_url(url)
  except Exception:
    path = "/"
  q = path.find("?")
  if q >= 0:
    path = path[:q]
  name = path.split("/")[-1]
  return name if name else "index.html"

def request(url, method="GET", data=None, header_lines=None,
            user_agent="pdeck-curl/0.2", timeout=None, head=False,
            follow=0, auth=None):
  # follow > 0 enables redirect following (that many hops). auth is a
  # "user:password" string for HTTP basic auth.
  method = method.upper()
  if head:
    method = "HEAD"
  if data is None:
    data_b = b""
  elif isinstance(data, bytes):
    data_b = data
  else:
    data_b = str(data).encode("utf-8")

  while True:
    status, resp_headers, body = _request_once(
      url, method, data_b, header_lines, user_agent, timeout, head, auth)
    code = _status_code(status)
    if follow > 0 and code in (301, 302, 303, 307, 308):
      loc = resp_headers.get("location")
      if loc:
        url = _resolve_location(url, loc)
        follow -= 1
        # Classic curl behavior: 301/302/303 turn the next request into a
        # bodyless GET; 307/308 preserve method and body.
        if code in (301, 302, 303) and method != "HEAD":
          method = "GET"
          data_b = b""
        continue
    return status, resp_headers, body

def _request_once(url, method, data_b, header_lines, user_agent,
                  timeout, head, auth):
  scheme, host, port, path = _split_url(url)

  headers = {}
  headers["Host"] = host
  headers["User-Agent"] = user_agent
  headers["Connection"] = "close"
  headers["Accept"] = "*/*"

  if auth:
    b64 = ubinascii.b2a_base64(auth.encode("utf-8")).decode().strip()
    headers["Authorization"] = "Basic " + b64

  if header_lines:
    for h in header_lines:
      name, value = _parse_header_line(h)
      headers[name] = value

  if method == "POST" or len(data_b) > 0:
    headers["Content-Length"] = str(len(data_b))
    has_ct = False
    for k in headers:
      if k.lower() == "content-type":
        has_ct = True
        break
    if not has_ct:
      headers["Content-Type"] = "application/x-www-form-urlencoded"

  req = method + " " + path + " HTTP/1.1\r\n"
  for k in headers:
    req += k + ": " + headers[k] + "\r\n"
  req += "\r\n"

  addr = socket.getaddrinfo(host, port)[0][-1]
  s = socket.socket()
  if timeout:
    try:
      s.settimeout(timeout)
    except AttributeError:
      pass  # emulator stub sockets may lack settimeout
  try:
    s.connect(addr)
    if scheme == "https":
      try:
        s = ssl.wrap_socket(s, server_hostname=host)
      except TypeError:
        s = ssl.wrap_socket(s)

    _sock_write(s, req.encode("utf-8"))
    if len(data_b) > 0:
      _sock_write(s, data_b)

    header_b, leftover = _read_until_headers(s)

    try:
      header_text = header_b.decode("utf-8")
    except Exception:
      header_text = header_b.decode()

    status, resp_headers = _headers_to_dict(header_text)

    te = resp_headers.get("transfer-encoding", "")
    cl = resp_headers.get("content-length", None)

    if head:
      # HEAD: servers send no body (Content-Length may still be present).
      body = b""
    elif te.lower().find("chunked") >= 0:
      raw_body = leftover + _read_all(s)
      body = _decode_chunked(raw_body)
    elif cl is not None:
      remaining = int(cl) - len(leftover)
      body = leftover
      while remaining > 0:
        chunk = _read_chunk(s, min(4096, remaining))
        if not chunk:
          break
        body += chunk
        remaining -= len(chunk)
        if len(body) >= 200000:
          break
    else:
      body = leftover + _read_all(s)

  finally:
    try:
      s.close()
    except Exception:
      pass

  return status, resp_headers, body

def build_parser():
  parser = argparse.ArgumentParser(
    description="Tiny curl clone for Pocket Deck"
  )
  #parser.add_argument("url", nargs="?", help="URL to request, http:// or https://")
  parser.add_argument("-o", "--output",
                      default=None, help="Write body to file")
  parser.add_argument("-X", "--request",
                      default="GET", help="HTTP method, e.g. GET or POST")
  parser.add_argument("-H", "--header",
                      default=None,
                      nargs='*',
                      help="Custom header, e.g. -H 'Accept: application/json'")
  parser.add_argument("-d", "--data",
                      default=None, help="Request body data, or @file to read the body from a file")
  parser.add_argument("-i", "--include", action="store_true",
                      help="Include response status and headers in output")
  parser.add_argument("-L", "--location", action="store_true",
                      help="Follow redirects (up to 5)")
  parser.add_argument("-I", "--head", action="store_true",
                      help="HEAD request: show status and headers only")
  parser.add_argument("-m", "--max-time", type=int, default=None,
                      dest="max_time", metavar="SECONDS",
                      help="Timeout for the whole request in seconds")
  parser.add_argument("-A", "--user-agent", default="pdeck-curl/0.2",
                      dest="user_agent", help="User-Agent string to send")
  parser.add_argument("-u", "--user", default=None,
                      help="HTTP basic auth as user:password")
  parser.add_argument("-O", "--remote-name", action="store_true",
                      dest="remote_name",
                      help="Save body to a file named from the URL")
  parser.add_argument("-s", "--silent", action="store_true",
                      help="Silent mode, suppress progress/status messages")
  parser.add_argument("-t", "--truncate", type=int, default=None, metavar="N",
                      help="Truncate output to N bytes (default: no limit)")
  parser.add_argument("-V", "--version", action="store_true",
                      help="Show version")
  return parser

def _write_body_to_vs(vs, body, truncate=None):
  try:
    text = body.decode("utf-8")
  except Exception:
    text = repr(body)
  if truncate is not None and len(text) > truncate:
    vs.write(text[:truncate])
    print_vs(vs, "\n[... truncated, total body %d bytes]" % len(text))
  else:
    vs.write(text)
    if not text.endswith("\n"):
      vs.write("\n")

def main(vs, args_in):
  parser = build_parser()
  try:
    # The URL can appear anywhere: prefer the last token with a '://' scheme
    # (like real curl), falling back to a bare last argument. It is removed
    # before parsing so option values with spaces parse cleanly on the
    # device's mini argparse.
    url = None
    for i in range(len(args_in) - 1, 0, -1):
      if args_in[i].find("://") > 0:
        url = args_in[i]
        args_in = args_in[:i] + args_in[i + 1:]
        break
    if url is None and len(args_in) > 1 and not args_in[-1].startswith("-"):
      url = args_in[-1]
      args_in = args_in[:-1]
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return 2

  version = _arg_get(args, ("version", "V"), False)
  output = _arg_get(args, ("output", "o"), None)
  request_method = _arg_get(args, ("request", "X"), "GET")
  headers = _arg_get(args, ("header", "H"), [])
  data = _arg_get(args, ("data", "d"), None)
  include_headers = _arg_get(args, ("include", "i"), False)
  silent = _arg_get(args, ("silent", "s"), False)
  truncate = _arg_get(args, ("truncate", "t"), None)
  location = _arg_get(args, ("location", "L"), False)
  head = _arg_get(args, ("head", "I"), False)
  max_time = _arg_get(args, ("max_time", "m"), None)
  user_agent = _arg_get(args, ("user_agent", "A"), "pdeck-curl/0.2")
  user = _arg_get(args, ("user", "u"), None)
  remote_name = _arg_get(args, ("remote_name", "O"), False)

  if version:
    print_vs(vs, _VERSION)
    return 0

  if not url:
    print_vs(vs, "curl: URL required")
    print_vs(vs, "Try: curl https://example.com")
    return 2

  # -d @file: read the request body from a file.
  if data is not None and data.startswith("@"):
    try:
      with open(data[1:], "rb") as f:
        data = f.read()
    except Exception as e:
      print_vs(vs, "curl: cannot read data file: " + str(e))
      return 1

  method = request_method
  if data is not None and method == "GET":
    method = "POST"

  try:
    status, resp_headers, body = request(
      url,
      method=method,
      data=data,
      header_lines=headers,
      user_agent=user_agent,
      timeout=max_time,
      head=head,
      follow=5 if location else 0,
      auth=user
    )
  except Exception as e:
    print_vs(vs, "curl: error: " + str(e))
    return 1

  if head:
    # Like real curl -I: status and headers are the output.
    print_vs(vs, status)
    for k in resp_headers:
      print_vs(vs, k + ": " + resp_headers[k])
    return 0

  if remote_name and not output:
    output = _remote_filename(url)

  if output:
    try:
      with open(output, "wb") as f:
        f.write(body)
      if not silent:
        print_vs(vs, "Saved " + str(len(body)) + " bytes to " + output)
    except Exception as e:
      print_vs(vs, "curl: cannot write output: " + str(e))
      return 1
  else:
    if include_headers:
      print_vs(vs, status)
      for k in resp_headers:
        print_vs(vs, k + ": " + resp_headers[k])
      print_vs(vs, "")
    _write_body_to_vs(vs, body, truncate)

  if not silent and status:
    print_vs(vs, "")
    print_vs(vs, status)

  return 0
