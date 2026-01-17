
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

PEM has an unique concept called jump history. It records the cursor position when you jump (by searching, go to line, etc.). You can go back previous positions when you need.

- `M-;` : Jump history walking backward
- `M-'` : Jump history walking forward
- `M-SPACE` : Manually mark the position

### Completion and symbol reference

It has basic symbol completion, only available with Python mode. Python mode is activated when it opens with .py extension.

- `TAB` : Perform completion
- `M-.` : Trying to find a definition of the symbol at the cursor. (Simply it will find "def " + symbol.
- `M-/` : Start search with the symbol at the cursor.


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
