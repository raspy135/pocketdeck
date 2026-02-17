import audio
from pie import Pie, PieWavetable, PieReverb, PieRouter, PieCompressor
import time

def main(vs, args):
    print("Initializing Audio Engine...", file=vs)
    audio.sample_rate(24000)
    #audio.sample_rate(32000)
    #audio.sample_rate(48000)
    #audio.sample_rate(44100)
    
    # Initialize Pie Sequencer
    p = Pie(bpm=120)

    # 1. Create Modules
    master = PieRouter()
    rev = PieReverb()
    wv = PieWavetable(4)
    comp = PieCompressor()
        
    with master,  wv,rev, comp:

        #rev.detach()
        comp.detach()
        # 2. Setup Signal Chain
        master.clear()
        master.add(wv)  
        master.add(rev) 
        master.add(comp)
        comp.set_params(1.2, 2.0)
        frames = wv.load_wavetable(0, "/sd/data/wavetable/Instruments/ESW Real - World Japanese Guitar.wav", stride=8, max_frames=32)
        #frames = wv.load_wavetable(0, "/sd/data/piano_a2.wav", stride=1, max_frames=64, frame_size = 256)
        print(f"{frames} frames", file=vs)
        wv.morph(0,0)
        wv.copy_table(1,0)
        wv.copy_table(2,0)
        wv.copy_table(3,0)
        for i in range(4):
          wv.dev.volume(i,0.76)
          wv.dev.set_adsr(i,1000,1300,1,4400)
          wv.dev.morph_start(i,0.8)
          wv.dev.morph(i,0.1)
          wv.dev.morph_adsr(i,10,3300,0,4400)
          wv.dev.morph_adsr_enable(i,True)
        # 3. Configure Reverb
        rev.set_params(room_size=0.50, brightness=0.7, predelay_ms=215.0, transition_ms=0, mix=0.4)

        print("Starting Reverb Test...", file=vs)
        # Play a test pattern
        # A Major scale arpeggio
        p.add(wv, "<<c3 a2> d2min7 c#2min g#2sev>/2")
        #p.add(wv, "<mrp_:1:2000 mrp_:0:2000>/2")
        
        # Automate Reverb parameters via pattern
        # Change room size every bar: Small -> HUGE
        #p.add(rev, "<room:0.02:0 room:0.545:0>")

        rev.dev.active(True)
        comp.dev.active(True)
                
        with p:
            while True:
                p.process_event()
                time.sleep(0.1)
                
                ret = vs.v.read_nb(1)
                if ret and ret[0] > 0:
                    break
                    

