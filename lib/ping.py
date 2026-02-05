import uping
import pdeck

#import pdeck_utils as pu

#pu.reimport('uping')


def main(vs,args):
  if len(args) == 2:
    uping.ping(args[1], vs = vs)
    #print(args)
    
