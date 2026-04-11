import bluetooth
import sys
import micropython

class BLEManager:
  _instance = None
  
  @classmethod
  def get_instance(cls):
    if cls._instance is None:
      cls._instance = cls()
    return cls._instance

  def __init__(self):
    if BLEManager._instance is not None:
      raise Exception("BLEManager is a singleton! Use get_instance().")
    self.ble = bluetooth.BLE()
    self.ble.active(True)
    # Common config for Pocket Deck
    try:
      self.ble.config(gap_name='PocketDeck', bond=True, mitm=False, le_secure=False, io=4)
    except:
      pass
    self.subscribers = {}
    self.ble.irq(self._irq)
      
  def _irq(self, event, data):
    # Synchronous dispatch (scheduled dispatch was causing device resets)
    for sub in self.subscribers:
      try:
        self.subscribers[sub](event, data)
      except Exception as e:
        print(f"[BLE_MGR] Sub Error: {e}")
        sys.print_exception(e)
              
  def subscribe(self, key, callback):
    if callback not in self.subscribers:
      self.subscribers[key] = callback
      print(f"[BLE_MGR] New Subscriber. Total: {len(self.subscribers)}")
          
  def unsubscribe(self, key):
    del self.subscribers[key]
    print(f"[BLE_MGR] Subscriber Removed. Total: {len(self.subscribers)}")
      
  def get_ble(self):
    return self.ble
