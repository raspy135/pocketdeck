import network, socket
import ujson
import time
import urequests as requests
import pdeck
import pdeck_utils as pu
import esclib as elib
import argparse
import gpt_post

class chatgpt_util:
  def __init__(self,vs):
    self.vs = vs
    self.url = "https://api.openai.com/v1/responses"
    
  def make_json(self, message, references):
    if len(references) > 0:
      out = []
      out.append("I put some attached text files as reference. Then answer the question by using attached information. You are not limited to reference the attached text, you can use all your knowledge. ")
      for i,item in enumerate(references):
        out.append(f"----- reference  {i} -----")
        out.append(item)
      out.append("----- Question -----")
      out.append(message)
      message = "\n".join(out)
    #print(message)  
    payload = ujson.dumps({
        "model" : "gpt-5.2",
        "input" : message
        })
    #print(payload)
    return payload
    
  def ask(self,json):
    response = gpt_post.post(self.url,json.encode('utf-8'))
    response_data = response.json()
    response.close()

    #print(response_data)
    if response_data:
      print(response_data["error"])
      #  print(response_data["error"]["message"], file=self.vs)
      #  return None
      res_text = response_data["output"][0]["content"][0]["text"]
      return res_text

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
  #return
  raw_response = gpt.ask(gpt.make_json(message, references))
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
      
  
