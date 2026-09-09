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

# Every Nth reconnect round falls back to scanning instead of a directed
# gap_connect, so a keyboard that woke up with a rotated address is found.
_SCAN_EVERY = 4
# After a resume-from-lightsleep, don't wait for _SCAN_EVERY failed rounds: if
# the directed gap_connect hasn't landed within this many seconds, scan too.
# The peer woke with us and may advertise a rotated RPA we can't direct-connect.
_RESUME_SCAN_S = 5

# First reconnect delay (seconds) when the link that just dropped had survived
# at least this long: the drop was peer-initiated (keyboard slept / reset), so
# its own link state is already clean and we can re-grab it almost at once.
_QUICK_RECONNECT_UP_S = 2

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
    self.fast_pending = False # fast path enabled notify; awaiting first report to validate
    self.fast_failed = False  # fast path tried and timed out -> use full discovery
    self.ready_at = 0         # when KB became ready (for fast-path validation)
    self.path = None          # "fast" (cached handles) or "full" (GATT discovery)
    self.opt_fast = False     # tried cached handles without confirmed encryption
    self.intercepted = False  # handles already registered with the C firmware
    self.prev_keys = set()
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
    self._scan_t = 0       # deadline at which an unfinished scan is declared lost
    self.connecting = 0    # number of pending connections
    self._recon_t = 0
    # addr_hex -> [[report_vh, cccd_vh], ...] cached from the saved-device
    # config ("h" key), used to skip GATT discovery on reconnection.
    self._handle_cache = {}
    for d in self._saved:
      if d.get("addr") and d.get("h"):
        self._handle_cache[d["addr"]] = d["h"]
    # Reconnect backoff (seconds). Starts at ~1.5s: many keyboards keep
    # advertising for a second or two after a drop while their own link layer
    # is still cleaning up — connecting into that window races the peer's
    # security procedures and causes connect-then-drop cycles. Doubles up to a
    # 3s ceiling on repeated failures. Reset on _CONNECT.
    self._recon_delay = 1.5
    # Consecutive failed reconnect rounds; every _SCAN_EVERY'th round we
    # scan instead of gap_connect'ing the saved address. Reset on _CONNECT.
    self._recon_fails = 0
    # After a resume, the time to fall back to scanning regardless of the
    # _SCAN_EVERY cadence (0 = not in a resume window). Set by _reset_ble.
    self._resume_scan_at = 0

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
        return json.load(f)
    except: return []

  def _save_cfg(self):
    try:
      try: os.mkdir("/config")
      except: pass
      with open(_CFG, "w") as f: json.dump(self._saved, f)
    except: pass

  # Keep only the few most recent addresses. Keyboards that sleep for a while
  # come back with a rotated resolvable-private address, so _saved would grow
  # forever — and since only ONE gap_connect can be in flight at a time,
  # reconnect_all's loop only ever gets an attempt out for the FIRST entry.
  # A stale address at the head would then permanently block reconnecting.
  _MAX_SAVED = 4

  def _add_device(self, addr_type, addr):
    h = bytes(addr).hex()
    for i, d in enumerate(self._saved):
      if d.get("addr") == h:
        if i:  # most-recently-used first
          self._saved.insert(0, self._saved.pop(i))
          self._save_cfg()
        return
    self._saved.insert(0, {"addr_type": addr_type, "addr": h})
    del self._saved[self._MAX_SAVED:]
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
      # _known holds every connected/connecting addr (watchdog below re-adds them)
      if ah not in self._known and self._match_kb(adv):
        self._known.add(ah)
        self.connecting += 1
        self._msg("Found KB")
        self._dbg(f"SCAN match addr={ah} type={addr_type} -> gap_connect")
        # Only one gap_connect can be in flight; if this raises (e.g. one is
        # already pending from reconnect_all) roll back the bookkeeping or
        # self.connecting stays elevated and blocks retries.
        try:
          self.ble.gap_connect(addr_type, addr)
        except Exception as e:
          self._dbg(f"gap_connect FAILED addr={ah}: {e}")
          self.connecting = max(0, self.connecting - 1)
          self._known.discard(ah)

    elif event == _SCAN_DONE:
      self.scanning = False
      self._scan_t = 0
      # Scan finished with nothing connected: retry reconnect soon, but not
      # instantly — the peer may still be cleaning up its own link state.
      if not self._conns:
        self._recon_t = time.time() + 1

    elif event == _CONNECT:
      ch, at, addr = data[0], data[1], data[2]
      ah = bytes(addr).hex()
      if ch in self._conns: return
      # The 4s watchdog clears self._known while a connect is still in flight;
      # accept the link anyway if we recognize the address (known or saved).
      # Only reject truly unknown peers — and tear the link down when we do,
      # otherwise it stays connected-but-unmanaged at the controller (a zombie
      # link that wedges all retries until a reboot).
      saved = any(d.get("addr") == ah for d in self._saved)
      if ah not in self._known and not saved:
        self.connecting = max(0, self.connecting - 1)
        self._dbg(f"CONNECT ch={ch} addr={ah} unexpected -> disconnect (zombie guard)")
        try: self.ble.gap_disconnect(ch)
        except: pass
        return
      self.connecting = max(0, self.connecting - 1)
      self._recon_delay = 1.5  # success -> restart backoff from the base delay
      self._recon_fails = 0
      self._resume_scan_at = 0  # resume fallback scan no longer needed
      # Check if this is a known/saved device
      is_new = not any(d.get('addr') == ah for d in self._saved)
      c = _Conn(ch, ah, is_new)
      if not is_new:
        # Reconnection grace period: give the keyboard ~2s to re-establish
        # encryption and finish its own cleanup before we touch security/GATT.
        # ENC_UPDATE cancels this deadline the instant encryption lands, so it
        # only bounds the wait when re-encryption is slow or silent. A short
        # grace (<1s) races the peer's security procs -> SMP collisions and
        # connect-then-drop cycles.
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
        # Untracked handle: NimBLE reports a failed gap_connect as a DISCONNECT
        # with conn_handle 0xffff and no address. Clear the in-flight
        # bookkeeping here — otherwise self.connecting and self._known stay
        # dirty until the 4s watchdog, which blocks every retry (and makes
        # _SCAN_RESULT ignore the address it is holding) for that whole window.
        self.connecting = max(0, self.connecting - 1)
        self._known = set(x.addr for x in self._conns.values())
        self._dbg(f"DISCONNECT ch={ch} (untracked -> connect attempt failed)")
      n = len(self._conns)
      if n == 0:
        try: pdeck.led(3, 0)
        except: pass
      # Show enough on-screen (even with DEBUG=False) to tell a clean drop from
      # the "connected then dropped before encryption" failure and see reconnect.
      self._msg(f"Disconnected ({n}), hit enter(A button) to scan. " +
                (f" enc={c.encrypted} up={time.time()-c.conn_at:.0f}s" if c else ""))
      # If the link had been up for a while before dropping, the peer
      # (keyboard) initiated the disconnect — its side is clean, so skip the
      # escalating backoff and try to grab it right away. Only freshly-
      # connected links that flapped need the conservative delay (those drops
      # race the peer's security cleanup, where a fast retry causes
      # connect-then-drop cycles).
      if c and time.time() - c.conn_at >= _QUICK_RECONNECT_UP_S:
        self._recon_delay = 0.2
      self._recon_t = time.time() + self._recon_delay
      # Failed reconnects escalate the delay; a successful _CONNECT resets it.
      self._recon_delay = min(self._recon_delay * 2, 3.0)

    elif event == _ENC_UPDATE:
      ch = data[0]
      c = self._conns.get(ch)
      # data = (conn_handle, encrypted, authenticated, bonded, key_size)
      enc = data[1] if len(data) > 1 else None
      self._dbg(f"ENC_UPDATE ch={ch} {tuple(data[1:])}", scr=True)
      if c and enc:
        c.encrypted = True
        # If an optimistic fast attempt is still pending, its CCCD writes were
        # rejected before encryption — now that the link is encrypted, re-run
        # the fast enable immediately (writes the cached CCCDs again).
        # _fast_enable releases the old C-side registration first so handles
        # are never double-registered.
        if c.ready and c.fast_pending:
          self._fast_enable(c)
        elif not c.discovering:
          c.disc_q = True
          c.disc_at = time.time()  # run discovery on the very next tick

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
        c.ready_at = time.time()
        self._save_handles(c)
        self._c_intercept(ch, c)
        try: pdeck.led(3, 5)
        except: pass
        c.path = "full"
        self._msg(f"KB ready [full disc {time.time()-c.conn_at:.1f}s]")
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
      matched = vh in c.reports
      self._dbg(f"NOTIFY ch={ch} vh={vh} matched={matched} data={bytes(nd).hex()}")
      if matched:
        c.fast_pending = False  # cached handles confirmed live
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
    if c.intercepted:
      # Re-registering (fast-path re-run after ENC_UPDATE): release first so
      # handles are never double-registered in the firmware.
      try: pdeck.ble_kb_release(ch)
      except: pass
    for rh, _ in c.cccds:
      pdeck.ble_kb_intercept(ch, rh)
    c.intercepted = True

  def _c_release(self, ch):
    # Drop the C-side registration and force-release any held keys. Safe to
    # call redundantly (firmware also does this on a real BLE disconnect).
    try: pdeck.ble_kb_release(ch)
    except: pass

  def _setup_active(self):
    # True while any link is still scanning/connecting/pairing/discovering.
    # The main loop uses this to tick fast during setup so each stage of the
    # connect state machine advances quickly; keypresses are IRQ-driven, so
    # this affects connection speed only, not key latency.
    return bool(self.scanning or self.connecting) or any(
      not c.ready for c in self._conns.values())

  def _disc_desc(self, c):
    vh = c.reports[c.desc_i]
    self.ble.gattc_discover_descriptors(c.ch, vh, vh + 3)

  def _fast_enable(self, c):
    # Skip full discovery on reconnection using cached GATT handles for this
    # address (BLE HID devices expose the same report/CCCD handles every
    # connection). Two writes vs several round-trips of service + char +
    # descriptor discovery. Returns True if the fast path was taken; if the
    # handles went stale the KB-ready timeout in the main loop falls back to
    # full discovery, so this can never be worse than the slow path.
    fh = self._handle_cache.get(c.addr)
    if not fh: return False
    c.reports = []
    c.cccds = []
    for rh, cd in fh:
      c.reports.append(rh)
      c.cccds.append((rh, cd))
    for rh, cd in c.cccds:
      self._dbg(f"FAST enable notify ch={c.ch} report_vh={rh} cccd={cd} (skipped discovery)")
      self.ble.gattc_write(c.ch, cd, b'\x01\x00')
    c.ready = True
    c.disc_q = False
    c.fast_pending = True     # validated once the first report arrives
    c.ready_at = time.time()
    self._save_handles(c)
    self._c_intercept(c.ch, c)
    try: pdeck.led(3, 5)
    except: pass
    c.path = "fast"
    self._msg(f"KB ready [cached handles {time.time()-c.conn_at:.1f}s]")
    self._dbg(f"KB ready (fast) ch={c.ch} encrypted={c.encrypted}", scr=True)
    return True

  def _save_handles(self, c):
    # Persist the working handles back into the saved-device entry.
    fh = [[rh, cd] for rh, cd in c.cccds]
    for d in self._saved:
      if d.get("addr") == c.addr:
        if d.get("h") != fh:
          d["h"] = fh
          self._save_cfg()
        break

  def _discover(self, c):
    if c.discovering: return
    # Fast path: known handles -> enable notify directly. Normally gated on
    # encryption, but many stacks re-encrypt a bonded link WITHOUT raising
    # ENC_UPDATE, so c.encrypted can stay False on a usable link. For a known
    # device we therefore try the cache optimistically once: the CCCD write on
    # an unencrypted link makes the keyboard raise a security request, which
    # triggers re-encryption with the stored bond key. If nothing arrives
    # within the validation window we fall back to pairing + discovery.
    if not c.fast_failed and self._handle_cache.get(c.addr) \
        and (c.encrypted or not c.opt_fast):
      if not c.encrypted:
        c.opt_fast = True
        self._dbg(f"OPTIMISTIC fast path ch={c.ch} (encrypted flag False; "
                  f"CCCD write should trigger security request)", scr=True)
      if self._fast_enable(c):
        return
    if not c.fast_failed:
      self._dbg(f"full discovery ch={c.ch} "
                f"(cache={'yes' if self._handle_cache.get(c.addr) else 'no'} "
                f"encrypted={c.encrypted} tried_opt={c.opt_fast})", scr=True)
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

  def scan(self, ms=30000):
    if self.scanning: return
    self._msg("Scanning...")
    self.scanning = True
    # If _SCAN_DONE never arrives (event lost while the IRQ handler raised, or
    # a radio hiccup), nothing else clears the flag — the scan fallback in the
    # reconnect logic would then never run again. Keep a deadline.
    self._scan_t = time.time() + ms / 1000 + 2
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
    self._scan_t = 0

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

  def _drop_links(self):
    # Cleanly tear down every live link (shared by resume and stop).
    self._stop_scan()
    for ch in list(self._conns):
      self._c_release(ch)
      try: self.ble.gap_disconnect(ch)
      except: pass

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
    self._drop_links()
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
    # The keyboard woke when the deck woke, so it is very likely advertising
    # right now — and possibly with a rotated RPA the directed gap_connect
    # can't reach. Don't wait out the _SCAN_EVERY failure cadence: also scan
    # if the direct connect hasn't landed within a few seconds.
    self._resume_scan_at = time.time() + _RESUME_SCAN_S

  def stop(self):
    self._drop_links()
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
  conn_t = time.time()

  # Start with both reconnect + scan
  if kb._saved:
    kb.reconnect_all()
  else:
    kb.scan(1500)
  kb._recon_t = time.time() + 3
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
      if key and key[0] > 0:
        # BS/Delete in the daemon's terminal quits cleanly (runs kb.stop(),
        # releasing links and the shared radio subscription).
        if key[1] in ('\x08', '\x7f'):
          kb._msg("Stopping (BS pressed)...")
          break
        if key[1] == '\r' and not kb.scanning:
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
          # If we're not encrypted yet, don't just wait: when we hold cached
          # handles the optimistic fast path (a CCCD write inside _discover)
          # makes the keyboard raise a security request, which re-encrypts
          # with the stored bond in a few hundred ms. Only without a cache
          # (new device / stale cache) do we gap_pair and wait for bonding.
          if not c.encrypted and not c.pair_tried \
              and not kb._handle_cache.get(c.addr):
            c.pair_tried = True
            kb._dbg(f"not encrypted, no cache -> gap_pair ch={c.ch}", scr=True)
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

        # Validate the fast path. With the C-side intercept active, HID
        # reports are parsed in firmware and NEVER raise a Python _NOTIFY IRQ
        # (verified: fast path always "times out" even when working). So
        # Python can't observe reports — trust the fast path when the link is
        # provably encrypted, and only act on silence when it isn't:
        # - encrypted + intercepted: leave it alone. If the link is actually
        #   dead, the keyboard drops it (DISCONNECT) and we reconnect fresh.
        # - encrypted but NOT intercepted (DEBUG/old firmware): silence here is
        #   real evidence of stale handles -> one quiet rediscovery (heals and
        #   refreshes the cache via _DSC_DONE). No gap_pair on an encrypted link.
        # - not encrypted: the optimistic write didn't trigger security ->
        #   one gap_pair (as the old stable code did), then discovery.
        if c.fast_pending and now > c.ready_at + 6:
          c.fast_pending = False
          if c.encrypted and c.intercepted:
            kb._dbg(f"fast-path 'silent' ch={c.ch}: expected (C intercept "
                    f"swallows _NOTIFY); trusting link, no action", scr=True)
          elif c.encrypted:
            c.fast_failed = True  # don't loop back into the fast path
            kb._dbg(f"fast-path silent 6s ch={c.ch} (no intercept) -> "
                    f"rediscover to heal handles", scr=True)
            kb._discover(c)
          elif not c.pair_tried:
            c.pair_tried = True
            kb._dbg(f"fast-path silent 6s ch={c.ch} NOT encrypted -> gap_pair "
                    f"(cache kept)", scr=True)
            try: kb.ble.gap_pair(c.ch)
            except: pass
            c.disc_q = True
            c.disc_at = now + 5
          else:
            c.fast_failed = True
            c.ready = False
            kb._dbg(f"fast-path exhausted ch={c.ch} -> full rediscovery "
                    f"(cache kept; corrected by _DSC_DONE if stale)", scr=True)
            kb._discover(c)

      # Watchdog: reset stuck connecting counter after 4s
      if kb.connecting > 0 and now - conn_t > 4:
        kb.connecting = 0
        kb._known.clear()
        for c in kb._conns.values():
          kb._known.add(c.addr)

      # Reconnect + scan together
      if kb._scan_t and now > kb._scan_t:
        # Scan deadline passed with no _SCAN_DONE: the event was lost.
        # Clear the flag so the scan fallback below can run again.
        kb._dbg("scan deadline exceeded -> clearing stale scanning flag", scr=True)
        kb.scanning = False
        kb._scan_t = 0
      if kb.connecting == 0 and now > kb._recon_t:
        if not kb._conns:
          # Directed reconnect to the saved address is the fast path, but a
          # keyboard that slept long enough rotates its resolvable-private
          # address and that address is then dead forever. So every few failed
          # rounds, scan instead: _match_kb picks the keyboard out by its HID
          # appearance/service whatever address it is wearing now. Right after
          # a resume we don't wait for the failure cadence either — if the
          # direct connect hasn't landed within _RESUME_SCAN_S the saved
          # address is almost certainly stale, so scan now.
          resume_scan = kb._resume_scan_at and now >= kb._resume_scan_at
          if kb._saved and not resume_scan and (kb._recon_fails + 1) % _SCAN_EVERY:
            kb._stop_scan()   # gap_connect and an active scan don't mix
            kb.reconnect_all()
            conn_t = now
          elif not kb.scanning:
            if resume_scan:
              kb._dbg("resume: directed connect missed within window -> scan", scr=True)
              kb._resume_scan_at = 0  # one scan fallback per resume
            kb.scan(1500)
          kb._recon_fails += 1
        # Schedule the next retry with the escalating backoff. A failed
        # gap_connect does NOT raise a DISCONNECT event (no link was ever
        # up), so escalation must happen here per attempt, not only in the
        # IRQ handler — otherwise retries stay on the slow fixed cadence.
        kb._recon_t = now + kb._recon_delay
        kb._recon_delay = min(kb._recon_delay * 2, 3.0)

      # Tick fast (~0.1s) while a link is still being set up so each stage
      # advances quickly. Once everything is ready, idle at 0.5s BUT wake
      # early if a timer (reconnect backoff, discovery retry, resume check)
      # is due within that window — so queued IRQ events like DISCONNECT or
      # ENC_UPDATE are acted on promptly without burning CPU when idle.
      if kb._setup_active():
        time.sleep(0.1)
      else:
        # next pending deadline among all connections
        deadlines = [c.disc_at for c in kb._conns.values() if c.disc_at > now]
        deadlines.append(kb._recon_t if kb._recon_t > now else now + 0.5)
        dl = min(deadlines)
        time.sleep(max(0.05, min(0.5, dl - now)))
  except KeyboardInterrupt:
    pass
  finally:
    kb.stop()
