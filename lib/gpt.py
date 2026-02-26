import network, socket
import ujson
import time
import urequests as requests
import pdeck
import pdeck_utils as pu
import esclib as elib
import argparse
import ubinascii

API_KEY_FILENAME = "/config/openai_api_key"

class chatgpt_util:
  def __init__(self,vs):
    self.vs = vs
    self.url = "https://api.openai.com/v1/responses"
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

  def make_json(self, message, references, images=None, model="gpt-5.2"):
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

    payload = ujson.dumps({
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
    })
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
      print(response_data)
      for item in response_data.get("output", []):
        if item.get("type") == "message":
          for content in item.get("content", []):
            if content.get("type") == "output_text" or content.get("type") =="text":
              return content.get("text")
    except Exception as e:
      print(f"Error parsing response: {e}", file=self.vs)
    
    return None

el = elib.esclib()

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
  parser.add_argument('-n', '--nosave',action='store_true',help='do not save the result')
  parser.add_argument('-c', '--clipboard', action='store_true', help='use clipboard as reference text')
  parser.add_argument('-j', '--jp',action='store_true',help='Answer in Japanese')
  parser.add_argument('-f', '--file',action='store',help='Attach file(s) as reference. file1,file2...')
  parser.add_argument('-i', '--image',action='store',help='Attach image file(s) or image url(s). img1,img2...')
  parser.add_argument('-m', '--model',action='store',default='gpt-5.2',help='Model to use (e.g. gpt-5-mini)')
  parser.add_argument('content', nargs='*',help='Content to ask')

  args = parser.parse_args(args_in[1:])

  print(f"Save:{args.nosave}",file=vs)
  print(f"Content:{args.content}",file=vs)
  print("Hello", file=vs)
  if not args.content:
    message = get_message(vs)
  else:
    message = ' '.join(args.content)


  print(f"'{message}'",file=vs)
  #return
  if len(message) == 0:
    return

  ex1 = "and answer in Japanese" if args.jp else  ""
  message = message + ex1

  #response = "dummy **important** response\n\nnext line **is** important too."
  gpt = chatgpt_util(vs)
  if not gpt.read_api_key():
    return
  references = []
  if args.file:
    files = args.file.split(',')
    for file in files:
      try:
        with open(file,'r') as f:
          references.append(f.read())
      except Exception as e:
        print(f'Error when opening {file}', file=vs)
        return
      
  if args.clipboard:
    references.append(pdeck.clipboard_paste().decode("utf-8"))
    #references.append(a.decode("utf-8"))
  #print(references)
  
  images = []
  if args.image:
    image_paths = args.image.split(',')
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

  #print(references)
  #return
  raw_response = gpt.ask(gpt.make_json(message, references, images, args.model))
  
  response = format(raw_response)
  if response:
    print(response, file=vs)
    if args.nosave:
      return
    ctime = time.gmtime(time.time()-pu.timezone)
    filename = f"/sd/log/gptlog{ctime[1]:02}{ctime[2]:02}_{ctime[3]:02}{ctime[4]:02}"
    pdeck.clipboard_copy(filename)      
    with open(filename,"w") as f:
      f.write(message)
      f.write('\n')
      f.write(raw_response)
    
    print(f"Saved to {filename} and the filename copied to clipboard", file = vs)
      
  
