import audio
from pie import Pie, PieWavetable, PieSampler, Pattern, PieRouter, PieCompressor
from codec_config import codec_config
import time

def main(vs, args):
    audio.sample_rate(24000)
    # 1. Initialize Pie and Wavetable
    # codec_config is handled by the base software
    p = Pie(bpm=120)
    
    # Creating a wavetable instrument with 4 oscillators
    sampler = PieSampler(4)
    synth = PieWavetable(4)
    
    with sampler, synth, PieRouter() as master, PieCompressor() as comp:
        print("Loading Serum wavetable...", file=vs)
        
        pat = Pattern("[0 <1 2>]*2")
        print(pat._data, file=vs)
        #return
        
        
        synth.load_wavetable(0, "/sd/data/wavetable/Instruments/ESW Real - World Japanese Guitar.wav", stride=4, max_frames=16)
        synth.copy_table(1,0)
        synth.copy_table(2,0)
        synth.copy_table(3,0)
        for i in range(0,3):
          synth.dev.volume(i,0.8)
          synth.dev.set_adsr(i,10,1300,0.05,400)
        
        print("Loading sampler instruments...", file=vs)
        sampler.load_wav(0, "/sd/data/samples/KMRBI_SJ_kick_one_shot_billington.wav")
        sampler.load_wav(1, '/sd/data/samples/MCS_snare_super_bright.wav')
        sampler.load_wav(2, '/sd/data/samples/TS_HP_hats_crispy.wav')
        print("Starting sequence...", file=vs)

        comp.detach()
        
        loc = {
         'p': p,
         'sampler' : sampler,
         'synth' : synth ,
         'master' : master,
         'comp' : comp,
        }
        with p:
          while True:
            p.process_event()
            try:
              p.process_interactive("/sd/work/int.py", loc)
            except Exception as e:
              print(f"Error in file {e}", file=vs)
            time.sleep(0.1)
            ret = vs.v.read_nb(1)
            if ret and ret[0] > 0:
              break
          



