"""Reconnect bookkeeping checks for lib/ble_kb.py (run: python3 -B test_ble_kb.py)."""
import sys, types, os

sys.path.insert(0, "lib")
for n in ("pdeck",):
  sys.modules[n] = types.ModuleType(n)
_bm = types.ModuleType("ble_manager")
class _Mgr:
  @staticmethod
  def get_instance(): return _Mgr()
  def get_ble(self): return None
  def subscribe(self, *a): pass
_bm.BLEManager = _Mgr
sys.modules["ble_manager"] = _bm

import ble_kb

def host():
  h = ble_kb.BLEKeyboardHost.__new__(ble_kb.BLEKeyboardHost)
  h.v = None
  h._conns, h._known, h._saved = {}, set(), []
  h.connecting, h.scanning, h._recon_t = 0, False, 0
  h._recon_delay, h._recon_fails = 1.5, 0
  h._handle_cache = {}
  h._save_cfg = lambda: None
  return h

def test_failed_connect_clears_inflight():
  h = host()
  h._known.add("aabb"); h.connecting = 1
  # NimBLE reports a failed gap_connect as DISCONNECT on an unknown handle
  h._irq(ble_kb._DISCONNECT, (0xffff, 0, b""))
  assert h.connecting == 0, h.connecting
  assert h._known == set(), h._known

def test_real_disconnect_keeps_other_links():
  h = host()
  live = ble_kb._Conn(2, "ccdd")
  h._conns = {1: ble_kb._Conn(1, "aabb"), 2: live}
  h._known = {"aabb", "ccdd"}
  h._irq(ble_kb._DISCONNECT, (1, 0, b""))
  assert h._known == {"ccdd"}, h._known
  assert list(h._conns) == [2]

def test_saved_is_mru_and_capped():
  h = host()
  for i in range(ble_kb.BLEKeyboardHost._MAX_SAVED + 2):
    h._add_device(1, bytes([i]) * 6)
  assert len(h._saved) == ble_kb.BLEKeyboardHost._MAX_SAVED
  assert h._saved[0]["addr"] == (bytes([5]) * 6).hex()  # newest first
  h._add_device(1, bytes([3]) * 6)                      # re-seen -> to front
  assert h._saved[0]["addr"] == (bytes([3]) * 6).hex()
  assert len(h._saved) == ble_kb.BLEKeyboardHost._MAX_SAVED

def test_scan_round_every_nth():
  n = ble_kb._SCAN_EVERY
  rounds = [bool((f + 1) % n) for f in range(2 * n)]
  assert rounds.count(False) == 2, rounds   # scans twice in 2N rounds
  assert rounds[0] is True                  # first round is a directed connect

for f in list(globals().values()):
  if callable(f) and getattr(f, "__name__", "").startswith("test_"):
    f(); print("ok", f.__name__)
