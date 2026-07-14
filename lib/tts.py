import gpt_l as gptlib
import argparse
import os
import struct
import wav_play
import audio
import pdeck
import re


def fix_wav_header(filename):
  try:
    size = os.stat(filename)[6]
    if size < 44:
      return False

    data_size = size - 44
    riff_size = size - 8

    with open(filename, 'r+b') as f:
      f.seek(4)
      f.write(struct.pack('<I', riff_size))
      f.seek(40)
      f.write(struct.pack('<I', data_size))
    return True
  except Exception:
    return False


def strip_urls(text):
  # Convert markdown links like [label](https://example.com) -> [label]
  text = re.sub(r'\[([^\]]+)\]\((?:https?|ftp)://[^)\s]+(?:\?[^)]*)?\)', r'[\1]', text)

  # Remove bare URLs
  text = re.sub(r'(?:https?|ftp)://\S+', '', text)

  return text


# The OpenAI TTS endpoint rejects input longer than 4096 characters, so long
# text has to be sent as several separate requests. We keep a safety margin
# under the hard limit and break at the most natural boundary we can find
# (paragraph > line > sentence > word) inside each window, falling back to a
# hard cut only if a single run has no break at all.
TTS_CHAR_LIMIT = 4000


def split_text(text, limit=TTS_CHAR_LIMIT):
  chunks = []
  while len(text) > limit:
    window = text[:limit]
    cut = -1
    for sep in ('\n\n', '\n', '. ', '。', '！', '？', '! ', '? ', '; ', ', ', ' '):
      pos = window.rfind(sep)
      if pos > 0:
        cut = pos + len(sep)
        break
    if cut <= 0:
      cut = limit  # no break found: hard-cut at the limit
    chunks.append(text[:cut])
    text = text[cut:]
  if text:
    chunks.append(text)
  return chunks


def _res_stream(res):
  return getattr(res, 'raw', getattr(res, 's', res))


def play_stream(vs, stream):
  """Play one WAV stream. Returns True if the user pressed a key to stop."""
  interrupted = False
  wp = wav_play.wav_play(16000)
  wp.open_stream(stream)
  wp.play()
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      interrupted = True
      break
  wp.stop()
  wp.close()
  return interrupted


def save_chunks_and_fix_header(gpt, chunks, voice, filename, vs):
  """Generate every chunk and concatenate the audio into one WAV file. The
  first chunk's 44-byte WAV header is kept; later chunks have their header
  stripped so only their PCM data is appended. The combined header is fixed up
  at the end. Returns True on success."""
  try:
    with open(filename, 'wb') as f:
      for i, chunk in enumerate(chunks):
        if len(chunks) > 1:
          print('Generating part {}/{}...'.format(i + 1, len(chunks)), file=vs)
        res = gpt.tts_stream(chunk, voice=voice)
        if not res or res.status_code != 200:
          print('TTS failed on part {}'.format(i + 1), file=vs)
          try:
            if res:
              res.close()
          except Exception:
            pass
          return False
        # Drop the 44-byte RIFF/WAV header from every chunk after the first.
        skip = 0 if i == 0 else 44
        try:
          stream = _res_stream(res)
          while True:
            data = stream.read(1024)
            if not data:
              break
            if skip:
              if len(data) <= skip:
                skip -= len(data)
                continue
              data = data[skip:]
              skip = 0
            f.write(data)
        finally:
          res.close()
    return fix_wav_header(filename)
  except Exception:
    return False


def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='Text to Speech')
  parser.add_argument('input', nargs='?', action='store', default=None,
                      help='Text file to read')
  parser.add_argument('-m', '--model', action='store', default=None,
                      help='Audio backend: an api:"audio" entry name from /config/gpt.json '
                           '(e.g. -m kokoro), or a model entry whose "audio" link to follow. '
                           'Default: the registry "audio" default, else OpenAI.')
  parser.add_argument('-vm', '--voicemodel', action='store', default=None,
                      help='Voice type for TTS. Overrides the backend voice; default: its configured voice.')
  parser.add_argument('-o', '--output', action='store', default=None,
                      help='Output WAV filename. Default is streaming playback only')

  args = parser.parse_args(args_in[1:])

  if not args.input:
    print('Specify input text file', file=vs)
    return

  try:
    with open(args.input, 'r') as f:
      text = f.read()
  except Exception:
    print('Failed to open input file', file=vs)
    return

  text = strip_urls(text)

  gpt = gptlib.chatgpt_util(vs)
  # Select the STT/TTS backend from /config/gpt.json (-m names an api:"audio"
  # entry, e.g. kokoro). With no match it defaults to OpenAI.
  audio = gptlib.resolve_audio(gptlib.load_registry_ro(), args.model)
  gptlib.apply_audio_config(gpt, audio)
  is_openai = audio['base_url'].rstrip('/') == gptlib.OPENAI_BASE
  if is_openai and not gpt.audio_key:
    print('Set OpenAI key in %s' % gptlib.api_key_location(), file=vs)
    return
  print('TTS: %s @ %s' % (gpt.tts_model, audio['base_url']), file=vs)

  # The TTS API caps input at ~4096 chars, so split long text and send one
  # request per chunk.
  chunks = split_text(text)

  if args.output:
    print('Generating speech ({} part(s))...'.format(len(chunks)), file=vs)
    print('Saving to {}...'.format(args.output), file=vs)
    ok = save_chunks_and_fix_header(gpt, chunks, args.voicemodel, args.output, vs)
    if not ok:
      print('Failed to save or fix WAV header', file=vs)
      return
    print('Saved to {}'.format(args.output), file=vs)
  else:
    print('Streaming audio ({} part(s))... press any key to stop'.format(len(chunks)), file=vs)
    for i, chunk in enumerate(chunks):
      if len(chunks) > 1:
        print('Generating part {}/{}...'.format(i + 1, len(chunks)), file=vs)
      res = gpt.tts_stream(chunk, voice=args.voicemodel)
      if not res or res.status_code != 200:
        print('TTS failed on part {}'.format(i + 1), file=vs)
        try:
          if res:
            res.close()
        except Exception:
          pass
        return
      try:
        interrupted = play_stream(vs, _res_stream(res))
      finally:
        res.close()
      if interrupted:
        break
