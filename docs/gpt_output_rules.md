# Important information

This is an instruction of output format for AI automation. **You must follow the instruction in the file**

## MicroPython format rule

- You must follow development guide(app_development.md).
- /sd/lib/analog_clock.py is a good reference to understand how to write a graphics application in Pocket Deck.
- /sd/lib/ls.py is a good reference of CLI app.
- You must use vs to print output. For example:
```
print('hello', file=vs)
```
Otherwise, the output goes to screen 0.
- if you want to check existing apps, /sd/lib is where system apps are, and /sd/lib/noa is for libraries.
- You should use argparse module when it's needed. 
- IMPORTANT: MicroPython's Tab width must be 2. 

## working folder

You must use /sd/work to store temporarily files.

## Python folder

- /sd/lib is for system apps. You must put python code under /sd/py unless user tell you to do.


