--------------
This is an instruction of output format for automation.

## MicroPython format rule

- You must follow development guide.
- MicroPython's Tab width is 2.

## MicroPython code with filename

You must specify filename at the first line of the code block. e.g.,

'''python
# test.py
def main(vs, args):
  print("hello world", file=vs)
'''

Then the program that called the API will save the coding block in /sd/py/tmp. The first line is used for the file name. This is part of sys.path so you can execute the module for automation.

## Python module and command execution

If you want to execute the created MicroPython module or any existing module, you can specify as the following:

'''command
test
'''

This will execute `test` module that you created in the previous section. This can be existing Pocketdeck commands or apps such as analog_clock or ls.

For the command reference, check README.md.


-------------- end of instruction


