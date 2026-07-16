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

# Loop gap (seconds) above which we assume the device resumed from lightsleep
# and must drop the stale links and reconnect. Kept well above the few-second
# stall a large .py compile causes: a compile freezes this loop but leaves the
# links up, so reconnecting there would needlessly disconnect a live keyboard.
# Real lightsleep-away gaps are much longer.
_RESUME_GAP_S = 10

# Set DEBUG = True to trace the BLE connect/pair/discover/notify flow.
# Detailed traces go to the serial REPL via print(); milestones also show
# on the device screen. Watch the serial console while pairing a new KB.
DEBUG = False


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
    self.pair_tried = is_new  # new devices pair via pair_q; known ones may re-pair
    self.disc_at = 0
    self.prev_keys = set()
    self.prev_mod = 0
    self.conn_at = time.time()  # for measuring how long a link survives


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

  def _dbg(self, s, scr=False):
    # Verbose trace: always to serial REPL, optionally echoed on screen.
    if not DEBUG: return
    try: print("[ble_kb]", s)
    except: pass
    if scr:
      try: self.v.print(f". {s}\n")
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
      self._dbg(f"SET_SECRET type={data[0]} key={bytes(data[1]).hex() if data[1] else None}")
      return self._sec.set(data[0], data[1], data[2])
    if event == _GET_SECRET:
      r = self._sec.get(data[0], data[1], data[2])
      self._dbg(f"GET_SECRET type={data[0]} idx={data[1]} -> {'HIT' if r else 'MISS'}")
      return r

    if event == _SCAN_RESULT:
      addr_type, addr, _, _, adv = data
      ah = bytes(addr).hex()
      # Skip only if already connected or actively connecting to this device
      already = any(c.addr == ah for c in self._conns.values())
      if not already and ah not in self._known and self._match_kb(adv):
        self._known.add(ah)
        self.connecting += 1
        self._msg("Found KB")
        self._dbg(f"SCAN match addr={ah} type={addr_type} -> gap_connect")
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
        # Reconnection: give encryption time to restore, then fall back to
        # discovery. The happy path is faster — ENC_UPDATE re-queues discovery
        # at +0.5s the moment encryption restores; this only bounds the wait
        # when re-encryption is slow or silent.
        c.disc_at = time.time() + 2
      self._conns[ch] = c
      self._add_device(at, addr)
      n = len(self._conns)
      self._msg(f"Connected ({n})")
      self._dbg(f"CONNECT ch={ch} addr={ah} is_new={is_new} "
                f"(new->will pair, known->wait for enc)")

    elif event == _DISCONNECT:
      ch = data[0]
      self._c_release(ch)
      c = self._conns.pop(ch, None)
      if c:
        self._known.discard(c.addr)
        was_ready = c.ready
        # reason code, if this MicroPython build exposes it
        reason = data[3] if len(data) > 3 else None
        self._dbg(f"DISCONNECT ch={ch} addr={c.addr} after={time.time()-c.conn_at:.1f}s "
                  f"encrypted={c.encrypted} ready={c.ready} discovering={c.discovering} "
                  f"reason={reason}", scr=True)
        if not c.encrypted:
          self._dbg("  -> dropped BEFORE encryption: pairing/bonding failed. "
                    "Try clearing the bond on both sides (see notes).", scr=True)
      else:
        self._dbg(f"DISCONNECT ch={ch} (untracked)")
      n = len(self._conns)
      if n == 0:
        try: pdeck.led(3, 0)
        except: pass
      # Show enough on-screen (even with DEBUG=False) to tell a clean drop from
      # the "connected then dropped before encryption" failure and see reconnect.
      if c:
        self._msg(f"Disconnected ({n}) enc={c.encrypted} up={time.time()-c.conn_at:.0f}s")
      else:
        self._msg(f"Disconnected ({n})")
      self._recon_t = time.time() + 2

    elif event == _ENC_UPDATE:
      ch = data[0]
      c = self._conns.get(ch)
      # data = (conn_handle, encrypted, authenticated, bonded, key_size)
      enc = data[1] if len(data) > 1 else None
      auth = data[2] if len(data) > 2 else None
      bonded = data[3] if len(data) > 3 else None
      ksz = data[4] if len(data) > 4 else None
      self._dbg(f"ENC_UPDATE ch={ch} encrypted={enc} authenticated={auth} "
                f"bonded={bonded} key_size={ksz}", scr=True)
      if c and enc:
        c.encrypted = True
        if not c.disc_q and not c.discovering:
          c.disc_q = True
          c.disc_at = time.time() + 0.5

    elif event == _PASSKEY:
      ch, act = data[0], data[1]
      self._dbg(f"PASSKEY ch={ch} action={act} "
                f"(4=numcmp confirm, 2=passkey entry)", scr=True)
      if act == 4: self.ble.gap_passkey(ch, act, 1)
      elif act == 2: self.ble.gap_passkey(ch, act, 0)

    elif event == _SVC_RESULT:
      ch = data[0]
      c = self._conns.get(ch)
      if c and "1812" in str(data[3]).lower():
        c.hid = (data[1], data[2])
        self._dbg(f"SVC found HID(0x1812) ch={ch} range={data[1]}-{data[2]}")

    elif event == _SVC_DONE:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      if c.hid:
        self._dbg(f"SVC_DONE ch={ch} -> discover HID characteristics")
        self.ble.gattc_discover_characteristics(ch, *c.hid)
      else:
        self._dbg(f"SVC_DONE ch={ch} NO HID service found "
                  f"(encrypted={c.encrypted}); will retry", scr=True)
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
        self._dbg(f"CHR report(0x2A4D,notify) ch={ch} value_handle={vh}")

    elif event == _CHR_DONE:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      self._dbg(f"CHR_DONE ch={ch} report_chars={len(c.reports)}")
      if c.reports:
        c.desc_i = 0
        self._disc_desc(c)
      else:
        self._dbg("  -> no notifiable input-report chars found", scr=True)

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
        for rh, cccd_h in c.cccds:
          self._dbg(f"CCCD write ch={ch} report_vh={rh} cccd_handle={cccd_h} <- 0100")
          self.ble.gattc_write(ch, cccd_h, b'\x01\x00')
        c.ready = True
        self._c_intercept(ch, c)
        try: pdeck.led(3, 5)
        except: pass
        self._msg("KB ready")
        self._dbg(f"KB ready ch={ch} notify-handles={[r for r,_ in c.cccds]} "
                  f"encrypted={c.encrypted} (press keys now)", scr=True)
      else:
        self._dbg(f"DSC_DONE ch={ch} no CCCD(0x2902) descriptors found -> "
                  f"cannot enable notifications", scr=True)

    elif event == _NOTIFY:
      ch = data[0]
      c = self._conns.get(ch)
      if not c: return
      vh, nd = data[1], data[2]
      matched = any(vh == r for r, _ in c.cccds) or vh in c.reports
      self._dbg(f"NOTIFY ch={ch} vh={vh} matched={matched} data={bytes(nd).hex()}")
      if matched:
        self._on_report(c, nd)

  def _c_intercept(self, ch, c):
    # Firmware fast path: register this keyboard's report handles so C parses
    # the notifications on the NimBLE host task. The Python _NOTIFY IRQ waits
    # for the GIL, so a gc pause or long import delayed key releases — the
    # firmware's 1s auto-repeat then flooded the held key (e.g. the phantom
    # C-s search storm in pem) and the blocked host task could even drop the
    # link by supervision timeout. Skipped when DEBUG so _on_report tracing
    # still sees every report; also skipped (hasattr) on older firmware,
    # where _on_report keeps handling reports as before.
    if DEBUG or not hasattr(pdeck, 'ble_kb_intercept'):
      return
    for rh, _ in c.cccds:
      pdeck.ble_kb_intercept(ch, rh)

  def _c_release(self, ch):
    # Drop the C-side registration and force-release any held keys. Safe to
    # call redundantly (firmware also does this on a real BLE disconnect).
    if hasattr(pdeck, 'ble_kb_release'):
      try: pdeck.ble_kb_release(ch)
      except: pass

  def _setup_active(self):
    # True while any link is still scanning/connecting/pairing/discovering.
    # The main loop uses this to tick fast during setup so each stage of the
    # connect state machine advances quickly; keypresses are IRQ-driven, so
    # this affects connection speed only, not key latency.
    if self.scanning or self.connecting:
      return True
    for c in self._conns.values():
      if not c.ready:
        return True
    return False

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
    if len(rpt) < 8:
      self._dbg(f"report ignored: len={len(rpt)} < 8 data={bytes(rpt).hex()}")
      return
    d = rpt[1:9] if len(rpt) >= 9 and rpt[0] != 0 else rpt[:8]
    mod = d[0]
    keys = set(k for k in d[2:] if k)
    self._dbg(f"report mod={mod:#04x} keys={sorted(keys)}")
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

  def _reset_ble(self):
    # Called on resume from lightsleep. lightsleep powers down the radio, so the
    # links are dead — but the controller itself comes back fine (restarting the
    # app reconnects without ever re-initializing it). So we replicate exactly
    # what the app-restart path does: cleanly disconnect the stale handles (as
    # stop() does), drop per-connection state, then reconnect.
    #
    # We deliberately do NOT cycle the shared radio (mgr.reset() ->
    # active(False)/active(True)): that re-inits the NimBLE host and wipes its
    # in-RAM security state, which left the fresh link connecting and then
    # immediately dropping during re-encryption ("connected then disconnected").
    # It would also tear down other services' links on the SHARED radio.
    self._msg("Resume: reconnecting KB...")
    self._stop_scan()
    for ch in list(self._conns):
      self._c_release(ch)
      try: self.ble.gap_disconnect(ch)
      except: pass
    self._conns.clear()
    self._known.clear()
    self.connecting = 0
    self.scanning = False
    try: pdeck.led(3, 0)
    except: pass
    if self._saved:
      self.reconnect_all()
    else:
      self.scan(1500)

  def stop(self):
    self._stop_scan()
    for ch in list(self._conns):
      self._c_release(ch)
      try: self.ble.gap_disconnect(ch)
      except: pass
    self._msg("Keyboard service stopped (radio remains active for other services).")
    self.mgr.unsubscribe('ble_kb')


def main(vs, args):
  # -r : reset — delete saved device + bond keys before starting, so the next
  # connection pairs from scratch. Must run before the host loads the config.
  if len(args) > 1 and "-r" in args[1:]:
    n = 0
    for path in (_CFG, _SEC):
      try:
        os.remove(path)
        n += 1
      except: pass
    try: vs.v.print(f"Reset: cleared {n} config file(s)\n")
    except: pass

  kb = BLEKeyboardHost(vs.v)
  fails = 0
  conn_t = time.time()

  # Start with both reconnect + scan
  if kb._saved:
    kb.reconnect_all()
  else:
    kb.scan(1500)
  kb._recon_t = time.time() + 3
  req_scan = False
  last_tick = time.time()
  try:
    while True:
      now = time.time()
      # Resume-from-lightsleep detection: the loop is normally paced by the
      # ~0.5s sleep below, so a gap of several seconds means the device slept.
      # lightsleep powers down the radio, leaving any bonded link dead. Drop the
      # stale handles and reconnect from a clean slate instead of limping on
      # links the controller no longer has.
      if now - last_tick > _RESUME_GAP_S:
        kb._dbg(f"resume after {now - last_tick:.0f}s idle -> drop stale links + reconnect",
                scr=True)
        kb._reset_ble()
        conn_t = now
        kb._recon_t = now + 1
      last_tick = now
      key = vs.v.read_nb(1)
      if key and key[0] > 0 and key[1].encode('ascii') == b'\x0d':
        req_scan = True
      if req_scan and not kb.scanning:
        kb.scan(1500)
        
      # Per-connection: pair & discover
      for c in list(kb._conns.values()):
        if c.pair_q:
          c.pair_q = False
          kb._dbg(f"gap_pair ch={c.ch} (new device -> initiate bonding)")
          try: kb.ble.gap_pair(c.ch)
          except Exception as e:
            kb._dbg(f"gap_pair FAILED ch={c.ch}: {e} -> fall back to discovery", scr=True)
            if not c.disc_q:
              c.disc_q = True
              c.disc_at = now + 3

        if c.disc_q and now >= c.disc_at:
          # HID-over-GATT gates keypress notifications behind link encryption.
          # If we're not encrypted yet, (re)initiate bonding before discovery
          # instead of falsely reporting "KB ready" on a link that won't deliver
          # reports. ENC_UPDATE re-queues discovery once encryption succeeds.
          if not c.encrypted and not c.pair_tried:
            c.pair_tried = True
            kb._dbg(f"not encrypted at discover -> gap_pair ch={c.ch}", scr=True)
            try:
              kb.ble.gap_pair(c.ch)
              c.disc_at = now + 5   # give bonding time; fall back after if silent
            except Exception as e:
              kb._dbg(f"gap_pair failed ch={c.ch}: {e} -> discover unencrypted", scr=True)
              kb._discover(c)
          else:
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
          else:
            if not kb.scanning:
              kb.scan(1500)
        kb._recon_t = now + 3

      if any(c.ready for c in kb._conns.values()):
        fails = 0

      # Tick fast (~0.1s) while a link is still being set up so each stage
      # advances quickly; idle slowly (0.5s) once every keyboard is ready.
      # The >_RESUME_GAP_S sleep-detection above stays valid: at idle the loop
      # still ticks every 0.5s, far below the gap threshold.
      time.sleep(0.1 if kb._setup_active() else 0.5)
  except KeyboardInterrupt:
    pass
  finally:
    kb.stop()
