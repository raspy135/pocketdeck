import os

font_list = {}
def load(path):
  if not path in font_list:
    filename = f'/sd/font/{path}.fnt'
    info = os.stat(filename)
    f = open(f'/sd/font/{path}.fnt','rb')
    font_list[path] = bytearray(info[6]+10)
    f.readinto(font_list[path])
    f.close()


