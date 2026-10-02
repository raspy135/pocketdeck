import time
import argparse
import array
import math
import os
import pdeck
import pdeck_utils
import esclib as elib
import anm
import pem_open
try:
  import micropython
except ImportError:
  micropython = None

KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_RIGHT = b'\x1b[C'
KEY_LEFT = b'\x1b[D'

DEFAULT_ROOT = '/sd/Documents/home.md'
VAULT_ROOT = '/sd/Documents'
CENTER_X = 200
CENTER_Y = 124

_LAYOUT_SCALE = 1024
_LAYOUT_SHIFT = 10
_LAYOUT_D2_SHIFT = 4
_LAYOUT_D2_AXIS_SCALE = _LAYOUT_SCALE >> _LAYOUT_D2_SHIFT
_LAYOUT_D2_SCALE = _LAYOUT_D2_AXIS_SCALE * _LAYOUT_D2_AXIS_SCALE
_LAYOUT_D2_BIAS = int(0.1 * _LAYOUT_D2_SCALE)
_LAYOUT_D2_LIMIT = 13000 * _LAYOUT_D2_SCALE
_LAYOUT_FORCE_NUM = 68 * _LAYOUT_SCALE * _LAYOUT_D2_SCALE
_LAYOUT_FORCE_MAX = int(0.055 * _LAYOUT_SCALE)


# On the device, micropython.viper compiles the integer kernel below. On a
# non-viper runtime (CPython/emulator) the ptr32 annotations aren't real names,
# so building the annotated def raises NameError — catch it and fall through to
# the pure-Python version, which produces identical results on array('i').
_have_viper = False
if micropython:
  try:
    @micropython.viper
    def _layout_repulse_int(x: ptr32, y: ptr32, vx: ptr32, vy: ptr32, n: int):
      shift = int(_LAYOUT_D2_SHIFT)
      pos_scale = int(_LAYOUT_SCALE)
      d2_bias = int(_LAYOUT_D2_BIAS)
      d2_limit = int(_LAYOUT_D2_LIMIT)
      force_num = int(_LAYOUT_FORCE_NUM)
      force_max = int(_LAYOUT_FORCE_MAX)
      for i in range(n):
        xi = x[i]
        yi = y[i]
        vxi = vx[i]
        vyi = vy[i]
        j = i + 1
        while j < n:
          dx = xi - x[j]
          dy = yi - y[j]
          sdx = dx >> shift
          sdy = dy >> shift
          d2 = sdx * sdx + sdy * sdy + d2_bias
          if d2 <= d2_limit:
            force = force_num // d2
            if force > force_max:
              force = force_max
            fx = (dx * force) // pos_scale
            fy = (dy * force) // pos_scale
            if i != 0:
              vxi += fx
              vyi += fy
            if j != 0:
              vx[j] -= fx
              vy[j] -= fy
          j += 1
        if i != 0:
          vx[i] = vxi
          vy[i] = vyi
    _have_viper = True
  except NameError:
    pass

if not _have_viper:
  def _layout_repulse_int(x, y, vx, vy, n):
    shift = _LAYOUT_D2_SHIFT
    pos_scale = _LAYOUT_SCALE
    d2_bias = _LAYOUT_D2_BIAS
    d2_limit = _LAYOUT_D2_LIMIT
    force_num = _LAYOUT_FORCE_NUM
    force_max = _LAYOUT_FORCE_MAX
    for i in range(n):
      xi = x[i]
      yi = y[i]
      vxi = vx[i]
      vyi = vy[i]
      for j in range(i + 1, n):
        dx = xi - x[j]
        dy = yi - y[j]
        sdx = dx >> shift
        sdy = dy >> shift
        d2 = sdx * sdx + sdy * sdy + d2_bias
        if d2 > d2_limit:
          continue
        force = force_num // d2
        if force > force_max:
          force = force_max
        fx = (dx * force) // pos_scale
        fy = (dy * force) // pos_scale
        if i != 0:
          vxi += fx
          vyi += fy
        if j != 0:
          vx[j] -= fx
          vy[j] -= fy
      if i != 0:
        vx[i] = vxi
        vy[i] = vyi


def exists(path):
  try:
    os.stat(path)
    return True
  except Exception:
    return False


def is_dir(path):
  try:
    return (os.stat(path)[0] & 0x4000) != 0
  except Exception:
    return False


def join_path(a, b):
  if not a or a == '/':
    return '/' + b
  if a.endswith('/'):
    return a + b
  return a + '/' + b


def dirname(path):
  i = path.rfind('/')
  if i <= 0:
    return '/'
  return path[:i]


def basename(path):
  i = path.rfind('/')
  if i < 0:
    return path
  return path[i + 1:]


def norm_path(path):
  absolute = path.startswith('/')
  parts = []
  for p in path.split('/'):
    if p == '' or p == '.':
      continue
    if p == '..':
      if parts:
        parts.pop()
    else:
      parts.append(p)
  out = '/'.join(parts)
  if absolute:
    return '/' + out
  return out


def display_name(path_or_link):
  name = basename(path_or_link)
  if name.endswith('.md'):
    name = name[:-3]
  return name


def clean_link(link):
  link = link.strip()
  bar = link.find('|')
  if bar >= 0:
    link = link[:bar].strip()
  sharp = link.find('#')
  if sharp >= 0:
    link = link[:sharp].strip()
  return link


def parse_links(text):
  links = []
  pos = 0
  while True:
    start = text.find('[[', pos)
    if start < 0:
      break
    end = text.find(']]', start + 2)
    if end < 0:
      break
    if start == 0 or text[start - 1] != '!':
      link = clean_link(text[start + 2:end])
      if link:
        links.append(link)
    pos = end + 2
  return links


def resolve_root(arg):
  if not arg:
    return DEFAULT_ROOT
  tries = []
  if arg.startswith('/'):
    tries.append(arg)
  else:
    tries.append(join_path(VAULT_ROOT, arg))
    try:
      tries.append(join_path(os.getcwd(), arg))
    except Exception:
      pass
    tries.append(arg)
  more = []
  for p in tries:
    more.append(p)
    if not p.endswith('.md'):
      more.append(p + '.md')
  for p in more:
    p = norm_path(p)
    if exists(p) and not is_dir(p):
      return p
  if arg.startswith('/'):
    return norm_path(arg)
  return norm_path(join_path(VAULT_ROOT, arg))


def resolve_link(base_file, link):
  link = clean_link(link)
  if not link:
    return None
  tries = []
  if link.startswith('/'):
    tries.append(link)
  else:
    tries.append(join_path(dirname(base_file), link))
    tries.append(join_path(VAULT_ROOT, link))
  more = []
  for p in tries:
    more.append(p)
    if not p.endswith('.md'):
      more.append(p + '.md')
  for p in more:
    p = norm_path(p)
    if exists(p) and not is_dir(p):
      return p
  return None


class GraphCache:
  def __init__(self):
    self.file_links = {}
    self.link_targets = {}
    self.file_hits = 0
    self.file_misses = 0
    self.resolve_hits = 0
    self.resolve_misses = 0

  def clear(self):
    self.file_links = {}
    self.link_targets = {}
    self.file_hits = 0
    self.file_misses = 0
    self.resolve_hits = 0
    self.resolve_misses = 0


class GraphLoader:
  def __init__(self, root_file, max_nodes=90, max_edges=220, max_files=80, max_depth=None, cache=None):
    self.root_file = root_file
    self.max_nodes = max_nodes
    self.max_edges = max_edges
    self.max_files = max_files
    self.max_depth = max_depth
    self.cache = cache if cache is not None else GraphCache()
    self.cache_hits = 0
    self.cache_misses = 0
    self.resolve_cache_hits = 0
    self.resolve_cache_misses = 0
    self.nodes = []
    self.edges = []
    self.node_index = {}
    self.edge_set = {}
    self.children = {}
    self.child_set = {}
    self.queue = []
    self.visited = {}
    self.files_loaded = 0
    self.errors = 0
    self.capped = False
    self.done = False
    root = self.add_node(root_file, root_file, True, 0, None)
    if root is not None:
      self.queue.append(root_file)

  def add_node(self, key, path, resolved, depth, parent):
    if key in self.node_index:
      idx = self.node_index[key]
      n = self.nodes[idx]
      if path and not n['path']:
        n['path'] = path
      if resolved:
        n['resolved'] = True
      if parent is not None:
        if n.get('parent', None) is None or depth < n['depth']:
          n['parent'] = parent
      if depth < n['depth']:
        n['depth'] = depth
      return idx
    if len(self.nodes) >= self.max_nodes:
      self.capped = True
      return None
    idx = len(self.nodes)
    if parent is None or parent >= len(self.nodes):
      x = 0.0
      y = 0.0
    else:
      angle = (idx * 2.399963) % 6.283185
      radius = 22.0 + (idx % 5) * 6.0
      p = self.nodes[parent]
      x = p['x'] + math.cos(angle) * radius
      y = p['y'] + math.sin(angle) * radius
    node = {
      'key': key,
      'name': display_name(path or key),
      'path': path,
      'resolved': resolved,
      'loaded': False,
      'depth': depth,
      'parent': parent,
      'x': x,
      'y': y,
      'vx': 0.0,
      'vy': 0.0,
    }
    self.nodes.append(node)
    self.node_index[key] = idx
    return idx

  def add_edge(self, a, b):
    if a is None or b is None or a == b:
      return
    dkey = str(a) + ':' + str(b)
    if dkey not in self.child_set:
      self.child_set[dkey] = True
      if a not in self.children:
        self.children[a] = []
      self.children[a].append(b)
    if len(self.edges) >= self.max_edges:
      self.capped = True
      return
    if a < b:
      key = str(a) + ':' + str(b)
    else:
      key = str(b) + ':' + str(a)
    if key in self.edge_set:
      return
    self.edge_set[key] = True
    self.edges.append((a, b))

  def child_list(self, idx):
    return self.children.get(idx, [])

  def is_child(self, parent, child):
    return (str(parent) + ':' + str(child)) in self.child_set

  def child_count(self, idx):
    return len(self.children.get(idx, []))

  def load_links(self, path):
    entry = self.cache.file_links.get(path, None)
    if entry is not None:
      self.cache.file_hits += 1
      self.cache_hits += 1
      return entry[0], entry[1]
    try:
      #print('load')
      with open(path, 'r') as f:
        text = f.read()
      ok = True
      links = parse_links(text)
    except Exception:
      ok = False
      links = None
    self.cache.file_links[path] = (ok, links)
    self.cache.file_misses += 1
    self.cache_misses += 1
    return ok, links

  def resolve_link_cached(self, base_file, link):
    link = clean_link(link)
    if not link:
      return None
    key = base_file + '\n' + link
    resolved = self.cache.link_targets.get(key, None)
    if resolved is not None and exists(resolved):
      self.cache.resolve_hits += 1
      self.resolve_cache_hits += 1
      return resolved
    resolved = resolve_link(base_file, link)
    if resolved:
      self.cache.link_targets[key] = resolved
    else:
      try:
        del self.cache.link_targets[key]
      except Exception:
        pass
    self.cache.resolve_misses += 1
    self.resolve_cache_misses += 1
    return resolved

  def step(self, budget=1):
    if self.done:
      return 0
    count = 0
    while self.queue and count < budget:
      path = self.queue.pop(0)
      if path in self.visited:
        continue
      if self.files_loaded >= self.max_files:
        self.capped = True
        self.done = True
        return count
      self.visited[path] = True
      idx = self.node_index.get(path, None)
      if idx is None:
        continue
      ok, links = self.load_links(path)
      self.nodes[idx]['loaded'] = True
      self.files_loaded += 1
      depth = self.nodes[idx]['depth']
      if not ok:
        self.errors += 1
        count += 1
        continue
      if self.max_depth is not None and depth >= self.max_depth:
        count += 1
        continue
      for link in links:
        resolved = self.resolve_link_cached(path, link)
        if resolved:
          key = resolved
          child = self.add_node(key, resolved, True, self.nodes[idx]['depth'] + 1, idx)
        else:
          key = 'link:' + link
          child = self.add_node(key, None, False, self.nodes[idx]['depth'] + 1, idx)
        self.add_edge(idx, child)
        if child is not None and resolved and resolved not in self.visited:
          already = False
          for q in self.queue:
            if q == resolved:
              already = True
              break
          if not already:
            self.queue.append(resolved)
      count += 1
    if not self.queue:
      self.done = True
    return count


class GraphApp:
  def __init__(self, vs, root_file, max_nodes=90, max_depth=None):
    self.vs = vs
    self.v = vs.v
    self.root_file = root_file
    self.max_depth = max_depth
    self.cache = GraphCache()
    self.loader = GraphLoader(root_file, max_nodes=max_nodes, max_depth=max_depth, cache=self.cache)
    self.running = True
    self.cam_x = 200.0
    self.cam_y = 126.0
    self.zoom = 1.0
    self.target_cam_x = self.cam_x
    self.target_cam_y = self.cam_y
    self.target_zoom = self.zoom
    self.seq = anm.anm_sequencer()
    self.frame = 0
    self.selected = 0
    self.need_select = True
    self.layout_active = True
    self.settle_count = 0
    self.last_node_count = 1
    self.last_edge_count = 0
    self.load_done_frame = None
    self.touch_last = None
    self.last_scale_slider = 255
    self.last_click_bits = 0
    self.root_history = []
    self.reset_search_state()
    self.reset_search_state()
    self.clear_layout_arrays()
    self.rebuild_layout_arrays()

  def sx(self, x):
    return int(x * self.zoom + self.cam_x)

  def sy(self, y):
    return int(y * self.zoom + self.cam_y)

  def clamp_zoom(self, value):
    if value < 0.25:
      return 0.25
    if value > 3.0:
      return 3.0
    return value

  def set_zoom_target(self, zoom, duration=80):
    nodes = self.loader.nodes
    self.target_zoom = self.clamp_zoom(zoom)
    if nodes and self.selected < len(nodes):
      node = nodes[self.selected]
      self.target_cam_x = CENTER_X - node['x'] * self.target_zoom
      self.target_cam_y = CENTER_Y - node['y'] * self.target_zoom
    self.animate_camera(duration)

  def zoom_step(self, steps, duration=80):
    if steps == 0:
      return False
    factor = 1.0
    if steps > 0:
      for _ in range(steps):
        factor *= 1.12
    else:
      for _ in range(-steps):
        factor /= 1.12
    self.set_zoom_target(self.target_zoom * factor, duration)
    return True

  def handle_scale_slider(self, raw):
    # Use the touch strip relatively like Nudoc: store the first touch value,
    # then apply one zoom step for each threshold crossing.
    if raw == 255:
      self.last_scale_slider = 255
      return False
    if raw < 0:
      raw = 0
    if raw > 100:
      raw = 100
    if self.last_scale_slider == 255:
      self.last_scale_slider = raw
      return False
    step = 5
    delta = 0
    diff = raw - self.last_scale_slider
    while diff >= step:
      delta += 1
      self.last_scale_slider += step
      diff = raw - self.last_scale_slider
    while diff <= -step:
      delta -= 1
      self.last_scale_slider -= step
      diff = raw - self.last_scale_slider
    if delta:
      return self.zoom_step(delta, 70)
    return False

  def camera_busy(self):
    if abs(self.cam_x - self.target_cam_x) > 0.2:
      return True
    if abs(self.cam_y - self.target_cam_y) > 0.2:
      return True
    if abs(self.zoom - self.target_zoom) > 0.01:
      return True
    return False

  def animate_camera(self, duration=80):
    self.target_zoom = self.clamp_zoom(self.target_zoom)
    dx = abs(self.target_cam_x - self.cam_x)
    dy = abs(self.target_cam_y - self.cam_y)
    dz = abs(self.target_zoom - self.zoom)
    if dx < 0.05 and dy < 0.05 and dz < 0.001:
      self.cam_x = self.target_cam_x
      self.cam_y = self.target_cam_y
      self.zoom = self.target_zoom
      self.need_select = True
      return
    try:
      self.seq.unregister('cam')
    except Exception:
      pass
    obj = anm.anm_object(duration, {
      'x': [anm.ease_out, self.cam_x, self.target_cam_x],
      'y': [anm.ease_out, self.cam_y, self.target_cam_y],
      'z': [anm.ease_out, self.zoom, self.target_zoom],
    }, auto_unregister=True)
    self.seq.register('cam', obj)
    self.need_select = True

  def pan_by(self, dx, dy, duration=140):
    self.target_cam_x += dx
    self.target_cam_y += dy
    self.animate_camera(duration)

  def zoom_by(self, factor, duration=180):
    self.target_zoom = self.clamp_zoom(self.target_zoom * factor)
    self.animate_camera(duration)

  def reset_view(self):
    self.target_cam_x = 200.0
    self.target_cam_y = 126.0
    self.target_zoom = 1.0
    self.animate_camera(240)

  def center_on_selected(self):
    nodes = self.loader.nodes
    if not nodes or self.selected >= len(nodes):
      return
    node = nodes[self.selected]
    self.target_cam_x = CENTER_X - node['x'] * self.target_zoom
    self.target_cam_y = CENTER_Y - node['y'] * self.target_zoom
    self.animate_camera(220)


  def reset_search_state(self):
    self.search_active = False
    self.search_query = ''
    self.search_matches = []
    self.search_match_pos = -1
    self.search_failed = False
    self.search_saved_selected = 0
    self.search_saved_cam_x = 200.0
    self.search_saved_cam_y = 126.0
    self.search_saved_zoom = 1.0
    self.search_saved_target_cam_x = 200.0
    self.search_saved_target_cam_y = 126.0
    self.search_saved_target_zoom = 1.0

  def search_begin(self):
    if self.search_active:
      if self.search_query:
        return self.search_next()
      return True
    self.search_active = True
    self.search_query = ''
    self.search_matches = []
    self.search_match_pos = -1
    self.search_failed = False
    self.search_saved_selected = self.selected
    self.search_saved_cam_x = self.cam_x
    self.search_saved_cam_y = self.cam_y
    self.search_saved_zoom = self.zoom
    self.search_saved_target_cam_x = self.target_cam_x
    self.search_saved_target_cam_y = self.target_cam_y
    self.search_saved_target_zoom = self.target_zoom
    return True

  def search_finish(self):
    if not self.search_active:
      return False
    self.reset_search_state()
    return True

  def search_cancel(self):
    if not self.search_active:
      return False
    selected = self.search_saved_selected
    cam_x = self.search_saved_cam_x
    cam_y = self.search_saved_cam_y
    zoom = self.search_saved_zoom
    target_cam_x = self.search_saved_target_cam_x
    target_cam_y = self.search_saved_target_cam_y
    target_zoom = self.search_saved_target_zoom
    self.reset_search_state()
    nodes = self.loader.nodes
    if nodes:
      if selected < 0:
        selected = 0
      if selected >= len(nodes):
        selected = len(nodes) - 1
      self.selected = selected
    try:
      self.seq.unregister('cam')
    except Exception:
      pass
    self.cam_x = cam_x
    self.cam_y = cam_y
    self.zoom = zoom
    self.target_cam_x = target_cam_x
    self.target_cam_y = target_cam_y
    self.target_zoom = target_zoom
    self.need_select = False
    return True

  def node_search_text(self, idx):
    nodes = self.loader.nodes
    if idx < 0 or idx >= len(nodes):
      return ''
    node = nodes[idx]
    parts = [node.get('name', '')]
    path = node.get('path', None)
    if path:
      parts.append(path)
    key = node.get('key', '')
    if key and key != path:
      parts.append(key)
    return ' '.join(parts).lower()

  def search_find_matches(self, query):
    q = query.lower()
    out = []
    for i in range(len(self.loader.nodes)):
      if q in self.node_search_text(i):
        out.append(i)
    return out

  def order_matches_from(self, matches, start):
    nodes = self.loader.nodes
    n = len(nodes)
    if n <= 0 or not matches:
      return []
    found = {}
    for idx in matches:
      found[idx] = True
    out = []
    if start < 0 or start >= n:
      start = 0
    for offset in range(n):
      idx = (start + offset) % n
      if idx in found:
        out.append(idx)
    return out

  def search_select_match(self, idx):
    nodes = self.loader.nodes
    if idx < 0 or idx >= len(nodes):
      return False
    self.selected = idx
    self.center_on_selected()
    self.need_select = False
    return True

  def search_apply_query(self, prefer_current=True):
    if not self.search_active:
      return False
    if not self.search_query:
      self.search_matches = []
      self.search_match_pos = -1
      self.search_failed = False
      return False
    matches = self.search_find_matches(self.search_query)
    self.search_matches = matches
    if not matches:
      self.search_match_pos = -1
      self.search_failed = True
      return False
    ordered = self.order_matches_from(matches, self.search_saved_selected)
    pos = 0
    if prefer_current and self.selected in ordered:
      pos = ordered.index(self.selected)
    self.search_match_pos = pos
    self.search_failed = False
    return self.search_select_match(ordered[pos])

  def search_next(self):
    if not self.search_active:
      return self.search_begin()
    if not self.search_query:
      return True
    matches = self.search_find_matches(self.search_query)
    self.search_matches = matches
    if not matches:
      self.search_match_pos = -1
      self.search_failed = True
      return False
    ordered = self.order_matches_from(matches, self.search_saved_selected)
    pos = -1
    if self.selected in ordered:
      pos = ordered.index(self.selected)
    pos = (pos + 1) % len(ordered)
    self.search_match_pos = pos
    self.search_failed = False
    return self.search_select_match(ordered[pos])

  def is_printable_search_char(self, k):
    if not k or len(k) != 1:
      return False
    code = k[0]
    return code >= 32 and code <= 126

  def handle_search_key(self, k):
    if not self.search_active:
      if k == bytes([19]):
        self.search_begin()
        return True
      return False
    if k == bytes([19]):
      self.search_next()
      return True
    if k == bytes([7]):
      self.search_cancel()
      return True
    if k == KEY_UP or k == KEY_DOWN or k == KEY_LEFT or k == KEY_RIGHT:
      self.search_finish()
      return False
    if k == bytes([8]) or k == bytes([127]):
      if not self.search_query:
        self.search_cancel()
        return True
      self.search_query = self.search_query[:-1]
      if not self.search_query:
        self.search_cancel()
      else:
        self.search_apply_query(True)
      return True
    if k == bytes([13]) or k == bytes([10]):
      self.search_finish()
      return False
    if self.is_printable_search_char(k):
      try:
        ch = k.decode('ascii')
      except Exception:
        return True
      self.search_query += ch
      self.search_apply_query(True)
      return True
    self.search_finish()
    return False



  def reset_search_state(self):
    self.search_active = False
    self.search_query = ''
    self.search_matches = []
    self.search_match_pos = -1
    self.search_failed = False
    self.search_saved_selected = 0
    self.search_saved_cam_x = 200.0
    self.search_saved_cam_y = 126.0
    self.search_saved_zoom = 1.0
    self.search_saved_target_cam_x = 200.0
    self.search_saved_target_cam_y = 126.0
    self.search_saved_target_zoom = 1.0

  def search_begin(self):
    if self.search_active:
      if self.search_query:
        return self.search_next()
      return True
    self.search_active = True
    self.search_query = ''
    self.search_matches = []
    self.search_match_pos = -1
    self.search_failed = False
    self.search_saved_selected = self.selected
    self.search_saved_cam_x = self.cam_x
    self.search_saved_cam_y = self.cam_y
    self.search_saved_zoom = self.zoom
    self.search_saved_target_cam_x = self.target_cam_x
    self.search_saved_target_cam_y = self.target_cam_y
    self.search_saved_target_zoom = self.target_zoom
    return True

  def search_finish(self):
    if not self.search_active:
      return False
    self.reset_search_state()
    return True

  def search_cancel(self):
    if not self.search_active:
      return False
    selected = self.search_saved_selected
    cam_x = self.search_saved_cam_x
    cam_y = self.search_saved_cam_y
    zoom = self.search_saved_zoom
    target_cam_x = self.search_saved_target_cam_x
    target_cam_y = self.search_saved_target_cam_y
    target_zoom = self.search_saved_target_zoom
    self.reset_search_state()
    nodes = self.loader.nodes
    if nodes:
      if selected < 0:
        selected = 0
      if selected >= len(nodes):
        selected = len(nodes) - 1
      self.selected = selected
    try:
      self.seq.unregister('cam')
    except Exception:
      pass
    self.cam_x = cam_x
    self.cam_y = cam_y
    self.zoom = zoom
    self.target_cam_x = target_cam_x
    self.target_cam_y = target_cam_y
    self.target_zoom = target_zoom
    self.need_select = False
    return True

  def node_search_text(self, idx):
    nodes = self.loader.nodes
    if idx < 0 or idx >= len(nodes):
      return ''
    node = nodes[idx]
    parts = [node.get('name', '')]
    path = node.get('path', None)
    if path:
      parts.append(path)
    key = node.get('key', '')
    if key and key != path:
      parts.append(key)
    return ' '.join(parts).lower()

  def search_find_matches(self, query):
    q = query.lower()
    out = []
    for i in range(len(self.loader.nodes)):
      if q in self.node_search_text(i):
        out.append(i)
    return out

  def order_matches_from(self, matches, start):
    nodes = self.loader.nodes
    n = len(nodes)
    if n <= 0 or not matches:
      return []
    found = {}
    for idx in matches:
      found[idx] = True
    out = []
    if start < 0 or start >= n:
      start = 0
    for offset in range(n):
      idx = (start + offset) % n
      if idx in found:
        out.append(idx)
    return out

  def search_select_match(self, idx):
    nodes = self.loader.nodes
    if idx < 0 or idx >= len(nodes):
      return False
    self.selected = idx
    self.center_on_selected()
    self.need_select = False
    return True

  def search_apply_query(self, prefer_current=True):
    if not self.search_active:
      return False
    if not self.search_query:
      self.search_matches = []
      self.search_match_pos = -1
      self.search_failed = False
      return False
    matches = self.search_find_matches(self.search_query)
    self.search_matches = matches
    if not matches:
      self.search_match_pos = -1
      self.search_failed = True
      return False
    ordered = self.order_matches_from(matches, self.search_saved_selected)
    pos = 0
    if prefer_current and self.selected in ordered:
      pos = ordered.index(self.selected)
    self.search_match_pos = pos
    self.search_failed = False
    return self.search_select_match(ordered[pos])

  def search_next(self):
    if not self.search_active:
      return self.search_begin()
    if not self.search_query:
      return True
    matches = self.search_find_matches(self.search_query)
    self.search_matches = matches
    if not matches:
      self.search_match_pos = -1
      self.search_failed = True
      return False
    ordered = self.order_matches_from(matches, self.search_saved_selected)
    pos = -1
    if self.selected in ordered:
      pos = ordered.index(self.selected)
    pos = (pos + 1) % len(ordered)
    self.search_match_pos = pos
    self.search_failed = False
    return self.search_select_match(ordered[pos])

  def is_printable_search_char(self, k):
    if not k or len(k) != 1:
      return False
    code = k[0]
    return code >= 32 and code <= 126

  def handle_search_key(self, k):
    if not self.search_active:
      if k == bytes([19]):
        self.search_begin()
        return True
      return False
    if k == bytes([19]):
      self.search_next()
      return True
    if k == bytes([7]):
      self.search_cancel()
      return True
    if k == KEY_UP or k == KEY_DOWN or k == KEY_LEFT or k == KEY_RIGHT:
      self.search_finish()
      return False
    if k == bytes([8]) or k == bytes([127]):
      if not self.search_query:
        self.search_cancel()
        return True
      self.search_query = self.search_query[:-1]
      if not self.search_query:
        self.search_cancel()
      else:
        self.search_apply_query(True)
      return True
    if k == bytes([13]) or k == bytes([10]):
      self.search_finish()
      return False
    if self.is_printable_search_char(k):
      try:
        ch = k.decode('ascii')
      except Exception:
        return True
      self.search_query += ch
      self.search_apply_query(True)
      return True
    self.search_finish()
    return False


  def clear_layout_arrays(self):
    self.layout_x = array.array('f')
    self.layout_y = array.array('f')
    self.layout_vx = array.array('f')
    self.layout_vy = array.array('f')
    self.layout_ix = array.array('i')
    self.layout_iy = array.array('i')
    self.layout_ivx = array.array('i')
    self.layout_ivy = array.array('i')
    self.layout_parent = array.array('h')
    self.layout_child_count = array.array('h')
    self.layout_cache_nodes = -1
    self.layout_cache_edges = -1

  def rebuild_layout_arrays(self):
    nodes = self.loader.nodes
    n = len(nodes)
    scale = _LAYOUT_SCALE
    self.layout_x = array.array('f')
    self.layout_y = array.array('f')
    self.layout_vx = array.array('f')
    self.layout_vy = array.array('f')
    self.layout_ix = array.array('i')
    self.layout_iy = array.array('i')
    self.layout_ivx = array.array('i')
    self.layout_ivy = array.array('i')
    self.layout_parent = array.array('h')
    self.layout_child_count = array.array('h')
    for i in range(n):
      node = nodes[i]
      parent = node.get('parent', None)
      if parent is None:
        parent = -1
      x = float(node['x'])
      y = float(node['y'])
      vx = float(node['vx'])
      vy = float(node['vy'])
      self.layout_x.append(x)
      self.layout_y.append(y)
      self.layout_vx.append(vx)
      self.layout_vy.append(vy)
      self.layout_ix.append(int(x * scale))
      self.layout_iy.append(int(y * scale))
      self.layout_ivx.append(int(vx * scale))
      self.layout_ivy.append(int(vy * scale))
      self.layout_parent.append(int(parent))
      self.layout_child_count.append(int(len(self.loader.children.get(i, ()))))
    self.layout_cache_nodes = n
    self.layout_cache_edges = len(self.loader.edges)

  def ensure_layout_arrays(self):
    if self.layout_cache_nodes != len(self.loader.nodes):
      self.rebuild_layout_arrays()
      return
    if self.layout_cache_edges != len(self.loader.edges):
      self.rebuild_layout_arrays()

  def sync_layout_fixed(self, count):
    scale = _LAYOUT_SCALE
    x = self.layout_x
    y = self.layout_y
    vx = self.layout_vx
    vy = self.layout_vy
    ix = self.layout_ix
    iy = self.layout_iy
    ivx = self.layout_ivx
    ivy = self.layout_ivy
    for i in range(count):
      ix[i] = int(x[i] * scale)
      iy[i] = int(y[i] * scale)
      ivx[i] = int(vx[i] * scale)
      ivy[i] = int(vy[i] * scale)

  def selected_node_path(self):
    nodes = self.loader.nodes
    if not nodes or self.selected >= len(nodes):
      return None
    node = nodes[self.selected]
    if not node['resolved']:
      return None
    return node['path']

  def rebuild_loader(self, root_file, keep_cache=True):
    old = self.loader
    self.root_file = root_file
    if not keep_cache:
      self.cache.clear()
    self.loader = GraphLoader(
      root_file,
      max_nodes=old.max_nodes,
      max_edges=old.max_edges,
      max_files=old.max_files,
      max_depth=old.max_depth,
      cache=self.cache,
    )
    self.selected = 0
    self.need_select = True
    self.layout_active = True
    self.settle_count = 0
    self.last_node_count = 1
    self.last_edge_count = 0
    self.load_done_frame = None
    self.touch_last = None
    self.last_scale_slider = 255
    self.last_click_bits = 0
    self.reset_search_state()
    self.reset_search_state()
    self.target_cam_x = 200.0
    self.target_cam_y = 126.0
    self.target_zoom = 1.0
    self.clear_layout_arrays()
    self.rebuild_layout_arrays()
    self.animate_camera(240)

  def reload_current_root(self):
    self.rebuild_loader(self.root_file, keep_cache=False)
    print('Reload root: ' + display_name(self.root_file), file=self.vs)
    return True

  def reroot_to_selected(self):
    path = self.selected_node_path()
    if not path:
      return False
    if path == self.root_file:
      return self.reload_current_root()
    self.root_history.append(self.root_file)
    self.rebuild_loader(path)
    print('Reroot: ' + display_name(path), file=self.vs)
    return True

  def go_parent(self):
    nodes = self.loader.nodes
    if not nodes or self.selected >= len(nodes):
      return False
    if self.selected == 0:
      if self.root_history:
        path = self.root_history.pop()
        self.rebuild_loader(path)
        print('Parent root: ' + display_name(path), file=self.vs)
        return True
      return self.reload_current_root()
    parent = nodes[self.selected].get('parent', None)
    if parent is None or parent < 0 or parent >= len(nodes):
      return False
    self.selected = parent
    self.need_select = False
    self.center_on_selected()
    return True

  def find_pem_launch_screen(self):
    current = pdeck.get_screen_num()
    for screen in range(2, 9):
      if screen == current:
        continue
      try:
        if not pdeck.cmd_exists(screen):
          return screen
      except Exception:
        pass
    return current

  def open_selected_node(self):
    path = self.selected_node_path()
    if not path:
      return False
    screen_before = pdeck.get_screen_num()
    try:
      pem_open.main(self.vs, ['pem_open', path])
      if pdeck.get_screen_num() != screen_before:
        return True
    except Exception:
      pass
    try:
      screen = self.find_pem_launch_screen()
      pdeck_utils.launch(['pem', path], screen)
      pdeck.change_screen(screen)
      return True
    except Exception as e:
      print('Pem launch failed: ' + str(e), file=self.vs)
      return False

  def update_camera(self):
    self.seq.update(time.ticks_ms())
    obj = None
    try:
      obj = self.seq.get_obj('cam')
    except Exception:
      obj = None
    if obj is not None:
      self.cam_x = obj.x
      self.cam_y = obj.y
      self.zoom = obj.z
      self.need_select = True
    else:
      self.cam_x = self.target_cam_x
      self.cam_y = self.target_cam_y
      self.zoom = self.target_zoom

  def disturb_layout(self):
    self.layout_active = True
    self.settle_count = 0

  def settle_layout(self):
    self.ensure_layout_arrays()
    nodes = self.loader.nodes
    count = len(self.layout_vx)
    for i in range(count):
      self.layout_vx[i] = 0.0
      self.layout_vy[i] = 0.0
      if i < len(nodes):
        nodes[i]['vx'] = 0.0
        nodes[i]['vy'] = 0.0
    if nodes:
      self.layout_x[0] = 0.0
      self.layout_y[0] = 0.0
      nodes[0]['x'] = 0.0
      nodes[0]['y'] = 0.0
    self.layout_active = False

  def layout_step(self):
    nodes = self.loader.nodes
    n = len(nodes)

    if n <= 1 or not self.layout_active:
      return

    self.ensure_layout_arrays()
    x = self.layout_x
    y = self.layout_y
    vx = self.layout_vx
    vy = self.layout_vy
    parent = self.layout_parent
    child_count = self.layout_child_count
    edges = self.loader.edges

    x[0] = 0.0
    y[0] = 0.0
    vx[0] = 0.0
    vy[0] = 0.0

    self.sync_layout_fixed(n)
    _layout_repulse_int(self.layout_ix, self.layout_iy, self.layout_ivx, self.layout_ivy, n)
    inv_scale = 1.0 / _LAYOUT_SCALE
    for i in range(1, n):
      vx[i] = self.layout_ivx[i] * inv_scale
      vy[i] = self.layout_ivy[i] * inv_scale

    selected = self.selected
    sqrt = math.sqrt
    for edge in edges:
      a = edge[0]
      b = edge[1]
      if a >= n or b >= n:
        continue
      dx = x[b] - x[a]
      dy = y[b] - y[a]
      dist = sqrt(dx * dx + dy * dy + 0.1)
      target = 42.0
      if parent[b] == a:
        target = 26.0 + min(30.0, child_count[b] * 3.0)
      elif parent[a] == b:
        target = 26.0 + min(30.0, child_count[a] * 3.0)
      if a == selected and parent[b] == a:
        target = 20.0 + min(26.0, child_count[b] * 2.5)
      elif b == selected and parent[a] == b:
        target = 20.0 + min(26.0, child_count[a] * 2.5)
      f = (dist - target) * 0.0034
      if dist > 0.1:
        inv = f / dist
        fx = dx * inv
        fy = dy * inv
        if a != 0:
          vx[a] += fx
          vy[a] += fy
        if b != 0:
          vx[b] -= fx
          vy[b] -= fy

    max_speed = 0.0
    damping = 0.74
    if self.loader.done:
      damping = 0.68

    nodes[0]['x'] = 0.0
    nodes[0]['y'] = 0.0
    nodes[0]['vx'] = 0.0
    nodes[0]['vy'] = 0.0
    for i in range(1, n):
      xi = x[i]
      yi = y[i]
      vxi = vx[i] - xi * 0.0014
      vyi = vy[i] - yi * 0.0014
      vxi *= damping
      vyi *= damping
      if vxi > 4.0:
        vxi = 4.0
      elif vxi < -4.0:
        vxi = -4.0
      if vyi > 4.0:
        vyi = 4.0
      elif vyi < -4.0:
        vyi = -4.0
      if -0.01 < vxi < 0.01:
        vxi = 0.0
      if -0.01 < vyi < 0.01:
        vyi = 0.0
      xi += vxi
      yi += vyi
      x[i] = xi
      y[i] = yi
      vx[i] = vxi
      vy[i] = vyi
      node = nodes[i]
      node['x'] = xi
      node['y'] = yi
      node['vx'] = vxi
      node['vy'] = vyi
      speed = abs(vxi) + abs(vyi)
      if speed > max_speed:
        max_speed = speed

    if self.loader.done:
      if self.load_done_frame is None:
        self.load_done_frame = self.frame
      done_age = self.frame - self.load_done_frame
      if max_speed < 0.04:
        self.settle_count += 1
      elif done_age >= 60 and max_speed < 0.10:
        self.settle_count += 2
      else:
        self.settle_count = 0
      if self.settle_count > 3 or done_age >= 120:
        self.settle_layout()
    else:
      self.load_done_frame = None
      self.settle_count = 0

  def choose_selected(self):
    nodes = self.loader.nodes
    if not nodes:
      self.selected = 0
      return
    best = self.selected
    best_score = 1 << 30
    visible_found = False
    for i in range(len(nodes)):
      sx = self.sx(nodes[i]['x'])
      sy = self.sy(nodes[i]['y'])
      visible = sx >= 0 and sx <= 399 and sy >= 20 and sy <= 228
      if visible:
        visible_found = True
      if visible_found and not visible:
        continue
      dx = sx - CENTER_X
      dy = sy - CENTER_Y
      score = dx * dx + dy * dy + nodes[i]['depth'] * 40
      if not nodes[i]['resolved']:
        score += 400
      if score < best_score:
        best_score = score
        best = i
    self.selected = best
    self.need_select = False

  def draw_header(self):
    v = self.v
    l = self.loader
    v.set_draw_color(1)
    v.draw_box(0, 0, 400, 18)
    v.set_draw_color(0)
    v.set_font('u8g2_font_profont15_mf')
    if l.done:
      s = 'Graph {} nodes {} edges'.format(len(l.nodes), len(l.edges))
    else:
      s = 'Loading files:{} queue:{} nodes:{}'.format(l.files_loaded, len(l.queue), len(l.nodes))
    if l.capped:
      s += ' CAP'
    if l.errors:
      s += ' err:' + str(l.errors)
    if not self.layout_active and l.done:
      s += ' settled'
    v.draw_str(4, 14, s[:54])
    v.set_draw_color(1)

  def draw_scale_slider(self):
    v = self.v
    x = 292
    y = 235
    w = 100
    v.set_draw_color(1)
    v.draw_frame(x, y - 8, w, 7)
    pos = int((self.zoom - 0.30) * w / 2.70)
    if pos < 0:
      pos = 0
    if pos > w - 4:
      pos = w - 4
    v.draw_box(x + pos, y - 10, 5, 11)
    v.draw_str(x, y - 11, 'scale')

  def draw_footer(self):
    nodes = self.loader.nodes
    if not nodes:
      return
    self.v.set_draw_color(0)
    self.v.draw_box(0,220,400,20)
    self.v.set_draw_color(1)
    self.v.set_font('u8g2_font_profont15_mf')
    if self.search_active:
      prefix = 'I-search: '
      if self.search_failed:
        prefix = 'Fail I-search: '
      text = prefix + self.search_query + '  ^S next BS ^G'
      self.v.draw_str(4, 236, text[:39])
      self.draw_scale_slider()
      return
    node = nodes[self.selected]
    name = node['name']
    if not node['resolved']:
      name = '?' + name
    kids = len(self.loader.child_list(self.selected))
    text = name + '  kids:' + str(kids) + '  enter open  c center  q quit'
    self.v.draw_str(4, 236, text[:39])
    self.draw_scale_slider()

  def rect_overlap(self, a, b):
    if a[2] <= b[0] or b[2] <= a[0]:
      return False
    if a[3] <= b[1] or b[3] <= a[1]:
      return False
    return True

  def label_rect(self, x, y, w):
    return (x - 2, y - 11, x + w + 2, y + 2)

  def draw_label(self, x, y, text):
    v = self.v
    w = v.get_str_width(text)
    if w <= 0:
      return None
    tries = [
      (x + 8, y - 4),
      (x + 8, y + 12),
      (x - w - 8, y - 4),
      (x - w - 8, y + 12),
    ]
    for px, py in tries:
      if px < 4:
        px = 4
      if px + w > 396:
        px = 396 - w
      if py < 28:
        py = 28
      if py > 226:
        py = 226
      rect = self.label_rect(px, py, w)
      if rect[1] < 20 or rect[3] > 232:
        continue
      return (px, py, rect)
    return None

  def draw_bold_line(self, x1, y1, x2, y2):
    v = self.v
    v.draw_line(x1, y1, x2, y2)
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    if dx > dy:
      v.draw_line(x1, y1 - 1, x2, y2 - 1)
      v.draw_line(x1, y1 + 1, x2, y2 + 1)
    else:
      v.draw_line(x1 - 1, y1, x2 - 1, y2)
      v.draw_line(x1 + 1, y1, x2 + 1, y2)

  def node_half_size(self, idx):
    kids = self.loader.child_count(idx)
    half = 2 + ((kids + 1) // 2)
    if half > 8:
      half = 8
    nodes = self.loader.nodes
    if idx < len(nodes) and not nodes[idx]['resolved'] and half > 5:
      half -= 1
    if idx == 0 and half < 4:
      half = 4
    return half

  def node_frame_pad(self, idx):
    kids = self.loader.child_count(idx)
    if kids >= 9:
      return 5
    if kids >= 4:
      return 4
    return 3

  def draw_graph(self):
    v = self.v
    nodes = self.loader.nodes
    v.set_draw_color(1)
    v.set_dither(7)
    for a, b in self.loader.edges:
      if a >= len(nodes) or b >= len(nodes):
        continue
      x1 = self.sx(nodes[a]['x'])
      y1 = self.sy(nodes[a]['y'])
      x2 = self.sx(nodes[b]['x'])
      y2 = self.sy(nodes[b]['y'])
      if (x1 < -40 and x2 < -40) or (x1 > 440 and x2 > 440):
        continue
      if (y1 < 0 and y2 < 0) or (y1 > 260 and y2 > 260):
        continue
      v.draw_line(x1, y1, x2, y2)
    v.set_dither(16)
    if self.selected < len(nodes):
      for child in self.loader.child_list(self.selected):
        if child >= len(nodes):
          continue
        x1 = self.sx(nodes[self.selected]['x'])
        y1 = self.sy(nodes[self.selected]['y'])
        x2 = self.sx(nodes[child]['x'])
        y2 = self.sy(nodes[child]['y'])
        if (x1 < -40 and x2 < -40) or (x1 > 440 and x2 > 440):
          continue
        if (y1 < 0 and y2 < 0) or (y1 > 260 and y2 > 260):
          continue
        self.draw_bold_line(x1, y1, x2, y2)

    for i in range(len(nodes)):
      node = nodes[i]
      x = self.sx(node['x'])
      y = self.sy(node['y'])
      half = self.node_half_size(i)
      pad = self.node_frame_pad(i)
      if x < -12 - half or x > 412 + half or y < 8 - half or y > 252 + half:
        continue
      if i == 0 or i == self.selected:
        v.draw_box(x - half, y - half, half * 2 + 1, half * 2 + 1)
        v.draw_frame(
          x - half - pad,
          y - half - pad,
          (half + pad) * 2 + 1,
          (half + pad) * 2 + 1,
        )
      elif not node['resolved']:
        v.set_dither(6)
        v.draw_box(x - half, y - half, half * 2 + 1, half * 2 + 1)
        v.set_dither(16)
      else:
        v.draw_box(x - half, y - half, half * 2 + 1, half * 2 + 1)

    v.set_font('u8g2_font_profont15_mf')
    v.set_font('u8g2_font_profont15_mf')
    occupied = []
    candidates = []
    if self.selected < len(nodes):
      candidates.append(self.selected)
      for child in self.loader.child_list(self.selected):
        if child < len(nodes):
          candidates.append(child)

    seen = {}
    for idx in candidates:
      if idx in seen:
        continue
      seen[idx] = True
      node = nodes[idx]
      sx = self.sx(node['x'])
      sy = self.sy(node['y'])
      if sx < -24 or sx > 424 or sy < 18 or sy > 232:
        continue
      label = node['name']
      if not node['resolved']:
        label = '?' + label
      label = label[:18]
      placed = self.draw_label(sx, sy, label)
      if placed is None:
        continue
      px, py, rect = placed
      overlap = False
      if idx != self.selected:
        for old in occupied:
          if self.rect_overlap(rect, old):
            overlap = True
            break
      if overlap:
        continue
      v.set_draw_color(1)
      v.draw_box(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
      v.set_draw_color(0)
      v.draw_str(px, py, label)
      v.set_draw_color(1)
      occupied.append(rect)

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return
    self.frame += 1
    node_count = len(self.loader.nodes)
    edge_count = len(self.loader.edges)
    if node_count != self.last_node_count or edge_count != self.last_edge_count:
      self.last_node_count = node_count
      self.last_edge_count = edge_count
      self.disturb_layout()
      self.rebuild_layout_arrays()
      self.need_select = True
      if self.search_active and self.search_query:
        self.search_apply_query(True)
    if self.loader.done:
      if self.load_done_frame is None:
        self.load_done_frame = self.frame
    else:
      self.load_done_frame = None
    self.update_camera()
    self.layout_step()
    if (not self.search_active) and (self.need_select or (self.layout_active and not self.loader.done and (self.frame % 10) == 0)):
      self.choose_selected()
    self.v.set_font_mode(1)
    self.v.set_bitmap_mode(1)
    self.draw_graph()
    self.draw_header()
    self.draw_footer()
    self.v.finished()

  def read_key(self):
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

  def handle_key(self, k):
    if k is None:
      return
    if self.handle_search_key(k):
      return
    step = 24
    if k == b'q' or k == b'Q':
      self.running = False
    elif k == KEY_UP:
      self.pan_by(0, step)
    elif k == KEY_DOWN:
      self.pan_by(0, -step)
    elif k == KEY_LEFT:
      self.pan_by(step, 0)
    elif k == KEY_RIGHT:
      self.pan_by(-step, 0)
    elif k == b'+' or k == b'=':
      self.zoom_by(1.15)
    elif k == b'-' or k == b'_':
      self.zoom_by(1.0 / 1.15)
    elif k == b'0':
      self.reset_view()
    elif k == b'c' or k == b'C':
      self.center_on_selected()
    elif k == bytes([13]) or k == bytes([10]):
      self.open_selected_node()

  def handle_touchpad(self):
    try:
      keys = self.v.get_tp_keys()
      if not keys or len(keys) < 4:
        self.touch_last = None
        self.last_scale_slider = 255
        self.last_click_bits = 0
        return
      click_bits = keys[3] & 0x03
      if (click_bits & 1) and not (self.last_click_bits & 1):
        self.go_parent()
      if (click_bits & 2) and not (self.last_click_bits & 2):
        self.reroot_to_selected()
      self.last_click_bits = click_bits
      scale_raw = keys[0]
      if self.handle_scale_slider(scale_raw):
        self.touch_last = None
        return
      ty = keys[1]
      tx = keys[2]
      if tx == 0xFF or ty == 0xFF:
        self.touch_last = None
        return
      moved = False
      if self.touch_last is not None:
        dx = tx - self.touch_last[0]
        dy = ty - self.touch_last[1]
        if -50 < dx < 50 and -50 < dy < 50:
          self.target_cam_x += dx * 4.0
          self.target_cam_y += dy * 3.6
          if dx or dy:
            moved = True
      edge_dx = 0.0
      edge_dy = 0.0
      if tx < 6:
        edge_dx = -(6 - tx) * 2.2
      elif tx > 94:
        edge_dx = (tx - 94) * 2.2
      if ty < 6:
        edge_dy = -(6 - ty) * 2.0
      elif ty > 74:
        edge_dy = (ty - 74) * 2.0
      if edge_dx or edge_dy:
        self.target_cam_x += edge_dx
        self.target_cam_y += edge_dy
        moved = True
      self.touch_last = (tx, ty)
      if moved:
        if self.search_active:
          self.search_finish()
        self.animate_camera(100)
    except Exception:
      self.touch_last = None
      self.last_scale_slider = 255
      self.last_click_bits = 0

  def loop(self):
    self.v.callback(self.update)
    while self.running:
      k = self.read_key()
      self.handle_key(k)
      self.handle_touchpad()
      if not self.loader.done:
        #time.sleep_ms(30)
        self.loader.step(1)
      if not self.v.callback_exists():
        break
      if self.v.active:
        #pdeck.delay_tick(2)
        time.sleep_ms(20)
      else:
        pdeck.delay_tick(50)
    self.v.callback(None)


def run_test(vs, root, max_depth=None):
  loader = GraphLoader(
    root,
    max_nodes=120,
    max_edges=300,
    max_files=120,
    max_depth=max_depth,
  )
  while not loader.done:
    loader.step(4)
  print('root: ' + root, file=vs)
  if max_depth is None:
    print('depth: unlimited', file=vs)
  else:
    print('depth: ' + str(max_depth), file=vs)
  print('nodes: {} edges: {} files: {} queue: {}'.format(
    len(loader.nodes), len(loader.edges), loader.files_loaded, len(loader.queue)), file=vs)
  print('capped: {} errors: {}'.format(loader.capped, loader.errors), file=vs)
  for i in range(min(12, len(loader.nodes))):
    n = loader.nodes[i]
    print('{} {} {}'.format(i, 'R' if n['resolved'] else '?', n['name']), file=vs)


def normalize_cli_args(argv):
  out = []
  for a in argv:
    if a.startswith('-n='):
      out.append('-n')
      out.append(a[3:])
    elif a.startswith('--max-nodes='):
      out.append('--max-nodes')
      out.append(a[12:])
    elif a.startswith('--depth='):
      out.append('--depth')
      out.append(a[8:])
    else:
      out.append(a)
  return out


def main(vs, args):
  parser = argparse.ArgumentParser(vs=vs)
  parser.add_argument('root', nargs='?', default=None, help='root markdown file')
  parser.add_argument(
    '-n', '--max-nodes',
    type=int,
    default=90,
    help='maximum number of nodes to keep',
  )
  parser.add_argument(
    '--depth',
    type=int,
    default=None,
    help='maximum link depth to traverse (root depth is 0)',
  )
  parser.add_argument(
    '--test',
    action='store_true',
    help='run loader test instead of opening the UI',
  )

  try:
    ns = parser.parse_args(normalize_cli_args(args[1:]))
  except SystemExit:
    return

  if ns.depth is not None and ns.depth < 0:
    print('graph: --depth must be >= 0', file=vs)
    return

  root = resolve_root(ns.root)
  if ns.test:
    run_test(vs, root, max_depth=ns.depth)
    return

  v = vs.v
  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  app = GraphApp(vs, root, max_nodes=ns.max_nodes, max_depth=ns.depth)
  app.loop()
  v.print(el.display_mode(True))
  print('Graph finished.', file=vs)
