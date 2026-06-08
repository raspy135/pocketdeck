import pdeck
import pdeck_utils as putils
import ujson
import time

try:
  with open('/config/startup.json') as f:
    config = ujson.loads(f.read())
except:
  config = {}

boot_app = config.get('boot_app', 'home')
ble_keyboard = config.get('ble_keyboard', False)
wifi_on_boot = config.get('wifi_on_boot', False)

if boot_app == 'editor':
  putils.launch(['pem'], 2)
  time.sleep(0.05)
  pdeck.change_screen(2)
else:
  putils.launch(['home'], 9)
  time.sleep(0.05)
  pdeck.change_screen(9)

if ble_keyboard:
  putils.launch(['ble_kb'], 8)

if wifi_on_boot:
  putils.launch(['wifi'], 7)

