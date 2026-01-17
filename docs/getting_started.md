# Pocket deck: Getting started

Welcome to Pocket deck!

Here is the getting started guide.

## The first document

When you power on the device, home app will be shown up. Select 'Launch apps', and select Pem editor to launch text editor.

Another way to launch application is from command line. Switch the virtual screen to screen 2 by pressing `<` or `>` touch pad, then type the following command:

`pem journal.md`

The first word means the command name. `pem` is the name of the editor. The second word means the filename, it could be any filename such as test.txt.. 'md' means Markdown. Editor will be launched.

If you want to launch another command line shell in other virtual screen, use `cmd` command. For example:

`cmd 3`

to launch another command line shell in screen 3.


## PEM editor

PEM editor key bindings are influenced by Emacs editor, the key bind is unique. See pem_readme.md for full information. Here is basic commands:

`C-x` `C-c` : Quit
`C-x` `C-f` : Open file
`C-x` `C-s` : Save file
`C-x`  `b` : Switch between files
`C-x` `k` : Close the current file
`C-k` : Delete to the end of the line and save it to yank buffer
`C-y` : paste yank buffer

For example, Ctrl-x then Ctrl-f to open new file.
To quit the editor, C-x followed by C-c.

## Virtual screens and the other applications

Pocket deck has 10 virtual screens. Here are the command to switch between screens.

- `C-[0-9]` : (Control + 0-9) Switch screen
- `C-Left` or `C-Right`, or left or right touch button on the device : Switch to next or previous screen

Let's create another command shell. Type the following command:

`cmd 3`

'cmd' will launch another shell on the specified screen number. In this case it's screen 3. You can switch back to screen 2 by pressing C-Left or left button on the device. Let's type 'ls' command to show the list of the file in screen 3:

`ls`

Let's launch clock and calendar app. Type the following command on screen 3.

`analog_clock`

You will see analog clock and a calendar.

If you press 'c', then current date will be copied to system clipboard. You can paste it to editor by S-C-v(Shift-Ctrl-V).


## File sync with google drive

TBD

## Other applications

- gpt is an application to talk ChatGPT. You need to modify the code to put your API key.
