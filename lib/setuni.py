import pdeck
import fontloader
def main(vs, args):
  fontname = 'unifont_large'
  fontloader.load(fontname)
  
  font = fontloader.font_list[fontname]
  vs.v.set_terminal_font(font,font,8,16)
  
