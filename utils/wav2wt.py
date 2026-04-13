import wave
import struct
import math
import argparse
import os

class WavetableConverter:
    def __init__(self, filename, frequency=110.0, frame_size=256, spread=0, num_frames=None, adaptive=True, normalize=False):
        self.filename = filename
        self.target_freq = frequency
        self.frame_size = frame_size
        self.spread = spread
        self.num_frames = num_frames
        self.adaptive = adaptive
        self.normalize = normalize
        self.output_rate = 48000
        
        self.input_data = []
        self.input_rate = 0
        self.channels = 0
        
    def load(self):
        with wave.open(self.filename, 'rb') as w:
            self.input_rate = w.getframerate()
            self.channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            n_frames = w.getnframes()
            
            if sampwidth == 3:
                # 24-bit manual extraction
                raw_data = []
                for _ in range(n_frames):
                    frame_bytes = w.readframes(1)
                    # Just take the first channel
                    b = frame_bytes[0:3]
                    val = int.from_bytes(b, 'little', signed=True)
                    raw_data.append(val >> 8) 
            else:
                raw = w.readframes(n_frames)
                if sampwidth == 2:
                    fmt = "<" + "h" * (n_frames * self.channels)
                    unpacked = struct.unpack(fmt, raw)
                    raw_data = unpacked[::self.channels] if self.channels > 1 else unpacked
                elif sampwidth == 1:
                    fmt = "<" + "B" * (n_frames * self.channels)
                    unpacked = [(v - 128) * 256 for v in struct.unpack(fmt, raw)]
                    raw_data = unpacked[::self.channels] if self.channels > 1 else unpacked
                else:
                    raise ValueError(f"Unsupported sample width: {sampwidth}")
            
            self.input_data = raw_data
        return len(self.input_data)

    def find_zero_crossing(self, start_idx):
        for i in range(max(0, start_idx), len(self.input_data) - 1):
            if self.input_data[i] <= 0 < self.input_data[i+1]:
                return i
        return -1

    def resample_segment(self, start_idx, segment_len):
        out = []
        ratio = segment_len / self.frame_size
        for i in range(self.frame_size):
            pos = start_idx + i * ratio
            idx = int(pos)
            frac = pos - idx
            if idx + 1 < len(self.input_data):
                v0 = self.input_data[idx]
                v1 = self.input_data[idx+1]
                val = v0 + frac * (v1 - v0)
            elif idx < len(self.input_data):
                val = self.input_data[idx]
            else:
                val = 0
            out.append(int(val))
        
        if self.normalize:
            peak = 0
            for v in out:
                if abs(v) > peak: peak = abs(v)
            if peak > 0:
                scale = 32767.0 / peak
                out = [int(v * scale) for v in out]
                
        return out

    def find_best_sync(self, last_sync, expected_period):
        search_min = int(expected_period * 0.9)
        search_max = int(expected_period * 1.3)
        template_len = int(expected_period * 0.8)
        template = self.input_data[last_sync : last_sync + template_len]
        if not template: return -1
            
        best_offset = -1
        min_diff = float('inf')
        for offset in range(search_min, search_max):
            candidate_sync = last_sync + offset
            if candidate_sync + template_len >= len(self.input_data): break
            diff = 0
            for j in range(template_len):
                d = template[j] - self.input_data[candidate_sync + j]
                diff += d * d 
            if diff < min_diff:
                min_diff = diff
                best_offset = offset
        
        if best_offset == -1: return -1
        
        refined_match = last_sync + best_offset
        for snap in range(refined_match - 8, refined_match + 8):
            if 0 <= snap < len(self.input_data) - 1:
                if self.input_data[snap] <= 0 < self.input_data[snap+1]:
                    return snap
        return refined_match

    def convert(self, output_filename):
        print(f"Opening {self.filename}...")
        if not self.load(): return
        
        target_period = self.input_rate / self.target_freq
        print(f"Target: {self.target_freq}Hz, Mode: {'Adaptive' if self.adaptive else 'Consistent'}, Norm: {'Yes' if self.normalize else 'No'}")
        
        all_frames = []
        current_sync = self.find_zero_crossing(0)
        if current_sync == -1:
            print("Error: No zero crossing found."); return
            
        while True:
            next_sync = self.find_best_sync(current_sync, target_period)
            if next_sync == -1 or next_sync <= current_sync: break
            
            actual_period = next_sync - current_sync
            extract_len = actual_period if self.adaptive else target_period
            
            frame = self.resample_segment(current_sync, extract_len)
            all_frames.extend(frame)
            
            count = len(all_frames) // self.frame_size
            if self.num_frames and count >= self.num_frames: break
            
            for _ in range(self.spread + 1):
                current_sync = next_sync
                next_sync = self.find_best_sync(current_sync, target_period)
                if next_sync == -1: break
            if next_sync == -1: break
            
            if count % 50 == 0:
                print(f"  Extracted {count} frames...")

        if not all_frames:
            print("Error: No frames extracted."); return

        with wave.open(output_filename, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.output_rate)
            w.writeframes(struct.pack("<" + "h" * len(all_frames), *all_frames))
            
        print(f"Done! {len(all_frames) // self.frame_size} frames -> {output_filename}")

def main():
    parser = argparse.ArgumentParser(description="Convert WAV to Pocket Deck Wavetable.")
    parser.add_argument("input", help="Source WAV")
    parser.add_argument("-o", "--output", help="Output WAV")
    parser.add_argument("--frequency", type=float, default=110.0, help="Source Hz (default 110)")
    parser.add_argument("--frame_size", type=int, default=256, help="Samples per frame (default 256)")
    parser.add_argument("--spread", type=int, default=0, help="Frames to skip")
    parser.add_argument("--num", type=int, help="Max frames")
    parser.add_argument("--consistent", action="store_true", help="Use fixed resampling ratio")
    parser.add_argument("--normalize", action="store_true", help="Normalize volume across cycles")
    
    args = parser.parse_args()
    if not args.output:
        args.output = os.path.splitext(args.input)[0] + "_wt.wav"
        
    converter = WavetableConverter(args.input, frequency=args.frequency, 
                                frame_size=args.frame_size, spread=args.spread, 
                                num_frames=args.num, adaptive=(not args.consistent),
                                normalize=args.normalize)
    converter.convert(args.output)

if __name__ == "__main__":
    main()
