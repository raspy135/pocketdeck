import audio
from pie import Pie, PieWavetable, PieReverb, PieRouter, PieCompressor
import time

def check_cycle(p_obj, repeatuntil):
  cur_cycle = p_obj.playing_cycle
  if cur_cycle >= repeatuntil-1.5:
    return False
  return True


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
  wv = PieWavetable(6)
  comp = PieCompressor()
    
  with master,  wv, rev, comp:

    # 2. Setup Signal Chain
    master.clear()
    master.add(wv)  
    master.add(rev) 
    master.add(comp)
    comp.set_params(1.2, 2.0)

    #frames = wv.load_wavetable(0, "/sd/data/square.wav", stride=2, max_frames=32, frame_size = 256)
    frames = wv.load_wavetable(0, "/sd/data/guitar_wt.wav", stride=5, max_frames=32, frame_size = 256)
    print(f"{frames} frames", file=vs)
    wv.morph(0,0)
    for i in range(5):
      wv.copy_table(i+1,0)
    for i in range(6):
      wv.dev.volume(i,0.16)
      wv.dev.set_adsr(i,10,2000,0.01,1000)
      wv.dev.morph_adsr(i,0,4400,0.1,1000)
      wv.dev.morph_start(i,1)
      wv.dev.morph(i,0)
      wv.dev.morph_adsr_enable(i,True)
    # 3. Configure Reverb
    rev.set_params(room_size=0.10, brightness=0.3, predelay_ms=115.0, transition_ms=0, mix=0.4)

    print("Starting Test...", file=vs)
    
    patterns = []
    
    patterns.append(['Strum', p.pattern(wv, "<[a2, c3, e3, g3]*2 [D2m7]*2 [e2m7]*2 [g27:-1]*2>").strum(0.02)])
    
    #patterns.append(['Scale with Clip',p.pattern(wv, "0 1 2 3").scale("Ebmaj").clip("0.2 1.0").transpose(-7)])
    
    #patterns.append(['Scale and transpose', p.pattern(wv, "<[0 4] [3 2] [1 .] [3 . . .]>").scale("Cmajor").transpose(-7)])

    #patterns.append(['Chord interval with transpose',p.pattern(wv, "<[0,3,7] [0,4,7]>").transpose("<48 53>")])
    
    #patterns.append(['Manual voicing', p.pattern(wv, "<[0,3,7] [7,12,16] [0,7,16] [4,7,12][0,3,7] [4,7,12] [0,3,7] [4,7,12]>").transpose("<45 36 38 41 45 40 45 40>").strum("0.005")])
    
    patterns.append(['Voicing with inversion', p.pattern(wv, "<A2m C2maj:2 D2maj:1 F2maj A2m E2maj:1 A2m E27:1>")])
    
    comp.dev.active(True)

    # Reverb is not active
    #rev.dev.active(True)  
      
    key_pressed=False
    patterns.append(['End',None])
    print(patterns[0][0], file=vs)
    wv_idx = p.add(wv, patterns[0][1])
    patterns = patterns[1:]
    with p:
      for i,pattern in enumerate(patterns):
        while not key_pressed:
          p.process_event()
          time.sleep(0.1)
          if not check_cycle(p,8*(i+1)):
            print(pattern[0], file=vs)
            if pattern[1] != None:
              p.update(wv_idx, pattern[1])
            break
          ret = vs.v.read_nb(1)
          if ret and ret[0] > 0:
            key_pressed=True

      #Wait for the last pattern
      while not key_pressed:
        time.sleep(0.1)
        if not check_cycle(p,8*(len(patterns)+1)):
          break    
        ret = vs.v.read_nb(1)
        if ret and ret[0] > 0:
          key_pressed=True
          
