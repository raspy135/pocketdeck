import network
import socket
import json
import esclib as elib

ROMAJI_TABLE = {
    "a":"あ","i":"い","u":"う","e":"え","o":"お",
    "ka":"か","ki":"き","ku":"く","ke":"け","ko":"こ",
    "sa":"さ","shi":"し","si":"し","su":"す","se":"せ","so":"そ",
    "ta":"た","chi":"ち","ti":"ち","tsu":"つ","tu":"つ","te":"て","to":"と",
    "na":"な","ni":"に","nu":"ぬ","ne":"ね","no":"の",
    "ha":"は","hi":"ひ","fu":"ふ","hu":"ふ","he":"へ","ho":"ほ",
    "ma":"ま","mi":"み","mu":"む","me":"め","mo":"も",
    "ya":"や","yu":"ゆ","yo":"よ",
    "ra":"ら","ri":"り","ru":"る","re":"れ","ro":"ろ",
    "wa":"わ","wo":"を","n":"ん","nn":"ん",

    #Dakuon, Han-dakuon
    # G (dakuon)
    "ga":"が","gi":"ぎ","gu":"ぐ","ge":"げ","go":"ご",
    # Z
    "za":"ざ","ji":"じ","zu":"ず","ze":"ぜ","zo":"ぞ",
    "zi":"じ",
    # D
    "da":"だ","di":"ぢ","du":"づ","de":"で","do":"ど",
    # B
    "ba":"ば","bi":"び","bu":"ぶ","be":"べ","bo":"ぼ",
    # P (handakuon)
    "pa":"ぱ","pi":"ぴ","pu":"ぷ","pe":"ぺ","po":"ぽ",


    # digraphs
    "kya":"きゃ","kyu":"きゅ","kyo":"きょ",
    "sha":"しゃ","shu":"しゅ","sho":"しょ",
    "sya":"しゃ","syu":"しゅ","syo":"しょ",
    "cha":"ちゃ","chu":"ちゅ","cho":"ちょ",
    "tya":"ちゃ","tyu":"ちゅ","tyo":"ちょ",
    "nya":"にゃ","nyu":"にゅ","nyo":"にょ",
    "hya":"ひゃ","hyu":"ひゅ","hyo":"ひょ",
    "mya":"みゃ","myu":"みゅ","myo":"みょ",
    "rya":"りゃ","ryu":"りゅ","ryo":"りょ",
    "gya":"ぎゃ","gyu":"ぎゅ","gyo":"ぎょ",
    "ja":"じゃ","ju":"じゅ","jo":"じょ",
    "bya":"びゃ","byu":"びゅ","byo":"びょ",
    "pya":"ぴゃ","pyu":"ぴゅ","pyo":"ぴょ",
    "-":"ー", 
    ",,":",",
    ",":"、", 
    ".":"。", 
    "[":"「",
    "]":"」",

 # Extended foreign sounds with フ
    "fa":"ふぁ","fi":"ふぃ","fe":"ふぇ","fo":"ふぉ",
    "dha":"でぁ","dhi":"でぃ","dhu":"でぅ","dhe":"でぇ","dho":"でぉ",
    "tyi":"ちぃ","tye":"ちぇ",
    "thi":"てぃ","the":"てぇ",

    # small vowels (x- or l- prefix)
    "xa":"ぁ","xi":"ぃ","xu":"ぅ","xe":"ぇ","xo":"ぉ",
    "la":"ぁ","li":"ぃ","lu":"ぅ","le":"ぇ","lo":"ぉ",
    # small tsu
    "xtu":"っ","ltu":"っ",
    # small ya/yu/yo
    "xya":"ゃ","xyu":"ゅ","xyo":"ょ",
    "lya":"ゃ","lyu":"ゅ","lyo":"ょ",
    # small wa
    "xwa":"ゎ","lwa":"ゎ",
}

class input_session:
  def __init__(self):
    self.input = ''
    self.hiragana = ''
    self.d_buffer = ''
    self.col = 0
    self.col_d = 0
    self.result = ''
    self.buffer=''
    self.MODE_HIRAGANA = 1
    self.MODE_HENKAN = 2
    self.mode = self.MODE_HIRAGANA
    self.word_index = 0
                
  def next_result(self, direction = 1):
    if self.word_index == len(self.t_result):
      self.word_index = 0
    word = self.t_result[self.word_index]
    if direction == 1:
      first_item = word[1].pop(0)
      word[1].append(first_item)
    else:
      last_item = word[1].pop()
      word[1].insert(0, last_item)
    self.t_result[self.word_index] = word
    
  def reset_input(self):
    self.input = ''
    self.mode = self.MODE_HIRAGANA
    self.hiragana = romaji_to_hiragana(self.input)
    self.col = len(self.hiragana)
    self.col_d = get_utf8width(self.hiragana)
    self.d_buffer = self.hiragana
    self.buffer = self.hiragana
        
    
  def feed_key(self, keys):
    result = ''
    if keys == b'\x08':
      if self.mode == self.MODE_HIRAGANA:
        self.input = self.input[:-1]
      if self.mode == self.MODE_HENKAN:
        self.mode = self.MODE_HIRAGANA
    elif keys == b'\x1b[D': # LEFT
      if self.mode == self.MODE_HENKAN and self.word_index > 0:
        self.word_index -= 1
    elif keys == b'\x1b[C': # RIGHT
      if self.mode == self.MODE_HENKAN and self.word_index < len(self.t_result):
        self.word_index += 1
    elif keys == b'\x1b[A': # TOP
      if self.mode == self.MODE_HENKAN:
        self.next_result(-1)
    elif keys == b'\x1b[B': # DOWN
      if self.mode == self.MODE_HENKAN:
        self.next_result()
    elif keys == b' ':
      if self.mode == self.MODE_HIRAGANA:
        if len(self.hiragana) > 0:
          self.t_result = google_transliterate(self.hiragana)
        else:
          return result
        if self.t_result == None:
          return result
        #print(self.t_result)
        self.word_index = len(self.t_result)
        #self.d_buffer = get_henkan_result(self.t_result, self.word_index)
        #self.buffer = get_henkan_result(self.t_result, self.word_index, False)
        self.mode = self.MODE_HENKAN
      elif self.mode == self.MODE_HENKAN:
        self.next_result()
      #return result
    elif keys == b'\r' or keys == b'\x0a':
      if self.mode == self.MODE_HIRAGANA:
        result = self.hiragana
        self.reset_input()
      if self.mode == self.MODE_HENKAN:
        self.reset_input()
        return get_henkan_result(self.t_result,0, False, False)
    elif keys[0] < 0x20:
      return result
    else:
      if self.mode == self.MODE_HIRAGANA:
        self.input += keys.decode('utf-8')
      if self.mode == self.MODE_HENKAN:
        self.input = ''
        self.input += keys.decode('utf-8')
        result = get_henkan_result(self.t_result,0, False, False)
        self.mode = self.MODE_HIRAGANA
        

    if self.mode == self.MODE_HIRAGANA:
      self.hiragana = romaji_to_hiragana(self.input)
      self.col = len(self.hiragana)
      self.col_d = get_utf8width(self.hiragana)
      self.d_buffer = self.hiragana
      self.buffer = self.hiragana
    if self.mode == self.MODE_HENKAN:
      self.d_buffer = get_henkan_result(self.t_result, self.word_index)
      self.buffer = get_henkan_result(self.t_result, self.word_index, False)
      self.col = len(self.buffer)
      self.col_d = get_utf8width(self.buffer)
    return result
    
def get_henkan_result(result, word_index, color = True, space = True):
  out=''
  idx = 0
  #print(f'word_index{word_index}, len({len(result)})')
  for word in result:
    if word_index == idx:
      if color:
        out += '[' + el.set_font_color(7) + word[1][0] + el.set_font_color(0) + ']'
      else:
        if space:
          out += '[' + word[1][0] + el.set_font_color(0) + ']'
        else:
          out += word[1][0]
      #out += '[' + word[1][0] + ']' 
    else:
      out += word[1][0] 
    idx += 1
  return out

station = network.WLAN(network.STA_IF)


def romaji_to_hiragana(text):
    if not station.isconnected():
      return text
  
    #text = text.lower()
    i = 0
    result = ""
    while i < len(text):
        # Handle double consonant (sokuon)
        if (i+1 < len(text) 
          and text[i] == text[i+1]
          and text[i] not in "aeioun.,-"):
            result += "っ"
            i += 1
        # Try 3 letters (e.g. "kyo")
        if i+3 <= len(text) and text[i:i+3] in ROMAJI_TABLE:
            result += ROMAJI_TABLE[text[i:i+3]]
            i += 3
        # Try 2 letters (e.g. "ka")
        elif i+2 <= len(text) and text[i:i+2] in ROMAJI_TABLE:
            result += ROMAJI_TABLE[text[i:i+2]]
            i += 2
        # Try 1 letter (e.g. "a")
        elif text[i] in ROMAJI_TABLE:
            result += ROMAJI_TABLE[text[i]]
            i += 1
        else:
            # Unknown character, keep as-is
            result += text[i]
            i += 1
    return result


def google_transliterate(input_text):
    host = "www.google.com"
    port = 80
    path = "/transliterate?langpair=ja-Hira|ja&text=" + input_text
    try:
      # Build HTTP request
      request = "GET {} HTTP/1.0\r\nHost: {}\r\n\r\n".format(path, host)

      # Open socket
      addr = socket.getaddrinfo(host, port)[0][-1]
      s = socket.socket()
      s.connect(addr)
      s.send(request.encode())

      # Receive response
      response = b""
      while True:
        data = s.recv(512)
        if not data:
          break
        response += data
      s.close()

      # Split header and body
      response = response.decode("utf-8")
      body = response.split("\r\n\r\n", 1)[1]

      # Parse JSON
      return json.loads(body)
    except Exception as e:
      print("Network error")
      return None

el = elib.esclib()

def get_utf8width(s):
  total = 0
  for ch in s:
    if ord(ch) > 0x80:
      total += 2
    else:
      total += 1
  return total


