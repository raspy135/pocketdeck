import bluetooth
import struct
import time
import pdeck
import json
import os
from ble_manager import BLEManager

# IRQ constants
_SCAN_RESULT = 5
_SCAN_DONE = 6
_CONNECT = 7
_DISCONNECT = 8
_SVC_RESULT = 9
_SVC_DONE = 10
_CHR_RESULT = 11
_CHR_DONE = 12
_DSC_RESULT = 13
_DSC_DONE = 14
_NOTIFY = 18
_ENC_UPDATE = 28
_GET_SECRET = 29
_SET_SECRET = 30
_PASSKEY = 31

_CFG = "/config/ble_kb.json"
_SEC = "/config/ble_secrets.json"


class _Secrets:
  """Persist BLE bonding keys to JSON."""
  def __init__(self):
    self._d = {}
    try:
      os.stat(_SEC)
      with open(_SEC, "r") as f:
        self._d = json.load(f)
    except: pass

  def _save(self):
    try:
      try: os.mkdir("/config")
      except: pass
      with open(_SEC, "w") as f: json.dump(self._d, f)
    except: pass

  def set(self, sec_type, key, value):
    self._d[f"{sec_type}:{bytes(key).hex()}"] = bytes(value).hex()
    self._save()
    return True

  def get(self, sec_type, index, key):
    if key is None:
      m = [v for k, v in self._d.items() if k.startswith(f"{sec_type}:")]
      return bytes.fromhex(m[index]) if index < len(m) else None
    v = self._d.get(f"{sec_type}:{bytes(key).hex()}")
    return bytes.fromhex(v) if v else None

  def clear(self):
    self._d = {}
    try: os.remove(_SEC)
    except: pass


class _Conn:
  """Per-connection state for one keyboard."""
  def __init__(self, ch, addr_hex, is_new=False):
    self.ch = ch
    self.addr = addr_hex
    self.reports = []
    self.cccds = []
    self.hid = None
    self.desc_i = 0
    self.encrypted = False
    self.discovering = False
    self.ready = False
    self.pair_q = is_new      # Only pair for NEW devices, not reconnections
    self.disc_q = not is_new  # Reconnections: wait for enc, fallback to disc
    self.disc_at = 0
    self.prev_keys = set()
    self.prev_mod = 0


class BLEKeyboardHost:
  def __init__(self, v):
    self.mgr = BLEManager.get_instance()
    self.ble = self.mgr.get_ble()
    self.mgr.subscribe('ble_kb', self._irq)
    self.v = v
    self._sec = _Secrets()
    self._conns = {}       # conn_handle -> _Conn
    self._known = set()    # addr hex strings currently connected/connecting
    self._saved = self._load_cfg()  # list of {addr_type, addr}
    self.scanning = False
    self.connecting = 0    # number of pending connections
    self._recon_t = 0

  def _msg(self, s):
    try: self.v.print(f"{s}\n")
    except: pass

  def _load_cfg(self):
    try:
      os.stat(_CFG)
      with open(_CFG, "r") as f:
        d = json.load(f)
        # Migrate single-device config to list
        if isinstance(d, dict):
          return [d]
        return d
    except: return []

  def _save_cfg(self):
    try:
      try: os.mkdir("/config")
      except: pass
      with open(_CFG, "w") as f: json.dump(self._saved, f)
    except: pass

  def _add_device(self, addr_type, addr):
    h = bytes(addr).hex()
    for d in self._saved:
      if d.get("addr") == h: return
    self._saved.append({"addr_type": addr_type, "addr": h})
    self._save_cfg()

  def _irq(self, event, data):
    if event == _SET_SECRET:
      return self._sec.set(data[0], data[1], data[2])
    if event == _GET_SECRET:
      return self._sec.get(data[0], data[1], data[2])

    if event == _SCAN_RESULT:
      addr_type, addr, _, _, adv = data
      ah = bytes(addr).hex()
      # Skip only if already connected or actively connecting to this device
      already = any(c.addr == ah for c in self._conns.values())
      if not already and ah not in self._known and self._match_kb(adv):
        self._known.add(ah)
        self.connecting += 1
        self._msg("Found KB")
        self.ble.gap_connect(addr_type, addr)

    elif event == _SCAN_DONE:
      self.scanning = False

    elif event == _CONNECT:
      ch, at, addr = data[0], data[1], data[2]
      ah = bytes(addr).hex()
      if ah not in self._known:
        return
      
      if ch in self._conns: return
      self.connecting = max(0, self.connecting - 1)
      # Check if this is a known/saved device
      is_new = not any(d.get('addr') == ah for d in self._saved)
      c = _Conn(ch, ah, is_new)
      if not is_new:
        # Reconnection: give encryption 3s to restore, then fallback
        c.disc_at = time.time() + 3
      self._conns[ch] = c
      self._add_device(at, addr)
      n = len(self._conns)
      self._msg(f"Connected ({n})")

    elif event == _DISCONNECT:
      ch = data[0]
      c = self._conns.pop(ch, None)
      if c:
        self._known.discard(c.addr)
        was_ready = c.ready
      n = len(self._conns)
      if n == 0:
        try: pdeck.led(3, 0)
        except: pass
      self._msg(f"Disconnected ({n})")
      self._recon_t = time.time() + 2

    elif event == _ENC_UPDATE:
      ch = data[0]
      c = self._conns.get(ch)
      if c and data[1]:
        c.encrypted = True
        if not c.disc_q and not c.discovering:
          c.disc_q = True
          c.disc_at = time.time() + 0.5

    elif event == _PASSKEY:
      ch, act = data[0], data[1]
      if act == 4: self.ble.gap_passkey(ch, act, 1)
      elif act == 2: self.ble.gap_passkey(ch, act, 0)

    elif event == _SVC_RESULT:
      ch = data[0]
      c = self._conns.get(ch)
      if c and "1812" in str(data[3]).lower():
        c.hid = (data[1], data[2])

    elif event == _SVC_DONE:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      if c.hid:
        self.ble.gattc_discover_characteristics(ch, *c.hid)
      else:
        c.discovering = False
        if not c.encrypted:
          c.disc_q = True
          c.disc_at = time.time() + 3

    elif event == _CHR_RESULT:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      vh, props, uuid = data[2], data[3], data[4]
      if "2a4d" in str(uuid).lower() and (props & 0x10):
        c.reports.append(vh)

    elif event == _CHR_DONE:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      if c.reports:
        c.desc_i = 0
        self._disc_desc(c)

    elif event == _DSC_RESULT:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      h, uuid = data[1], data[2]
      if "2902" in str(uuid).lower():
        c.cccds.append((c.reports[c.desc_i], h))

    elif event == _DSC_DONE:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      c.desc_i += 1
      if c.desc_i < len(c.reports):
        self._disc_desc(c)
      elif c.cccds:
        for _, cccd_h in c.cccds:
          self.ble.gattc_write(ch, cccd_h, b'\x01\x00')
        c.ready = True
        try: pdeck.led(3, 5)
        except: pass
        self._msg("KB ready")

    elif event == _NOTIFY:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      vh, nd = data[1], data[2]
      if any(vh == r for r, _ in c.cccds) or vh in c.reports:
        self._on_report(c, nd)

  def _disc_desc(self, c):
    vh = c.reports[c.desc_i]
    self.ble.gattc_discover_descriptors(c.ch, vh, vh + 3)

  def _discover(self, c):
    if c.discovering: return
    c.discovering = True
    c.disc_q = False
    c.hid = None
    c.reports = []
    c.cccds = []
    c.desc_i = 0
    try: self.ble.gattc_discover_services(c.ch)
    except: c.discovering = False

  def _match_kb(self, adv):
    i = 0
    while i < len(adv):
      n = adv[i]
      if n == 0: break
      t = adv[i + 1]
      p = adv[i + 2: i + 1 + n]
      if t in (0x02, 0x03):
        for j in range(0, len(p), 2):
          if struct.unpack_from('<H', p, j)[0] == 0x1812: return True
      elif t == 0x19:
        if struct.unpack('<H', p)[0] == 961: return True
      i += n + 1
    return False

  def _on_report(self, c, rpt):
    if len(rpt) < 8: return
    d = rpt[1:9] if len(rpt) >= 9 and rpt[0] != 0 else rpt[:8]
    mod = d[0]
    keys = set(k for k in d[2:] if k)
    for k in c.prev_keys - keys:
      self.v.send_key_event(k, mod, 0)
    for k in keys - c.prev_keys:
      self.v.send_key_event(k, mod, 1)
    if mod and not keys:
      self.v.send_key_event(0, mod, 1)
    c.prev_keys = keys
    c.prev_mod = mod

  def scan(self, ms=30000):
    if self.scanning: return
    self._msg("Scanning...")
    self.scanning = True
    try:
      self.ble.gap_scan(None)
      self.ble.gap_scan(ms, 30000, 30000, True)
    except:
      self.scanning = False

  def _stop_scan(self):
    if not self.scanning: return
    try: self.ble.gap_scan(None)
    except: pass
    self.scanning = False

  def reconnect_all(self):
    for dev in self._saved:
      ah = dev.get("addr", "")
      if ah in self._known: continue
      self._known.add(ah)
      self.connecting += 1
      self._msg("Reconnecting...")
      try:
        self.ble.gap_connect(dev['addr_type'],
          bytes.fromhex(ah), 1000)
      except:
        self._known.discard(ah)
        self.connecting = max(0, self.connecting - 1)

  def stop(self):
    self._stop_scan()
    for ch in list(self._conns):
      try: self.ble.gap_disconnect(ch)
      except: pass
    self._msg("Keyboard service stopped (radio remains active for other services).")
    self.mgr.unsubscribe('ble_kb')


def main(vs, args):
  kb = BLEKeyboardHost(vs.v)
  fails = 0
  conn_t = time.time()

  # Start with both reconnect + scan
  if kb._saved:
    kb.reconnect_all()
  kb.scan(1500)
  kb._recon_t = time.time() + 3

  try:
    while True:
      now = time.time()

      # Per-connection: pair & discover
      for c in list(kb._conns.values()):
        if c.pair_q:
          c.pair_q = False
          try: kb.ble.gap_pair(c.ch)
          except:
            if not c.disc_q:
              c.disc_q = True
              c.disc_at = now + 3

        if c.disc_q and now >= c.disc_at:
          kb._discover(c)

        if c.discovering and not c.ready and now > c.disc_at + 10:
          c.discovering = False
          kb._discover(c)

      # Watchdog: reset stuck connecting counter after 4s
      if kb.connecting > 0 and now - conn_t > 4:
        kb.connecting = 0
        kb._known.clear()
        for c in kb._conns.values():
          kb._known.add(c.addr)

      # Reconnect + scan together
      if kb.connecting == 0 and now > kb._recon_t:
        #if not kb._conns and fails >= 1:
        #  kb._msg("Fresh pair...")
        #  try: os.remove(_CFG)
        #  except: pass
        #  kb._saved = []
        #  kb._sec.clear()
        #  kb._known.clear()
        #  fails = 0
        if not kb._conns:
          if kb._saved:
            kb.reconnect_all()
            conn_t = now
            fails += 1
          if not kb.scanning:
            kb.scan(1500)
        kb._recon_t = now + 3

      if any(c.ready for c in kb._conns.values()):
        fails = 0

      time.sleep(0.5)
  except KeyboardInterrupt:
    pass
  finally:
    kb.stop()
