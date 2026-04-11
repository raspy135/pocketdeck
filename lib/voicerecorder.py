import recorder
import argparse
import audio
import pdeck

def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='Speech to text, Open AI API' )
  parser.add_argument('filename', nargs='?', default="/sd/work/voice.wav", help='filename to record')
  parser.add_argument('-l', '--length',action='store', default='7200', help='Length in second, you can also specify by minutes like 100m. Default is 2 hours')
  parser.add_argument('-s', '--sample_rate',action='store', default='8000', help='Sample rate')

  args = parser.parse_args(args_in[1:])
  
  sample_rate = int(args.sample_rate)
  
  audio.sample_rate(sample_rate)

  length = int(args.length) if args.length[-1] != 'm' else int(args.length[:-1])*60

  print(f"Recording... filename = {args.filename}", file=vs)
  print("Hit enter or q to stop recording")
  
  rec = recorder.stream_record('dummy', vs, 60000)
  rec.record(args.filename, sample_rate * length, num_channels=1)
  
  while(audio.stream_record()):
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      keys = ret[1].encode('ascii')
      if keys in (b'q', b'\r'):
        break

  rec.stop()
  print(f"The filename was copied to clipboard", file=vs)  
  pdeck.clipboard_copy(args.filename)
  
