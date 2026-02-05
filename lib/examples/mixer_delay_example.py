import pie
import time
import audio
import wav_loader
from pie import Pie, PieSampler, PieMixer, PieEcho, PieRouter

def main(vs, args):
  # Initialize audio
  audio.power(True)
  
  print("Mixer & Echo Example: Panning and Echo Automation", file=vs)

  with PieRouter() as master:
    # sampler -> echo -> mixer -> master
    with PieMixer() as mixer:
      with PieEcho(max_ms=1000) as echo:
        with PieSampler(4) as sampler:
          # Setup routing
          master.add(sampler)
          master.add(mixer)
          master.add(echo)
          
          # Mock data for demonstration
          kick, ch_kick = wav_loader.load_wav("/sd/data/samples/KMRBI_SJ_kick_one_shot_billington.wav")
          snare, ch_snare = wav_loader.load_wav('/sd/data/samples/MCS_snare_super_bright.wav')
          sampler.load(0, kick, ch_kick)
          sampler.load(1, snare, ch_snare)

          # Configure effects
          echo.set_type("ping_pong")
          echo.set_params(time_ms=250, feedback=0.2)
          
          # Create sequencer
          pie = Pie(bpm=120)
          
          # 1. Add beats
          pie.add(sampler, "0 . 1 . 0 0 1 .")
          
          # 2. Add Echo Sweep (time_ms)
          # We sweep the primary parameter (time_ms)
          #pie.add(echo, "100 200 300 400 500 400 300 200")
          
          # 3. Add Pan Sweep
          # Use dispatch() via pattern syntax cmd:val:trans
          pie.add(mixer, "[pan:-1:0 pan:1:0]")# ~ pan:1:0 ~]")
          
          print("Starting sequence (8 cycles)...", file=vs)
          ct = 0
          last_cycle=-1
          with pie:
            while True:
              pie.process_event()
              time.sleep(0.1)
              cur_cycle = int(pie.playing_cycle)
              if last_cycle != cur_cycle:
                print(f"Cycle {cur_cycle}/8...", file=vs)
                last_cycle = cur_cycle
              ct += 1
              if cur_cycle == 4:
                time.sleep(8) #for delay tail
                break

  print("Example finished", file=vs)
