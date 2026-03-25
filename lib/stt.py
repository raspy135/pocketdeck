import gpt as gptlib

def main(vs, args):
  gpt = gptlib.chatgpt_util(vs)
  if not gpt.read_api_key():
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
    print(f'result "{message}" copied to clipboard', file=vs)
    pdeck.copy_clipboard(message)
    

