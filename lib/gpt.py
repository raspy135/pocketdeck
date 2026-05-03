import network, socket
import codec_config
import ujson
import time
import urequests as requests
import pdeck
import pdeck_utils as pu
import esclib as elib
import argparse
import ubinascii
import audio
import wav_play
import recorder
import os
import re

API_KEY_FILENAME = "/config/openai_api_key"

def file_exists(name):
  if name == None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False

class chatgpt_util:
  def __init__(self,vs):
    self.vs = vs
    self.url = "https://api.openai.com/v1/responses"
    self.stt_url = "https://api.openai.com/v1/audio/transcriptions"
    self.tts_url = "https://api.openai.com/v1/audio/speech"
    self.api_key = ""

  def read_api_key(self):
    try:
      with open(API_KEY_FILENAME,"r") as f:
        self.api_key = f.read().strip()
    except Exception as e:
      print(f"Error to open API key. Put API key to {API_KEY_FILENAME}", file=self.vs)
      return False
    
    return True

  def post(self, url, json=None):
    headers = {
      'Content-Type' : 'application/json',
      'Accept': 'application/json',
      'Authorization' : 'Bearer ' + self.api_key
      }
    return requests.post(url, headers=headers, data=json)



  def make_json(self, message, references, images=None, model="gpt-5.5", instructions = None):
    content_items = []
    
    # Add text message
    if len(references) > 0:
      ref_text = "I put some attached text files as reference. Then answer the question by using attached information. You are not limited to reference the attached text, you can use all your knowledge. \n"
      for i, item in enumerate(references):
        ref_text += f"----- reference {i} -----\n{item}\n"
      ref_text += "----- Question -----\n"
      message = ref_text + message

    content_items.append({"type": "input_text", "text": message})

    # Add images
    if images:
      for img in images:
        if type(img) == str:
          img_url = img
        else:
          b64 = ubinascii.b2a_base64(img).decode('utf-8').strip()
          img_url = f"data:image/jpeg;base64,{b64}"
          
        content_items.append({
          "type": "input_image",
          "image_url": img_url
        })

    payload_dic = {
        "model" : model,
        "tools" : [
          { "type" : "web_search" }
          ],
        "input" : [
          {
            "type": "message",
            "role": "user",
            "content": content_items
          }
        ]
    }
    if instructions:
      payload_dic['instructions'] = instructions
      
    payload = ujson.dumps(payload_dic)
    print(payload)
    return payload
    
  def ask(self,json):
    response = self.post(self.url,json.encode('utf-8'))
    #print(f"res{response.text}")
    try:
      response_data = response.json()
    except:
      print(f"Error: Non-JSON response ({response.status_code})", file=self.vs)
      print(response.text[:200], file=self.vs)
      response.close()
      return None
    response.close()

    if "error" in response_data and response_data['error'] != None:
      print(f"API Error: {response_data['error'].get('message', 'Unknown error')}", file=self.vs)
      return None

    try:
      # Responses API structure: output -> items
      # Each item can be a message with content
      # print(response_data)
      for item in response_data.get("output", []):
        if item.get("type") == "message":
          for content in item.get("content", []):
            if content.get("type") == "output_text" or content.get("type") =="text":
              return content.get("text")
    except Exception as e:
      print(f"Error parsing response: {e}", file=self.vs)
    
    return None

  def stt(self, filename):
    """Transcribes audio using Whisper (Stream Upload)"""
    boundary = "----MicroPythonPdeckBoundary"
    try:
      file_size = os.stat(filename)[6]
    except Exception as e:
      print(f"STT Error reading file stat: {e}", file=self.vs)
      return None
    
    header_bytes = (
        '--' + boundary + '\r\n' +
        'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n' +
        'Content-Type: audio/wav\r\n\r\n'
    ).encode('utf-8')
    
        #'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n' +
    footer_bytes = (
        '\r\n--' + boundary + '\r\n' +
        'Content-Disposition: form-data; name="model"\r\n\r\ngpt-4o-mini-transcribe\r\n' +
        '--' + boundary + '--\r\n'
    ).encode('utf-8')
    
    content_length = len(header_bytes) + file_size + len(footer_bytes)
    print("Uploading audio to STT (streaming)...", file=self.vs)

    import usocket
    try:
      import ussl as ssl
    except ImportError:
      import ssl

    addr = usocket.getaddrinfo("api.openai.com", 443)[0][-1]
    s = usocket.socket()
    try:
      s.connect(addr)
      try:
        s = ssl.wrap_socket(s, server_hostname="api.openai.com")
      except TypeError:
        s = ssl.wrap_socket(s)
        
      req_head = (
          "POST /v1/audio/transcriptions HTTP/1.0\r\n"
          "Host: api.openai.com\r\n"
          "Connection: close\r\n"
          f"Content-Type: multipart/form-data; boundary={boundary}\r\n"
          f"Content-Length: {content_length}\r\n"
          f"Authorization: Bearer {self.api_key}\r\n\r\n"
      ).encode('utf-8')

      s.write(req_head)
      s.write(header_bytes)

      buf = bytearray(16384)
      with open(filename, 'rb') as f:
        while True:
          sz = f.readinto(buf)
          if not sz:
            break
          s.write(memoryview(buf)[:sz])
          
      s.write(footer_bytes)

      l = s.readline()
      if not l:
        print("STT Error: Empty response", file=self.vs)
        return None
        
      status_code = int(l.split(None, 2)[1])
      
      while True:
        line = s.readline()
        if not line or line == b"\r\n":
          break
          
      body_chunks = []
      while True:
        sz = s.readinto(buf)
        if not sz:
          break
        body_chunks.append(bytes(memoryview(buf)[:sz]))
      body = b"".join(body_chunks)

      if status_code == 200:
        return ujson.loads(body).get('text')
      else:
        print(f"STT Error: {status_code} {body.decode('utf-8')}", file=self.vs)
        return None

    except Exception as e:
      print(f"STT Socket Error: {e}", file=self.vs)
      return None
    finally:
      s.close()

  def tts(self, text, filename, voice='alloy'):
    """Converts text to speech"""
    res = self.tts_stream(text, voice)
    if res and res.status_code == 200:
      with open(filename, 'wb') as f:
        f.write(res.content)
      res.close()
      return True
    return False

  def tts_stream(self, text, voice='alloy'):
    """Converts text to speech and returns a response object with a raw stream"""
    payload = ujson.dumps({
        #"model": "tts-1-hd",
        "model": "gpt-4o-mini-tts",
        "input": text,
        "voice": voice,
        #"speed" : 1.1,
        "response_format": "wav"
    }).encode('utf-8')
    
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + self.api_key
    }
    
    # In MicroPython urequests, the response object itself can sometimes be treated as a stream
    return requests.post(self.tts_url, headers=headers, data=payload)

el = elib.esclib()

def record_audio(vs, filename, duration_sec=15):
  """Records 16kHz mono audio"""
  sample_rate = 16000
  cc = codec_config.codec_config()
  cc.toggle_li(False)
  cc.set_agc(True)
  
  audio.sample_rate(sample_rate)
  print(f"Recording... (press any key to stop)", file=vs)
  rec = recorder.stream_record('dummy', vs, 20000)
  # Use num_channels=1 for bandwidth savings as requested
  rec.record(filename, sample_rate * duration_sec, num_channels=1)
  
  # Wait for recording or keypress
  start = time.time()
  while audio.stream_record() and (time.time() - start) < duration_sec:
    pdeck.delay_tick(10)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break
    #if rec.time_silent == 2:
    #  break
  rec.stop()
  return filename

def play_audio(vs, filename):
  """Plays audio from file using wav_play"""
  wp = wav_play.wav_play()
  wp.open(filename)
  wp.play()
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break
  wp.stop()
  wp.close()

def play_audio_stream(vs, stream):
  """Plays audio from a stream using wav_play"""
  wp = wav_play.wav_play()
  wp.open_stream(stream)
  wp.play()
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break
  wp.stop()
  wp.close()

def get_message(vs):
  message=""
  while True:
    ch = vs.read(1)
    if ch == "\r":
      vs.write("\n")
      break
    if ch == chr(8):
      message = message[:-1]
      vs.write(ch)
      vs.write(el.erase_to_end_of_current_line())
    else:
      message += ch
      vs.write(ch)
  vs.write("\n\n")
  return message

def format(message):
  result = ""
  numfound = 0
  i = 0
  while len(message) > 0:
    pos = message.find("**")
    if pos == -1:
      result += message
      break
    result += message[:pos]
    numfound += 1
    if numfound&1:
      result += el.set_font_color(1)
    else:
      result += el.reset_font_color()
    message = message[pos+2:]    
  return result

def main(vs, args_in):
  #vs = pu.vscreen_stream()
  parser = argparse.ArgumentParser(
            description='ChatGPT query' )
  parser.add_argument('-a', '--agent', action='store_true', help='Enable Agent Mode')
  parser.add_argument('-n', '--nosave',action='store_true',help='do not save the result')
  parser.add_argument('-nf', '--no-format',action='store_true',help='do not format text (No bold)')
  parser.add_argument('-c', '--clipboard', action='store_true', help='use clipboard as reference text')
  parser.add_argument('-j', '--jp',action='store_true',help='Answer in Japanese')
  parser.add_argument('-f', '--file',nargs='+',action='store',help='Attach file(s) as reference. file1 file2...')
  parser.add_argument('-i', '--image', nargs='+', action='store',help='Attach image file(s) or image url(s). img1 img2...')
  parser.add_argument('-m', '--model',action='store',default='gpt-5.4',help='Model to use (e.g. gpt-5-mini)')
  parser.add_argument('-v', '--voice',action='store_true',help='Use voice mode (STT and TTS)')
  parser.add_argument('-vt', '--voice-type',action='store',default='coral',help='Voice type for TTS (alloy, coral, echo, fable, onyx, nova, shimmer)')
  parser.add_argument('content', nargs='*',help='Content to ask')
  parser.add_argument('-q', nargs='+',help='Content to ask, use this when you want to specify content explicitly. If you specify a filename, it uses file content as a main content.')

  args = parser.parse_args(args_in[1:])

  gpt = chatgpt_util(vs)
  if not gpt.read_api_key():
    return

  message = ""
  instructions = None

  if args.voice: # and not args.q and not args.content:
    rec_file = "/sd/work/voice_rec.wav"
    record_audio(vs, rec_file)
    print("Transcribing...", file=vs)
    message = gpt.stt(rec_file)
    if not message:
      print("Failed to transcribe audio", file=vs)
      return
    print(f"You (STT): {message}", file=vs)
    instructions = "Response will be fed to OpenAI TTS engine. Optimize your responce for Text to speech. Basically keep it short, suitable input for your text to speech engine."
    
  elif not args.content and not args.q:
    message = get_message(vs)
  else:
    if args.content:
      message += ' '.join(args.content)
    if args.q:
      if len(args.q) == 1 and file_exists(args.q[0]):
        with open( args.q[0],"r") as f:
          message = f.read()
      else:
        message += ' '.join(args.q)
  if len(message) == 0:
    return

  ex1 = " and answer in Japanese" if args.jp else  ""
  message = message + ex1

  ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
  time_str = f"[User current time: {ctime[0]:04d}-{ctime[1]:02d}-{ctime[2]:02d} {ctime[3]:02d}:{ctime[4]:02d}]\n"
  message = time_str + message

  references = []
  
  if args.agent:
    idx = 0
    while True:
        start = message.find('[[', idx)
        if start == -1:
            break
        end = message.find(']]', start)
        if end == -1:
            break
        match = message[start+2:end]
        idx = end + 2
        if file_exists(match):
            try:
                with open(match, 'r') as f:
                    references.append("---- " + match + " ----\n" + f.read())
            except Exception as e:
                print(f"Agent Mode: Error reading {match}: {e}", file=vs)
        else:
            print(f"Agent Mode: File {match} not found", file=vs)
            
    for auto_file in ["/sd/lib/data/agent_mode.md", "/sd/Documents/pd/README.md"]:
        if file_exists(auto_file):
            try:
                with open(auto_file, 'r') as f:
                    references.append("---- " + auto_file + " ----\n" + f.read())
            except Exception:
                pass
                
    agent_instruction = (
        "CRITICAL INSTRUCTION: You are an autonomous agent operating on a MicroPython device. "
        "You MUST execute commands by strictly using the markdown code blocks defined in agent_mode.md."
        "(`[type]:filename`, `python:execute`, `iterate`). "
    )
    
    if instructions:
        instructions += "\n\n" + agent_instruction
    else:
        instructions = agent_instruction
        
    message += "\n\n[SYSTEM NOTE: Follow the critical rules in agent_mode.md to perform actions.]"

  if args.file:
    files = args.file
    for file in files:
      if file.startswith("http://") or file.startswith("https://"):
        references.append(file)
        continue
        
      try:
        with open(file,'r') as f:
          references.append("---- " + file + " ----\n" + f.read())
      except Exception as e:
        print(f'Error when opening {file}', file=vs)
        return
      
  if args.clipboard:
    references.append(pdeck.clipboard_paste().decode("utf-8"))
  
  images = []
  if args.image:
    image_paths = args.image
    for img_path in image_paths:
      if img_path.startswith("http://") or img_path.startswith("https://"):
        images.append(img_path)
      else:
        try:
          with open(img_path, 'rb') as f:
            images.append(f.read())
        except Exception as e:
          print(f'Error when opening image {img_path}', file=vs)
          return
  model = args.model
  if model in ('m','medium'):
    model = 'ngpt-5.4'
  elif model in ('h','high'):
    model = 'gpt-5.5'
  elif model in ('f','fast'):
    model = 'gpt-5.4-mini'
  raw_response = gpt.ask(gpt.make_json(message, references, images, model, instructions = instructions))
  if not raw_response:
    return
  
  if args.no_format:
    response = raw_response
  else:
    response = format(raw_response)
  if response:
    print(response, file=vs)
    if args.voice:
      #raw_response = "Speak fast and casually: " + raw_response
      raw_response_sub = re.sub('\]\(ht.+?\)',']',raw_response)
      
      print(raw_response_sub)
      res = gpt.tts_stream(raw_response_sub, voice=args.voice_type)
      if res and res.status_code == 200:
        # In MicroPython urequests, the raw socket is often .raw or .s
        # If none exist, we try the object itself as a backup
        stream = getattr(res, "raw", getattr(res, "s", res))
        #print(f"Connecting stream... {type(stream)}", file=vs)
        try:
          play_audio_stream(vs, stream)
        except Exception as e:
          print(f"Streaming failed: {e}. Falling back to file mode.", file=vs)
          # Re-save to file if possible or just report error
          # For now, we've already consumed part of the stream, so fallback is tricky
        res.close()

    if args.nosave:
      return
    ctime = time.gmtime(time.time()+pu.timezone*60*15)
    filename = f"/sd/log/gptlog{ctime[1]:02}{ctime[2]:02}_{ctime[3]:02}{ctime[4]:02}"
    pdeck.shared_filelist(filename)
    pdeck.clipboard_copy(filename)      
    with open(filename,"w") as f:
      f.write(message)
      f.write('\n')
      f.write(raw_response)
    
    print(f"Saved to {filename} and the filename copied to clipboard", file = vs)
      
  if args.agent:
    idx = 0
    while True:
      start = raw_response.find("```", idx)
      if start == -1:
        break
      end = raw_response.find("```", start + 3)
      if end == -1:
        break
        
      block = raw_response[start+3:end]
      idx = end + 3
      
      first_nl = block.find('\n')
      if first_nl == -1:
        continue
        
      lang_tag = block[:first_nl].strip()
      code = block[first_nl+1:]
      
      if ":" in lang_tag and lang_tag != "python:execute":
        out_filename = lang_tag.split(":", 1)[1].strip()
        print(f"{el.set_font_color(1)}Agent: Saving to {out_filename}{el.reset_font_color()}", file=vs)
        
        if file_exists(out_filename):
          try:
            os.stat("/sd/backup")
          except OSError:
            try:
              os.mkdir("/sd/backup")
            except:
              pass
          base = out_filename.split("/")[-1]
          ctime = time.gmtime(time.time()+pu.timezone*60*15)
          backup_name = f"/sd/backup/{base}_{ctime[1]:02}{ctime[2]:02}_{ctime[3]:02}{ctime[4]:02}"
          try:
            os.rename(out_filename, backup_name)
            print(f"{el.set_font_color(1)}Agent: Backing up original file to {backup_name}{el.reset_font_color()}", file=vs)
          except:
            pass
            
        try:
          with open(out_filename, "w") as f:
            f.write(code)
        except Exception as e:
          print(f"{el.set_font_color(1)}Agent: Failed to write {out_filename}: {e}{el.reset_font_color()}", file=vs)
          
      elif lang_tag == "python:execute":
        print(f"{el.set_font_color(1)}Agent: Executing python block...{el.reset_font_color()}", file=vs)
        try:
          exec_locals = {'vs': vs, 'pdeck': pdeck}
          exec(code, globals(), exec_locals)
        except Exception as e:
          print(f"{el.set_font_color(1)}Agent: Execution Error: {e}{el.reset_font_color()}", file=vs)
          
      elif lang_tag == "iterate":
        print(  f"{el.set_font_color(1)}Agent: Iterating...{el.reset_font_color()}", file=vs)
        iter_args = ['gpt'] + code.split()
        for i, item in enumerate(iter_args):
          if item == '-q':
            iter_args = iter_args[0:i+1] + [" ".join(iter_args[i+2:])]
            break
        print(f"{el.set_font_color(1)}Agent: Calling main with {iter_args}{el.reset_font_color()}", file=vs)
        main(vs, iter_args)

