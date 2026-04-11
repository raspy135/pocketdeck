import pdeck
import fontloader
def main(vs, args):
  fontname = 'font_unifont_japanese3'
  fontloader.load(fontname)
  
  font = fontloader.font_list[fontname]
  vs.v.set_terminal_font(font,font,8,16)
  
