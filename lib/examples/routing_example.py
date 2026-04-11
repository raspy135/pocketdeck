import audio
import time
import math
import wav_loader
import download_drumkit_uzu

def main(vs, args):
  # Initialize audio
  audio.power(True)
  if not download_drumkit_uzu.check(vs):
    return

  # Load some samples
  try:
    # Assuming samples are in the same directory or relative to it
    kick, ch_kick = wav_loader.load_wav("/sd/data/uzu-drumkit/11_bd_mot4i.wav")

    snare, ch_snare = wav_loader.load_wav('/sd/data/uzu-drumkit/11_sd_switchangel_3.wav')
  except Exception as e:
    # Fallback if samples not found
    print(f"Warning: Samples not found {e}", file=vs)
    return

  print("Audio engine initialized", file=vs)

  with audio.router() as master:
    # 1. Create a Router to group drums
    with audio.router() as drums_router:
      # Add drums_router to master
      master.add(drums_router)

      # 2. Add Sampler to drums_router
      with audio.sampler(2) as s:
        s.set_sample(0, kick, ch_kick)
        s.set_sample(1, snare, ch_snare)
        drums_router.add(s)
        # 3. Create a Filter and add it to drums_router AFTER the sampler
        # This will filter everything already in the drums_router mix buffer
        with audio.filter() as lpf:
          lpf.set_type("lpf")
          lpf.set_params(4000, 1.0)
          drums_router.add(lpf)
          lpf.active(True)
          #return
          
          print("Routing: Sampler -> Drums Router (aggregated) -> LPF Filter -> Master Router", file=vs)
          
          # Start playback
          freq = 100
          lpf.set_params(freq, 1.5, 4000) # Sweep over 300ms
          for i in range(8):
            s.play(0) # kick
            time.sleep(0.5)
            s.play(1) # snare
                
                
            time.sleep(0.5)

  print("Example finished", file=vs)
