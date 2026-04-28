import github_get as gh_get

file_list = [ "bd/11_bd_mot4i.wav", "sd/11_sd_switchangel_3.wav", "hh/11_hh_mot4i.wav" ]

import os
def load_sample_from_web(force = False):
  drumkit_folder = "/sd/data/uzu-drumkit"
  try:
    os.mkdir(drumkit_folder)
  except:
    if not force:
      # Directly exists means it has data
      return
  base_url = "https://github.org/tidalcycles/uzu-drumkit/blob/main/"

  for file in file_list:
    gh_get.download_file(base_url + file, drumkit_folder)

  

