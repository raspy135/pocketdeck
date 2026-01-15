import time

class benchmark:

  def __init__(self,enabled):
    self.enabled = enabled
    
  def start_bench(self):
    if not self.enabled:
      return
    print('-------start------')
    self.tss=[]
    self.add_bench('start')

  def add_bench(self,label):
    if not self.enabled:
      return
    self.tss.append([label,time.ticks_us()])
    
  def print_bench(self):
    if not self.enabled:
      return
    self.tss.append(['end',time.ticks_us()])
    for i in range(1, len(self.tss)):
      diff = self.tss[i][1] - self.tss[i-1][1]
      print(f'{self.tss[i][0]}:{diff}')
    print(f'Total:{self.tss[-1][1] - self.tss[0][1]}')  

