import re

def findall(regex, text):
  while True:
    match = regex.search(text)
    if not match:
      break
    yield match.group(0)
    text = text[match.end():]

