import audio
import time
import math
import random
from pie import Pie, Pattern, PieWavetable, PieSampler, PieCompressor, PieReverb

# --- 808 Style Synthesizers ---

def generate_kick_808(length, sample_rate=24000):
    data = bytearray(length * 2)
    start_freq = 150
    end_freq = 45
    for i in range(length):
        # Logarithmic frequency sweep
        freq = end_freq + (start_freq - end_freq) * math.exp(-i / (length * 0.15))
        phase = 2 * math.pi * freq * i / sample_rate
        # Exponential amplitude decay
        amp = math.exp(-i / (length * 0.4))
        val = int(28000 * math.sin(phase) * amp)
        data[2*i] = val & 0xFF
        data[2*i+1] = (val >> 8) & 0xFF
    return data

def generate_snare_808(length):
    data = bytearray(length * 2)
    for i in range(length):
        # White noise with fast decay
        noise = random.getrandbits(15) - 16384
        #amp = 1 - i/length
        amp = math.exp(-i / (length * 0.4))
        #amp = math.exp(-i / (length * 0.2))
        val = int(noise * amp * 0.8)
        data[2*i] = val & 0xFF
        data[2*i+1] = (val >> 8) & 0xFF
    return data

def generate_hihat_808(length):
    data = bytearray(length * 2)
    for i in range(length):
        # High-pitched noise burst
        noise = random.getrandbits(15) - 16384
        # Very fast linear decay
        amp = max(0, 1 - i/length)
        val = int(noise * amp * 0.5)
        data[2*i] = val & 0xFF
        data[2*i+1] = (val >> 8) & 0xFF
    return data

def generate_bass_tone(size):
    # Pure sine for deep sub
    data = bytearray(size * 2)
    for i in range(size):
        val = int(28983 * math.sin(2 * math.pi * i / size))
        data[2*i] = val & 0xFF
        data[2*i+1] = (val >> 8) & 0xFF
    return data

def key_wait(vs, p_obj, period, repeatuntil):
    """Wait for key press while printing song progress."""
    ct = 0
    while True:
        p_obj.process_event()
        # Print current cycle to vs console
        cur_cycle = p_obj.playing_cycle
        if ct&1 == 0:
          print(f"[Cycle {int(cur_cycle)}] Progressive minimal techno...", end="\r", file=vs)
        ct += 1
        ret = vs.v.read_nb(1)
        if ret and ret[0] > 0:
            return False
        ## we need to update 2 cycles ahead because : lookahead cycle(1) + and currently playing by audio engine(1)  
        if cur_cycle >= repeatuntil-1.5:
          break
        time.sleep(0.1)
    return True

def main(vs, args):
    audio.power(True)
    audio.sample_rate(44100)
    
    with PieSampler(16) as drums, PieWavetable(1) as bass_synth, PieReverb() as reverb, PieCompressor() as comp:
        reverb.set_params(room_size=0.1, brightness=0.3, predelay_ms=15.0, transition_ms=0, mix=0.2)
        #reverb.detach()
        comp.set_params(3.5, 3)
        # 1. Prepare 808 Sounds
        kick = generate_kick_808(4000)
        snare = generate_snare_808(3000)
        hh_closed = generate_hihat_808(500)
        hh_open = generate_hihat_808(2500)
        
        drums.load(0, kick)
        drums.load(1, snare)
        drums.load(2, hh_closed)
        drums.load(3, hh_open)
        drums.dev.volume(0,0.3)
        drums.dev.volume(1,0.5)
        drums.dev.volume(2,0.2)
        drums.dev.volume(3,0.3)
        
        # 2. Prepare Sub Bass
        bass_wave = generate_bass_tone(256)
        bass_synth.set_table(0, [bass_wave])
        for i in range(4):
            bass_synth.dev.volume(i, 0.4)
            bass_synth.dev.set_adsr(i, 20, 150, 0.5, 300)
        
        # 3. Composition
        bpm = 126
        p = Pie(bpm=bpm)
        cycle_time = (60 / bpm) * 4 # Duration of one 4-beat cycle
        
        # Techno Patterns
        # Kick on 1, 2, 3, 4. Snare on 2 and 4.
        d_beat_basic = "0 0 0 0" 
        d_beat_basic2 = "0 0 0 0, ~ 1 ~ 1, [~ 2]* 16" 
        d_beat_basic3 = "0 0 0 0, ~ 1 ~ 1, [~ 3]* 16" 
        d_beat_full = "0 [0 0] 0 [0 1], [~ 2]*8"
        d_beat_minimal = "0 ~ 0 0, [~ 2]*4"

        p.add(comp,"[3 1 3 1]")
        # Hypnotic Sub Bass (MIDI 36 is C2)
        b_loop = "[36 36 ~ 36] [36 ~ 39 36]"
        b_offbeat = "[~ 36]*4"
        
        # Minimal Percussion
        perc = "[~ 2 2 2] [2 ~ 3 2]*2"
        
        print("\n--- Minimal Techno 808 Showcase ---", file=vs)
        print("Press any key to stop current section.", file=vs)
        
        # START THE TRACK
        print("\n[Intro] Kick & Sub Pulse", file=vs)
        idx_d = p.add(drums, d_beat_basic2)
        idx_b = p.add(bass_synth, b_offbeat)
        
        with p:
          if not key_wait(vs, p, cycle_time, 4):
            return
              
          print("\n[Groove] Adding Minimal Percussion", file=vs)
          p.update(idx_d, d_beat_minimal + ", " + perc)
          if not key_wait(vs, p, cycle_time, 8):
            return
              
          print("\n[The Drop] Full 808 Power", file=vs)
          p.update(idx_d, d_beat_full + ", [2*16]") # Fast hats
          p.update(idx_b, b_loop)
          if not key_wait(vs, p, cycle_time, 12):
            return
              
          print("\n[Outro] Stripping Back", file=vs)
          p.update(idx_d, d_beat_basic)
          p.remove(idx_b)
          if not key_wait(vs, p, cycle_time, 16):
            return
          while True:
            p.process_event()
            if p.playing_cycle >= 15.8:
              break
            time.sleep(0.1)
        
        print("\nTrack Finished.", file=vs)

if __name__ == "__main__":
    from mock_device import vs
    main(vs, [])
