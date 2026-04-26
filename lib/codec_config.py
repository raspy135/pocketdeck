from machine import Pin,I2C,I2S
import math
import time

class codec_config:
  def __init__(self):
    self.address = 0x18
    
    self.ic = I2C(0, scl = Pin(10), sda = Pin(11), freq=800000)

    # Coefficient offsets within a biquad block
    self.coef_offsets = {'N0': 0, 'N1': 4, 'N2': 8, 'D1': 12, 'D2': 16}
    
    # Page and Base Register mapping for DAC Channels
    # PRB-R8 has 3 biquads: A, B, C
    self.biquad_map = {
        'L': {'page': 44, 'base': 12},
        'R': {'page': 45, 'base': 20}
    }
    
  def get_input_mixer(self):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    val = self.ic.readfrom_mem(self.address, 0x18,1)[0]
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    return val
    
  def set_input_mixer(self,val):
    a = bytearray(1)
    a[0] = val
    a = bytes(a)
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    # 0 = 0.0dB
    # 1 = -0.4dB
    # 0x28 = MUTE
    if a[0] > 0x28:
      a[0] = 0x28
    self.ic.writeto_mem(self.address, 0x18, a)
    self.ic.writeto_mem(self.address, 0x19, a)
    if a[0] != 0x28:
      a = bytearray(1)
      a[0] = 0xa
      a = bytes(a)
      self.ic.writeto_mem(self.address, 0x0c, a)
      self.ic.writeto_mem(self.address, 0x0d, a)
    else:
      a = bytearray(1)
      a[0] = 0x8
      a = bytes(a)
      self.ic.writeto_mem(self.address, 0x0c, a)
      self.ic.writeto_mem(self.address, 0x0d, a)
      
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    


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

  def get_li(self):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    val = self.ic.readfrom_mem(self.address, 0x34, 1)[0]
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    #print(f"val{val}")   
    if val == 0xC0:
      return True
    else:
      return False
    
  def toggle_li(self,val):
    self.ic.writeto_mem(self.address, 0x0, b'\x01')
    if val:
      # Enable line in (In 1)
      self.ic.writeto_mem(self.address, 0x34, b'\xC0')
      self.ic.writeto_mem(self.address, 0x37, b'\xC0')
      self.ic.writeto_mem(self.address, 0x33, b'\x00')
    else:
      # Enable Microphone (In 2)
      self.ic.writeto_mem(self.address, 0x34, b'\x30')
      self.ic.writeto_mem(self.address, 0x37, b'\x30')
      self.ic.writeto_mem(self.address, 0x33, b'\x00')
      
    self.ic.writeto_mem(self.address, 0x0, b'\x00')

  def set_agc(self, enabled, target_level_db=-12):
    """
    Configures AGC (Auto Gain Control) for ADC.
    target_level_db: -5.5, -8, -10, -12, -14, -17, -20, -24
    """
    # Page 0, Reg 86/91: AGC Control 1
    # D7: Enable, D6-D4: Target Level
    targets = {
        -5.5: 0x00, -8.0: 0x10, -10.0: 0x20, -12.0: 0x30,
        -14.0: 0x40, -17.0: 0x50, -20.0: 0x60, -24.0: 0x70
    }
    
    # Simple nearest-match for dB
    best_match = -12.0
    min_diff = 100.0
    for t in targets.keys():
      diff = abs(target_level_db - t)
      if diff < min_diff:
        min_diff = diff
        best_match = t
    
    val = targets[best_match]
    if enabled:
      val |= 0x80
      
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    self.ic.writeto_mem(self.address, 86, bytes([val]))
    self.ic.writeto_mem(self.address, 94, bytes([val]))
    
    if enabled:
      # Max Gain (Reg 88/96): 0-0x77 (0 to 59.5dB). Default 40dB (0x50)
      max_gain = bytes([0x50])
      self.ic.writeto_mem(self.address, 88, max_gain)
      self.ic.writeto_mem(self.address, 96, max_gain)
      # Attack Time (Reg 89/97): Default ~20ms (0x02 for 32kHz sample rate)
      self.ic.writeto_mem(self.address, 89, b'\x02')
      self.ic.writeto_mem(self.address, 97, b'\x02')
      # Decay Time (Reg 90/98): Default ~500ms (0x10)
      self.ic.writeto_mem(self.address, 90, b'\x10')
      self.ic.writeto_mem(self.address, 98, b'\x10')
      
  def get_agc(self):
    """Returns (enabled, target_db)"""
    self.ic.writeto_mem(self.address, 0x0, b'\x00')
    val = self.ic.readfrom_mem(self.address, 86, 1)[0]
    enabled = (val & 0x80) != 0
    bits = val & 0x70
    targets_inv = {
        0x00: -5.5, 0x10: -8.0, 0x20: -10.0, 0x30: -12.0,
        0x40: -14.0, 0x50: -17.0, 0x60: -20.0, 0x70: -24.0
    }
    target_db = targets_inv.get(bits, -12.0)
    return enabled, target_db

  def set_pass_through(self, biquad_idx='A'):
    self.set_filter_raw(1.0, 0, 0, 0, 0, biquad_idx=biquad_idx)

  def set_lpf(self, cutoff_freq, q=0.707, sample_rate=44100, biquad_idx='A'):
    """Configures specified Biquad as a Low-Pass Filter (2nd Order)."""
    b0, b1, b2, a1, a2 = self._calc_lpf_coeffs(cutoff_freq, sample_rate, q)
    # Hardware eqn: y[n] = N0*x[n] + N1*x[n-1] + N2*x[n-2] + 2*D1*y[n-1] + D2*y[n-2]
    # Testing 1x Numerator scaling to fix volume drop
    self.set_filter_raw(b0, b1, b2, -a1/2.0, -a2, biquad_idx=biquad_idx)

  def set_lpf_1st(self, cutoff_freq, sample_rate=44100, biquad_idx='A'):
    """Configures specified Biquad as a 1st Order LPF (Ultra-Stable)."""
    # H(z) = (1-a) / (1 - a*z^-1) => y[n] = (1-a)x[n] + a*y[n-1]
    a = math.exp(-2.0 * math.pi * cutoff_freq / sample_rate)
    self.set_filter_raw(1.0 - a, 0, 0, a/2.0, 0, biquad_idx=biquad_idx)

  def set_hpf(self, cutoff_freq, q=0.707, sample_rate=44100, biquad_idx='A'):
    """Configures specified Biquad as a High-Pass Filter (2nd Order)."""
    b0, b1, b2, a1, a2 = self._calc_hpf_coeffs(cutoff_freq, sample_rate, q)
    # Hardware eqn: y[n] = N0*x[n] + 2*N1*x[n-1] + N2*x[n-2] + 2*D1*y[n-1] + D2*y[n-2]
    # We halve b1 and a1 to account for the hardware 2x multiplier.
    self.set_filter_raw(b0, b1/2.0, b2, -a1/2.0, -a2, biquad_idx=biquad_idx)

  def set_hpf_1st(self, cutoff_freq, sample_rate=44100, biquad_idx='A'):
    """Configures specified Biquad as a 1st Order HPF."""
    # H(z) = (1+a)/2 * (1-z^-1) / (1-a*z^-1)
    # y[n] = (1+a)/2 * x[n] - (1+a)/2 * x[n-1] + a * y[n-1]
    a = math.exp(-2.0 * math.pi * cutoff_freq / sample_rate)
    # n1 must be halved here because hardware multiplies it by 2.
    # desired n1 = -(1+a)/2, so pass -(1+a)/4.
    self.set_filter_raw((1.0 + a) / 2.0, -(1.0 + a) / 4.0, 0, a / 2.0, 0, biquad_idx=biquad_idx)

  def set_filter_raw(self, n0, n1, n2, d1, d2, biquad_idx='A'):
    """Writes raw floating point coefficients to hardware registers N0, N1, N2, D1, D2."""
    # 1. Power down DACs (Page 0, Reg 63)
    self.ic.writeto_mem(self.address, 0x00, b'\x00')
    pwr = self.ic.readfrom_mem(self.address, 0x3f, 1)[0]
    self.ic.writeto_mem(self.address, 0x3f, bytes([pwr & 0x3F]))

    # 2. Convert and write raw registers in 1.23 format
    # AIC3204 hardware expects N0, N1, N2, D1, D2
    # Note: Coefficients that go through the hardware 2x multiplier (N1, D1) 
    # must be halved BEFORE calling this method to maintain unity gain.
    coeffs = {
        'N0': self._float_to_coeff_int(n0),
        'N1': self._float_to_coeff_int(n1),
        'N2': self._float_to_coeff_int(n2),
        'D1': self._float_to_coeff_int(d1),
        'D2': self._float_to_coeff_int(d2)
    }

    for name, val in coeffs.items():
      self._write_coefficient_24bit('L', biquad_idx, name, val)
      self._write_coefficient_24bit('R', biquad_idx, name, val)

    # 3. Restore DAC Power
    self.ic.writeto_mem(self.address, 0x00, b'\x00')
    self.ic.writeto_mem(self.address, 0x3f, bytes([pwr]))
    time.sleep_ms(10)

  def _calc_lpf_coeffs(self, fc, fs, q):
    """Calculates 2nd-order LPF coefficients."""
    omega = 2.0 * math.pi * fc / fs
    sn, cs = math.sin(omega), math.cos(omega)
    alpha = sn / (2.0 * q)
    a0 = 1 + alpha
    return (1-cs)/(2*a0), (1-cs)/a0, (1-cs)/(2*a0), (-2*cs)/a0, (1-alpha)/a0

  def _calc_hpf_coeffs(self, fc, fs, q):
    """Calculates 2nd-order HPF coefficients."""
    omega = 2.0 * math.pi * fc / fs
    sn, cs = math.sin(omega), math.cos(omega)
    alpha = sn / (2.0 * q)
    a0 = 1 + alpha
    return (1+cs)/(2*a0), -(1+cs)/a0, (1+cs)/(2*a0), (-2*cs)/a0, (1-alpha)/a0

  def _float_to_coeff_int(self, val):
    # Convert float to 24-bit 1.23 signed integer.
    scaled = int(val * (2**23))
    if scaled > 8388607: scaled = 8388607
    elif scaled < -8388608: scaled = -8388608
    return scaled & 0xFFFFFF

  def _write_coefficient_24bit(self, channel, biquad_idx, coef_name, val):
    # Writes a 24-bit coefficient to 3 consecutive registers.
    # AIC3204 Biquads are 20 bytes (5 coeffs * 4 bytes) apart
    biquad_offset = (ord(biquad_idx) - ord('A')) * 20
    
    m = self.biquad_map[channel]
    reg = m['base'] + biquad_offset + self.coef_offsets[coef_name]
    self.ic.writeto_mem(self.address, 0x00, bytes([m['page']]))
    # AIC3204 expects MSB first (Big-Endian) in consecutive registers
    self.ic.writeto_mem(self.address, reg, bytes([(val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF]))

