
font_list = {}
def load(path):
  if not path in font_list:
    f = open(f'/sd/font/{path}.fnt','rb')
    font_list[path] = f.read()
    f.close()


