import audio
import time
import wav_loader
import download_drumkit_uzu

from pie import Pie, PieSampler, PieCompressor, PieRouter

def main(vs, args):
    # Initialize audio
    audio.power(True)
    if not download_drumkit_uzu.check(vs):
      return
    
    # Load a drum loop or samples
    try:
        # We'll use the kick sample for testing peak reduction
        kick, ch_kick = wav_loader.load_wav("/sd/data/uzu-drumkit/11_bd_mot4i.wav")
    except Exception as e:
        print(f"Warning: Sample not found {e}", file=vs)
        return

    print("Compressor Example: Testing Peak Reduction & Warm Clipping", file=vs)

    with PieRouter() as master:
        # Create a Compressor on the master bus
        with PieCompressor() as comp:
            
            # Create a Sampler and add it to the compressor
            with PieSampler(2) as s:
                s.dev.set_sample(0, kick, ch_kick)
                master.add(s)
                master.add(comp)
                
                # 1. No Compression
                print("1. Playing without compression...", file=vs)
                comp.set_params(gain=1.0, reduction=0.0)
                comp.dev.active(True)
                for _ in range(2):
                    s.play(0)
                    time.sleep(0.5)
                
                # 2. Heavy Reduction (Peak Squeezing)
                print("2. Heavy compression (reduction=10)...", file=vs)
                comp.set_params(gain=5.0, reduction=10, transition_ms=500)
                time.sleep(0.6)
                for _ in range(4):
                    s.play(0)
                    time.sleep(0.5)
                
                # 3. High Makeup Gain (Testing Warm Clipping)
                print("3. Pushing gain with warm clipping...", file=vs)
                comp.set_params(gain=2.5, reduction=0.5, transition_ms=500)
                time.sleep(0.6)
                for _ in range(4):
                    s.play(0)
                    time.sleep(0.5)

    print("Example finished", file=vs)
