import esp32
import os
import network
import github_get

def _print(vs, text):
  vs.write(text + "\n")

def update_updater_partition(vs, bin_file):
  _print(vs, f"Opening {bin_file}...")
  try:
    total_size = os.stat(bin_file)[6]
  except OSError:
    _print(vs, f"Error: Could not open {bin_file}")
    return False

  partitions = esp32.Partition.find(esp32.Partition.TYPE_APP, label="updater")
  if not partitions:
    _print(vs, "Error: Could not find 'updater' partition!")
    return False
      
  p = partitions[0]
  
  _print(vs, f"Found Partition: {p.info()[4]} at offset {hex(p.info()[2])}")
  _print(vs, f"Binary size: {total_size} bytes")
  
  BLOCK_SIZE = 4096
  total_blocks = (total_size + BLOCK_SIZE - 1) // BLOCK_SIZE
  
  _print(vs, f"Erasing and writing {total_blocks} blocks...")
  
  with open(bin_file, "rb") as f:
    for block_num in range(total_blocks):
      chunk = f.read(BLOCK_SIZE)
      
      if len(chunk) < BLOCK_SIZE:
        chunk += b'\xff' * (BLOCK_SIZE - len(chunk))
          
      p.writeblocks(block_num, chunk)
      
      if block_num % max(1, (total_blocks // 10)) == 0 or block_num == total_blocks - 1:
        _print(vs, f"Progress: {(block_num / total_blocks) * 100:.1f}%")
              
  _print(vs, "Flash complete!")
  return True

def download_updater_bin(vs):
  station = network.WLAN(network.STA_IF)
  if not station.isconnected():
    print("WiFi is not connected.", file=vs)
    return False

  print("Downloading the latest firmware", file=vs)

  github_get.download_file("https://github.com/raspy135/pocketdeck/blob/main/firmware/updater.bin","/sd")
  os.sync()
  return True

def main(vs, args):
  if len(args) != 2 or args[1] != '-f':
    print("This operation might break firmware updater and it could cause permanent damage to the device. Execute with '-f' option to proceed", file=vs)
    return

  bin_file = "/sd/updater.bin"
  if not download_updater_bin(vs):
    return
  update_updater_partition(vs, bin_file)
