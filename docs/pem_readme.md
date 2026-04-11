
# PEM editor

PEM edit is designed for Pocket deck system, 100% written by MicroPython, good fit for monochrome display.

## Features

- Multiple file editing
- UTF8 support
- Line wrap
- Emacs-like key bindings
- Incremental search and replace
- Jump history (Like browser's back/forward buttons)
- Yank (Kill ring, works like copy & paste buffer)
- Completion
- Compact design for small display

## Command line options

```
pem [options] filename
```

`-j` loads Japanese(CJK) font when launching the app. 

## Auto resume

Pem has auto resume feature, it will load the last edited file at launch. To disable the feature, change `resume_last_file` parameter to False in pem_keymap.py. See `Customizing` section for detail.

## Reference

- `C-x` means press Control + x
- `M-x` means press Escape then x or ALT + x
- `C-x` `y` means press Control + x then press y

### File / system

It can open multiple files.

- `C-x` `C-c` : Quit
- `C-x` `C-f` : Open file
- `C-x` `C-s` : Save file
- `C-x` `b` : Switch between files
- `C-x` `k` : Close the file
- `C-g`: Cancel operation (**Important!**)

**Move cursor**

You can move cursor just as normal editor.

- `C-p`  : Up
- `C-n` : Down
- `C-b` : Left
- `C-n` : Right
- `C-a` : The beginning of the line
- `C-e` : The end of the line
- `C-j` : enter
- `M-<` : Top of the file
- `M->` : End of the file
- `M-g` : Go to line number

### Yanking

PEM has similar concept of Eamcs's Yanking (Kill ring). It can be used like instant copy & paste buffer. Main difference is you need to delete the characters to store it to Yank buffer. See Emacs' manual or tutorial for detail. It stores 20 buffer.

- `C-k` : Delete chars to the end of the line, and store it to Yank buffer.
- `Del` or `C-d`: Delete one char and store it to Yank buffer. (So del, del, del, del.. then `C-y` can restore the deletion)
- `C-y` : Yank (Paste the latest buffer)
- `M-y` : Open Yank list
- `C-c v` : Copy system clipboard to yank buffer.  It's useful when copy long data.

In yank list,

- `Up`/`Down` : Move the list
- `Enter` : Select the list
- `C-g` or `q` : Quit the selection mode

### Search

Search is incremental.

- `C-s` : Start search, pressing `C-s` one more time to recall last search
- `C-r` : Start reverse search

In search mode,

- `C-s` : Go next match
- `C-r` : Go previous match
- `C-g` or arrow keys : Quit search mode

### Replace

- `M-%` : Replace

### Jump history

PEM has an unique concept called jump history. It records the cursor position when you jump (by searching, go to line, etc.). You can go back previous positions when you need. It acts like web browser's back and forward.

- `M-;` : Jump history walking backward
- `M-'` : Jump history walking forward
- `M-SPACE` : Manually mark the position

### Completion and symbol reference

It has basic symbol completion, only available with Python mode. Python mode is activated when it opens with .py extension. In markdown mode, `M-.` works as jumping to linked document.

- `TAB` : Perform completion
- `M-.` : In Python mode, the command tries to find a definition of the symbol at the cursor. (Simply it will find "def " + symbol. In Markdown mode, jumping to the link. For example, if you press `M-.` on the link `[[pem_readme]]`, pem_readme will be opened.
- `M-/` : Start search with the symbol at the cursor.

## Loading file from other applications

pem module has a list called `open_pending_list` and it is used to load files from other applications.

```python
import pem
# This will open test.md in the existing PEM instance. Arduments are `[filename, line_number, column_number]`. line and column numbers are 1-based.
pem.open_pending_list.append(['test.md',1,1])
```

## Customizing

Pem has a config file, and this is located at /sd/lib/pem_keymap.py. 

If you want to customize keymap or some settings, copy the file under /sd/py. /sd/py has a priority over /sd/lib.

init_custom() is called at initialization. km stores pem_keymap_default module instance.

Here is an example to change some key mapping

```python
def init_custom(km):
  # remove Ctrl-f from right
  km.map['right'] = [ b'\x1b[C' ]
  # Change search shortcut to Ctrl-f
  km.map['search'] = [  b'\x06' ]
```

## Japanese input

Japanese input is support when WiFi is connected.

- `Kana`-key or Alt-` to enable Japanese input.

Pocket Deck uses Google Japanese input API as input engine. Currently it only supports US keyboard and Romaji input. Key binding follows standard.

- `Space` : Start conversion
- `Left` and `Right` key : Move between word
- `Up` and `Down` key : Change to another result

Moving word splitting point is not possible after starting conversion. Normally Google Japanese input API is smart enough to understand word separation, however, if you want to make sure the word splitting point, you can specify it by inputting ",," as a splitter.

```
kokode,,hakimonowo,,nuidekudasai.
(You may still need to edit the conversion result but word splitting is controlled.)
kokodeha,,kimonowo,,nuidekudasai.

```
