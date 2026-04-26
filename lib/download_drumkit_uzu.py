import github_get as gh_get

file_list = [ "bd/11_bd_mot4i.wav", "sd/11_sd_switchangel_3.wav", "hh/11_hh_mot4i.wav" ]

drumkit_folder = "/sd/data/uzu-drumkit"

import os
import network

def check(vs):
  if check_download():
    print("Downloading drumkit", file=vs)
    s = network.WLAN(network.STA_IF)
    if not s.isconnected():
      print("Connect wifi", file=vs)
      os.rmdir(drumkit_folder)
      return False
    load_sample_from_web()
  return True

def check_download():
  try:
    os.mkdir(drumkit_folder)
    return True
  except:
    return False

def load_sample_from_web():
  base_url = "https://github.org/tidalcycles/uzu-drumkit/blob/main/"

  for file in file_list:
    gh_get.download_file(base_url + file, drumkit_folder)

  

