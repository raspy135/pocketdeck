import io

class mock_stream(io.IOBase):
  def __init__(self, initial=b""):
    self._buffer = bytearray(initial)
    self._wbuffer = bytearray()

  def read(self, n=-1):
    if n is None or n < 0:
      n = len(self._buffer)
    n = min(n, len(self._buffer))
    data = bytes(self._buffer[:n])
    del self._buffer[:n]
    return data

  def readinto(self, b):
    n = min(len(b), len(self._buffer))
    b[:n] = self._buffer[:n]
    del self._buffer[:n]
    return n

  def write(self, data):
    if isinstance(data, str):
      data = data.encode()
    self._wbuffer.extend(data)
    return len(data)

  def peek(self, n=1):
    return bytes(self._buffer[:n])

  def available(self):
    return len(self._buffer)

  def clear(self):
    self._buffer.clear()
    self._wbuffer.clear()

  def __len__(self):
    return len(self._buffer)

  def get_wbuffer(self):
    return self._wbuffer
    
