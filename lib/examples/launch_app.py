import pdeck
import time
import pdeck_utils as pd
def main(vs, args):
  pd.launch(['gpt','-i',
    'http://cdip.ucsd.edu/recent/forecast/buoy_ww3.gd?stn=071&stream=p1&pub=public&tz=PDT&units=english','"The images is wave height. Give me a forecast for surfing next a few days. Focus today and the imcoming dates. Check today\'s date by yourself"'],-1)

