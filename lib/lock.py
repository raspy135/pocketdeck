import pdeck

# lock [pin]
#   lock 0912   -> set the PIN to 0912 and lock the device
#   lock        -> lock using the already-stored PIN
# When locked, the display asks for the PIN. Enter it with the USB keyboard or
# the touchpad (3x3 numpad: top 789 / mid 456 / bottom 123, bottom-left = 0,
# A = enter, B = backspace).

def main(vs, args):
  pin = args[1] if len(args) > 1 else None
  try:
    if pin is not None:
      pdeck.lock(pin)
    else:
      pdeck.lock()
  except ValueError as e:
    print(f'lock: {e}', file=vs)
    return
