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
  app, screen = 'pem', 2
else:
  app, screen = 'home', 9

putils.launch([app], screen)

# Keep the boot splash (screen 100) up until the launched app is actually live,
# then switch to it so there is no blank frame in between. cmd_exists() flips
# true as soon as the app registers. Bail out after a timeout so boot always
# completes even if the app fails to start.
deadline = time.ticks_add(time.ticks_ms(), 4000)
while not pdeck.cmd_exists(screen) and time.ticks_diff(deadline, time.ticks_ms()) > 0:
  pdeck.delay_tick(4)
pdeck.change_screen(screen)

if ble_keyboard:
  putils.launch(['ble_kb'], 8)

if wifi_on_boot:
  putils.launch(['wifi'], 7)
