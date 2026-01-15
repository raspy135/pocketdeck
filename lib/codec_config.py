from machine import Pin,I2C,I2S

class codec_config:
  def __init__(self):
    self.address = 0x18
    
    self.ic = I2C(0, scl = Pin(10), sda = Pin(11), freq=800000)
    
  def set_vol(self,val):
    a = bytearray(1)
    a[0] = val
    a = bytes(a)
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    self.ic.writeto_mem(self.address, 0x41, a)
    self.ic.writeto_mem(self.address, 0x42, a)
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
  def get_vol(self):
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    val = self.ic.readfrom_mem(self.address, 0x41,1)[0]
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    return val
    

  def set_hpgain(self,val):
    a = bytearray(1)
    a[0] = val
    a = bytes(a)
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    self.ic.writeto_mem(self.address, 0x10, a)
    self.ic.writeto_mem(self.address, 0x11, a)
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
  def set_monitorgain(self,val):
    a = bytearray(1)
    a[0] = val
    a = bytes(a)
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    self.ic.writeto_mem(self.address, 0x16, a)
    self.ic.writeto_mem(self.address, 0x17, a)
    self.ic.writeto_mem(self.address, 0x0, b'\x00')

  def get_micgain(self):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    val = self.ic.readfrom_mem(self.address, 0x3b, 1)[0]
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    return val
    
  def set_micgain(self,val):
    a = bytearray(1)
    a[0] = val
    a = bytes(a)
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    self.ic.writeto_mem(self.address, 0x3b, a)
    self.ic.writeto_mem(self.address, 0x3c, a)
    self.ic.writeto_mem(self.address, 0x0, b'\x00')

  def get_lo(self):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    val = self.ic.readfrom_mem(self.address, 0x0e, 1)[0]
    #print(f"lo = {val}")
    
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    ret = True if val != 0 else False
    return ret

  def toggle_lo(self,val):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    if val:
      self.ic.writeto_mem(self.address, 0x0e, b'\x08')
      self.ic.writeto_mem(self.address, 0x0f, b'\x08')
    else:
      self.ic.writeto_mem(self.address, 0x0e, b'\x00')
      self.ic.writeto_mem(self.address, 0x0f, b'\x00')
    self.ic.writeto_mem(self.address, 0x0, b'\x00')

  def toggle_li(self,val):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    if val:
      self.ic.writeto_mem(self.address, 0x34, b'\x80')
      self.ic.writeto_mem(self.address, 0x36, b'\x80')
    else:
      self.ic.writeto_mem(self.address, 0x34, b'\x20')
      self.ic.writeto_mem(self.address, 0x36, b'\x20')
    self.ic.writeto_mem(self.address, 0x0, b'\x00')

