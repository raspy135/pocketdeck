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
  parser.add_argument('-o', '--output', action='store', help='Text file to write')

  args = parser.parse_args(args_in[1:])

  if args.input:
    print("Transcribing...", file=vs)
    message = gpt.stt(args.input)
    print(f'"{message}"\n The result copied to clipboard', file=vs)
    pdeck.clipboard_copy(message)
    return

  while True:
    print('Press any key to start record', file=vs)
    k = vs.read(1)
    if k == 'q':
      break
    # print("Listening..", file=vs)
    rec_file = "/sd/work/voice_rec.wav"
    gptlib.record_audio(vs, rec_file)
    print("Transcribing...", file=vs)
    message = gpt.stt(rec_file)
    if args.output:
      with open(args.output,"w") as f:
        f.write(message)
        print(f'The result saved to {args.output}', file=vs)
    else:
      print(f'"{message}"\n The result copied to clipboard', file=vs)
      pdeck.clipboard_copy(message)
    

