import gpt as gptlib
import pdeck
import argparse

def main(vs, args_in):
  
  gpt = gptlib.chatgpt_util(vs)
  if not gpt.read_api_key():
    print("Set OpenAI key in /config/openai_api_key", file=vs)
    return

  parser = argparse.ArgumentParser(
            description='Speech to Text' )
  parser.add_argument('input',nargs='?', action='store', default=None, help='WAV File to read')
  parser.add_argument('-s','--silent', action='store_true', help='No extra output messages. Record start immediate.')
  parser.add_argument('-d','--duration', action='store', default=20, help='recording duration in seconds')
  parser.add_argument('-l','--language', action='store', default = None, help='language')
  parser.add_argument('-o', '--output', action='store', help='Text file to write')

  args = parser.parse_args(args_in[1:])

  if args.input:
    print("Transcribing...", file=vs)
    message = gpt.stt(args.input)
    print(f'"{message}"\n The result copied to clipboard', file=vs)
    pdeck.clipboard_copy(message)
    return
  language = args.language
  silent = args.silent
  duration = int(args.duration)
  
  while True:
    if not silent:
      print('Press any key to start record, press q to quit', file=vs)
      k = vs.read(1)
      if k == 'q':
        break
    #print('recording')
    rec_file = "/sd/work/voice_rec.wav"
    pdeck.led(1,30)
    gptlib.record_audio(vs, rec_file, duration, silent)
    pdeck.led(1,0)
    if not silent:
      print("Transcribing...", file=vs)
    message = gpt.stt(rec_file, language)
    if args.output:
      with open(args.output,"w") as f:
        f.write(message)
        if not silent:
          print(f'The result saved to {args.output}', file=vs)
    else:
      if not silent:
        print(f'"{message}"\n The result copied to clipboard', file=vs)
      else:
        print(message, file=vs)
      pdeck.clipboard_copy(message)
    if silent:
      break

