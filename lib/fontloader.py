import os

def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

font_list = {}
def load(path):
  if not path in font_list:
    filenames = [
    f'/sd/font/{path}.fnt',
    f'/sd/lib/font/{path}.fnt']
    filename = None
    for item in filenames:
      if file_exists(item):
        filename = item
        break
    if not filename:
      return False

    info = os.stat(filename)
    f = open(filename,'rb')
    font_list[path] = bytearray(info[6]+10)
    f.readinto(font_list[path])
    f.close()
    return True

