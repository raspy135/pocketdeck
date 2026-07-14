# Pocket Deck

Pocket Deck is a tiny, customizable computer designed for everyday productivity and creative tinkering. It's great for fast text writing, personal organization, and small life-improvement utilities. 

And the applications are not limited to writing, it is capable doing graphics and music applicaitons.

Powered by MicroPython, it offers a powerful API, responsive graphics, and high-quality audio so you can build and tailor features to fit your workflow wherever you are.

![Product image](../images/pocketdeck.jpg)

# Purchase

https://shop.nunomo.net

# Emulator

There are some limitations, but you can try Pocket Deck here:
https://pdemulator.nunomo.net/emulator/

# Features

## Hardware

- WiFi and Bluetooth for connectivity.
- Touch pad and touch buttons (AVR128 as a sub processor for touch inputs)
- Stereo Audio codec
- Stereo built-in speaker
- Stereo MEMS Microphone
- LEDs
- SD card slot (Tested up to 128GB, technically you can go more)
- Expansion port
- USB-A for USB keyboard, and USB-C for charging.
- RTC clock to keep date and time
- 8 pin external port (2 pins are available for I/O)

## Accessaries

### USB keyboard & cable (Required)

You need USB keyboard and cable to operate the device.

### LiPo battery (Optional, recommended)

There is JST-PH connector on the main PCB. You can install LiPo battery. Around 3000mAh to 5000mAh is recommended.

3700mAh is good balance of weight and capacity.
https://a.co/d/0eiQML2P
5000mAh is for multi-days use.
https://a.co/d/00tRmMza

Battery operation is recommended.

### Magsafe stand (Optional, recommended)

Putting Magsafe sticker at back makes the device much more convenient. Put Magsafe sticker at the back. Position should be at top-center. There is a WiFi anntena at the botttom of the unit. Avoid to put the sticker at the bottom.

### Disassemble process

Following example is disassemble process to install LiPo battery.

1. Remove three screws on the top plate.

2. Remove front panel. Front panel and main panel are conntected by 0.1 inch pins. You can just pull the panel.

3. Remove main board. The board is just sitting on the case, no screws. Use SD slot or the other holes at the side of the case to get some leverage.

4. Install LiPo battery that you have. Preferrably use some double-sided tape to stick the battery.

5. Install the main board. There is a hole at the  right side for Lipo Battery cable.

6. Connect LiPo battery cable to the main panel. It's JST-PH connector. ** Check polarity of the battery before you connect it! There is no standard polarity in LiPo batteries, so it could be opposite. There are "+" and "-" marks on the PCB board. **

7. Install the front panel. Make sure to align pin headers.

8. Put on screws.

## Expansion port

Pocket deck has 8-pin expansion port. Pin layout is the following:

`GND EVENT IO13 IO6 NC NC 3.3V 5V`

IO13 and IO6 is free to use from Micrppython. Event is high when touch buttons are pressed.


## Software overview

- A powerful text editor 100% written by MicroPython. See [[pem_readme.md]] for detail.
- Some utilities written by MicroPython, such as journal to chart, clock, calendar and kitchen timer.
- Graphics and audio modules for optimized performance written by C.
- Powerful terminal which supports a lot of escape sequence. This enables practical SSH experience.

- Powerful audio engine, core is written by C for performance.
  - Stream, Sampler and Wavetable
  - Filter, Compressor, Delay and Reverb
  - Flexible routing
  - Tidal Cycles/Strudel inspired frontend sequencer gives flexible music sequencing, sample accurate timings

- Up to 10 virtual screens. You can use them for multi-tasking, for example:
  - Screen 1: Micropython interactive shell(REPL)
  - Screen 2: Command line terminal
  - Screen 3: Text editor for jornaling or programming
  - Screen 4: Clock and calendar.
  - Screen 5: Game
  - Screen 6: Music player
  - Screen 7: SSH to your Linux computer
  - Screen 10: Home app

Screen 1,2 and 10 is permanently assigned for REPL, command line and Home app

## Touch buttons, power button and LEDs

Pocket deck has touch buttons on the front panel.

Button names | Description
-----|-----
Up, Down, Right and Left | It works as arrow keys. Arrow keys also can be used as like a dial by circling finger, if the application supports it. See get_tp_keys() for detail.
A | Enter
B | Backspace
Square shaped button (Left) | mouse left button if the app supports it
Square shaped button (Right) | mouse right button if the app supports it
touch pad | This can be used as a touch pad (mouse) if the application supports it.
`<` | Go to previous screen
`>` | Go to next screen
Slide bar at the right side | It scrolls the terminal screen to see previous messages. If the terminal sets as raw mode (esclib.raw_mode(True)), it works as Up/Down keys. 

Pocket deck has LEDs on the left side and it can be used for status indications.

- The 4 LEDs on the first row indicates battery status with LiPo battery connected.
- The red LED on the second row blinks when there is new output to Python REPL (screen 1).
- The leftmost LED on the third row indicates netowrk status. It will be on when it's connected.
- The rest 3 LEDs are for applications, can be controlled via Python.

There is a power button next to touchpad.

Press the button one time to power up the device with Lipo battery. It's always on when it's connected to power supply.

Press the button two times (like double click) to shutdown the device.



## System shortcuts

- C-[0-9] : (Control + 0-9) Switch screen
- C-Left or C-Right or left or right touch button on the device : Switch to next or previous screen
- C-Up or C-Down : Scroll on console
- S-C-q : Forcefully quit the running application. You should avoid this as much as possible, because all applications are not protected like normal OSes such as Linux. For graphics application, try S-C-d first.
- S-C-r : (Shift + Control + R) Restart the device
- S-C-i : Invert color of the screen
- S-C-d : Detatch screen (Suspend application) for graphical application. It's useful when the application is out of control due to bug or any reasons. Safer than Ctrl-C.
- S-C-= : Increase font size. Unless the application has a logic to react the font size change, normally restarting application is necessary.
- S-C-- : Decrease font size.
- S-C-c : Copy current line to system clipboard. This is useful with text applications.
- S-C-v : Paste data from system clipboard

### App-defined shortcuts (Slider + key)

Apps can register their own global shortcut: **hold the touch slider** and then press a second key (A, B, a D-pad direction, or a bottom button). The slider acts as a modifier (like Fn). These shortcuts work **even when the app that registered them is in the background**.

For example, gpt_rt registers **Slider + A** to mute/unmute the microphone from
any screen. See `register_shortcut()` in app_development.md for how to add one.

## Locking the device

Pocket deck can be locked with a numeric PIN. The lock is handled by the firmware, so while locked the screen cannot be switched and the system shortcuts (restart, quit, etc.) are disabled until the correct PIN is entered.

- Lock from the command line: `lock 0912` sets the PIN to `0912` and locks; later `lock` locks again using the stored PIN.
- Lock from the Home app: **System → Lock device**. Set or change the PIN with **System → Set / change PIN**.
- From Python / REPL: `pdeck.lock('0912')` to set the PIN and lock, or `pdeck.lock()` to lock with the stored PIN.

Entering the PIN on the lock screen:

- **USB keyboard**: type the digits. The device unlocks automatically as soon as the right number of digits is entered — no Enter needed. Backspace edits.
- **Touchpad** as a 3×3 numpad: top row `7 8 9`, middle row `4 5 6`, bottom row `1 2 3`. The bottom-left square button is `0` and the **B** button is backspace.

The lock survives a reboot — if the device was locked it comes back up locked. If you forget the PIN, enter a wrong PIN 10 times: the device shows a 2‑hour countdown and, once it elapses, clears the PIN and unlocks so you can set a new one. (Note: this is a convenience lock — the SD card can still be removed physically.)

## Basic file structure

- `/` : Root folder (Internal flash)
- `/config` : Folder to store config information
- `/sd` : SD card root
- `/sd/Documents` : User documents
- `/sd/lib` : Built Python applications
- `/sd/lib/noa` : Built Python libraries
- `/sd/lib/examples` : Python application examples
- `/sd/py` : Python application folder for user apps

## Getting started

See [[getting_started.md]]

## Micropython interactive console (REPL)

Micropython interactive console (REPL) is always available on screen 1. It' great for small tasks like calculator and debugging.
Program can keep running even when the screen is not selected.


## Command Shell

- Pocket deck has a simple command shell to execute built-in commands and Python scripts.

- Only a few commands are built-in, everything else are written by Python.

command | summary
--------|---------
cmd | launch a new command shell. Syntax is 'cmd [screen_number].
ssh | ssh command. Syntax is "ssh host username password".
scp src dst | scp command. Syntax is "scp host username password copy_from copy_to". Remote path starts with ":". Example: scp 192.168.1.100 user password test.txt :/home/user/test.txt  .
Python module name or py module_name | Execute Python command. Syntax is "module_name [args] [args..]". Normally  module name is Python filename. Searching path is in sys.path list.

Here are some basic commands written by Python.

command | summary
--------|---------
ls [path] | List files. Supports wildcards (e.g. `ls *.py`). `-l` for detailed view with size and date. `-R` for recursive search, '-r' for reverse order. `-c N` to copy filename at index N to clipboard (-1 for last).
cp src dst | Copy file(s). Supports wildcards in src. `-r` for recursive copy. dst can be a directory when copying multiple files.
mv src dst | Move file
mkdir dir_name | Create a directory
rmdir dir_name | Delete a directory
head [-n N \| -c N] file [file...] | Print first lines (-n, default 10) or bytes (-c) of file(s).
tail [-n N \| -c N] file [file...] | Print last lines (-n, default 10) or bytes (-c) of file(s).
cat file | Print a file content
cd [dir] | Change working directory. Note this is global value, shared between shells and applications. The applicaitons (such as pem editor) do not know the change.
pwd | Get current working directory
lock [pin] | Lock the device. `lock 0912` sets the PIN to `0912` and locks; `lock` locks using the already-stored PIN. See "Locking the device" below.
netserver | launch network server to serve services. It provide screencast and clipboard sharing. See [[netserver/GETTING_STARTED]] for detail.
setuni | Change terminal font to CJK Unicode font,.
setjpf | Change terminal font to Japanese. It's lighter than setuni.
grep pattern [path ...] | Search text in files, Linux-like. The pattern is a **regex by default** (MicroPython's limited `re`; unsupported patterns fall back to literal match). `-F` literal/fixed-string match, `-v` invert match, `-r` recursive, `-n` line numbers, `-i` ignore case, `-l` filenames only, `-A/-B/-C N` context lines, `-c` count only, `-m N` stop after N matches, `--no-filename` hide the filename prefix, `--include .py,.md` filter by extension, `--max N` skip files larger than N bytes. (`-e`/`-E` accepted but redundant since regex is the default.)
curl [options] url | HTTP client for simple web requests. Supports `http://` and `https://`, `-L` to follow redirects (up to 5), `-m SECONDS` request timeout, `-I` HEAD request (status + headers only), `-o FILE` to save body to file, `-O` to save under the URL's filename, `-X METHOD` to choose request method, `-d DATA` to send request body (`-d @file` reads it from a file), `-A UA` to set the User-Agent, `-u user:password` for HTTP basic auth, `-i` to include response headers, `-s` for silent mode, and `-V` to show version. `-H` for header. The URL goes last.
diff [options] left right | Compare two text files. Supports unified and side-by-side views, paging, output to file, and configurable context lines.
qr [text...] | Generate and display a QR code centered on the screen. Supports `-c` to read from the clipboard.

### diff

`diff` compares two text files and shows added, removed and changed lines. By default it prints a unified view with a few context lines around each change.

```
diff [options] left_file right_file
```

Options:

- `-a` or `--all` : Show all unchanged lines in one unified output instead of compacting unchanged blocks.
- `-c N` or `--context N` : Number of context lines around each change. Default is 2.
- `-y` or `--side-by-side` : Show left and right files in side-by-side view.
- `-w N` or `--width N` : Target width for side-by-side view. By default it uses terminal width.
- `-l N` or `--lookahead N` : Anchor search window used while matching nearby changed lines. Default is 12.
- `-m` or `--more` : Pause every page and wait for a key. Press `q` to quit paging.
- `-o FILE` or `--output FILE` : Write diff output to a file instead of the terminal.
- `-p` or `--plain` : Disable syntax highlighting / terminal escape sequences.
- `--style` : Force syntax highlighting even when `-o` is used.

Examples:

```
diff old.txt new.txt
diff -y notes_before.md notes_after.md
diff -o /sd/work/readme.diff README_old.md README.md
```

In side-by-side view, `<` marks lines only on the left, `>` marks lines only on the right, and `!` marks changed lines on both sides.

### grep

`grep` searches files for lines matching a pattern, in a Linux-like way. The pattern is treated as a **regular expression by default**, using MicroPython's limited `re` module. If a pattern uses regex features that `re` does not support, grep prints a notice and falls back to a plain literal (substring) search instead of failing.

```
grep [options] pattern [path ...]
```

If `path` is omitted the current working directory is searched; several files or directories can be given. A directory is searched only at its top level unless `-r` is given. Matches are printed as `file: line`, with the filename highlighted.

Options:

- `-r` or `-R` or `--recursive` : Recurse into sub-directories.
- `-n` : Prefix each matching line with its line number.
- `-i` or `--ignore-case` : Case-insensitive match.
- `-l` : List only the names of files that contain a match (no lines).
- `-v` or `--invert-match` : Select lines that do **not** match.
- `-F` or `--fixed-strings` : Treat the pattern as a literal string, not a regex.
- `-A N` / `-B N` / `-C N` : Show N lines of context after / before / around each match. Context lines use `-` separators and `--` marks a gap between match groups.
- `-c` or `--count` : Print only a count of matching lines per file.
- `-m N` or `--max-count N` : Stop after N matching lines per file.
- `--no-filename` : Suppress the filename prefix on output lines.
- `-e` or `-E` or `--regex` : Treat the pattern as a regex. Accepted for compatibility but redundant, since regex is already the default.
- `--include EXT` : Only search files whose name ends with the given extension. Pass several comma-separated extensions to match any of them, e.g. `--include .py,.md`. This matches by file extension, not a glob pattern.
- `--max N` : Skip files larger than N bytes.

Examples:

```
grep TODO /sd/Documents
grep -rn "def .*main" /sd/py
grep -ri --include .py,.md hello /sd/Documents
grep -F "a+b" notes.txt
grep -l error /sd/logs
grep -n -C 2 "import anm" /sd/py/demo.py
grep -c TODO notes.md tasks.md
```

## SSH/SCP setup guide

See [[ssh_scp_readme]]


## Basic applications

### Setup

Setup (`setup`) configures boot sequence.

If you want to change boot sequence, execute `setup` command. It will ask initial app on boot, BLE keyboard, and network connection on boot.

Editor on boot is great for pure writing experience.


### Home app

Home app (`home`) is an app to launch apps and change settings.

- Arrow keys, Enter and BS : Navigate menu
- R bottom button in launch app list : Open application list menu. You can add, move and delete app. The data is saved in /config/apps.json. You can edit the file manually.

### Command line terminal

`cmd [screen_number]` is command line terminal.

It has powerful completion. Press TAB to open application list. TAB completion works on command, file, and command line history.


### Pem editor

Pem (`pem`) is emacs-inspired powerful editor written by Python. See [[pem_readme]] for detail. 

#### Pem remote command

`pem_open` command opens a file in existing pem application.
The syntax is the following. Line number, column nymver is an optional
```
pem_open [filename]:[line_num]:[column_num]
```
For example, the following example opens test.md, line 10.
```
pem_open test.md:10
```

### Analog clock

Analog clock (`analog_clock`) is useful application, it has analog clock, calendar and kicken timer. You can copy select date, it's useful for journaling.

- B button (BS) : Toggle timer
- C key in calendar mode : Copy selected date to clipboard (C-S-v to paste)

#### Analog clock remote command

`analog_clock_set_timer` command allows to set kitchen timer from command line.
The following example will set 10 minutes to kitchen timer.
```
analog_clock_set_timer 10
````


### Journal

Journal (`journal`) analizes journal Markdown file and visualizes to chart. Refer [[journal_readme.md]] for detail.

```
journal [file] [file..]
```

### Graph

Graph ('graph') gives Obsidian-style Markdown graph view.

- `-n` : max nodes that app reads
- `--depth` : Max depth that app reads

Operation:

- arrow keys, touchpad : Scroll screen
- Right bottom button : Re-root the node
- Left bottom button : Go to its parent node
- Enter : Open the selected file
- Ctrl-s : Incremental search. PEM (emacs) style. Ctrl-g to quit the search.

### Music

Music (`music`) is an audio player. Refer [[music_readme.md]] for detail.


### Wavplay

Wavplay (`wavplay`) is an audio player, CLI version of music. It also can play wav file when you specify path to wav file.

### wavfileplay

`wavfileplay` plays a single WAV file directly. Press any key to stop.

```
wavfileplay filename.wav
```

### recorder

`recorder` records audio to a WAV file.

```
recorder [filename] [-s sample_rate] [-l length] [-c channels] [-m]
```

- Default filename: `/sd/work/rec.wav`
- `-s`: sample rate (default 24000)
- `-l`: recording length in seconds, or minutes with `m` suffix e.g. `30m` (default 3600)
- `-c`: number of channels, 1 for mono, 2 for stereo (default 2)
- `-m`: input monitoring mode — hear mic through speaker before starting, press any key to begin recording
- Press `q` to stop recording. The filename is copied to clipboard when done.

### voicerecorder

`voicerecorder` records mono audio optimized for voice (low sample rate, small file size).

```
voicerecorder [filename] [-l length] [-s sample_rate]
```

- Default filename: `/sd/work/voice.wav`
- `-s`: sample rate (default 8000)
- `-l`: length in seconds, or minutes with `m` suffix e.g. `30m` (default 7200)
- Press Enter or `q` to stop. The filename is copied to clipboard when done.

### clip

`clip` is a simple application to save the content of clipboard to file.

```
clip file
```

### nudoc

`nudoc` is a Sudoku game.

```
nudoc [easy|medium|hard|board_file]
```

You can also pass a board file directly.

- Arrow keys: move cursor
- 1 – 9 key: select a number to input (just selecting, it won't place the nymber)
- Enter: Place selected number in current cell
- BS: toggle note mode (pencil mark shown in note mode)
- c : Toggle cursor highlight
- q: open quit dialog
- Touchpad: acts as a 3×3 numpad for number selection
- Slide bar: scroll to change selected number

#### Nudoc Board file

Nudoc app can read custom board file.

Custom board file syntax is simple text file:
```
800000000
003600000
070090200
050007000
000045700
000100030
001000068
008500010
090000400
```

### flashcards

`flashcards` is a flash card app to learn words.
Example-sentence generation uses an LLM (OpenAI by default, or any model in `/config/gpt.json`); read-aloud uses OpenAI TTS and needs `/config/openai_api_key`.

Options:
- `-r` : Reverse the answer and the question.
- `-v` : No voice
- `-m name` : LLM for example sentences — a `name` from `/config/gpt.json` (e.g. a local/third-party Chat model). Default: the registry default. See the gpt doc's [Model configuration](gpt_readme.md).

- Up : Reverse mode
- Down : Open menu
- Enter : See answer, go next word

#### Word file syntax

A word file for `flashcards` is simple Markdown file.

Here is an example.

```Markdown
# Hard one
- judicious : Showing good judgement, wisely chosen
- inscription : Words written or carved on a surface, like a stone, monument, or book.

Other sentences are just ignored.
```

### reader

`reader` is an E-book reader app.

```
reader [options] book_filename
```

Options:
- `-v` : vertical text(for Japanese)
- `-f font` : Font. t15, uni, lub1, lub2, cen1 or cen2.
- `-j` : for Horizontal Japanese text

For Japanese text, Adding `-v -f uni` options is recommended.


### invader

`invader` is a Space Invaders game.

- Left/Right touch buttons: move ship
- A button: shoot laser
- Left mouse button (square left button): quit

### zen_chamber

`zen_chamber` is an ambient audio-visual app. Particles fall under gravity and trigger notes from a musical scale, creating generative music.

- Touchpad: tilt gravity direction
- Slide bar (right): increase simulation energy and morph sound
- Dial: adjust number of particles (1–8)
- A button: transpose key clockwise on circle of fifths (+7 semitones)
- B button: transpose key counter-clockwise (−7 semitones)
- A+B together: cycle through scale modes
- Bottom-right button: quit


### gpt

gpt (`gpt`) is the AI assistant frontend. Refer [[gpt_readme]] for detail. Models and endpoints are configurable in `/config/gpt.json`: OpenAI's Responses API plus any Chat Completions endpoint (Ollama, local servers, other providers), selectable with `-m` or the `/model` command.

### gpt_rt

`gpt_rt` is a real-time voice agent using the OpenAI Realtime API. It opens a full-duplex audio conversation over WebSocket — you speak and the AI responds in near real time, with server-side voice activity detection handling turn changes automatically. Requires OpenAI API key at `/config/openai_api_key`. Many options are shared with gpt app. See [[gpt_readme]] for details.

```
gpt_rt [-m model] [-f file [file...]] [-a]
```

Option | Description
-------|------------
`-m model` | Model to use (default: `gpt-realtime-2`)
`-f file [file...]` | Attach one or more files as reference context for the session
`-a` | Agent mode — enables function calling (see below)

**Controls:**

Key | Action
----|-------
Enter | Toggle microphone mute/unmute
**Slider + A** | Toggle microphone mute/unmute — **works from any screen**, even when gpt_rt is in the background
`q` or B button | Quit

LED is lit while the microphone is active and turns off when muted.

Because Enter and `q`/B only reach gpt_rt while its own screen is foreground, the
**Slider + A** system shortcut is the way to mute/unmute while you are using
another screen (e.g. in agent mode, or just multitasking).

Barge-in is supported: speaking while the AI is talking interrupts the response and clears the audio queue.

#### Agent Mode (`-a`)

In agent mode the AI can take actions on the device during the conversation. The AI can run text commands, launch applications, write files, and **see and drive other apps**:

- `list_running_apps` — list the running apps and which screen each is on.
- `switch_screen` — bring a screen to the foreground.
- `capture_screen` — screenshot a screen and send it to the model as an image (encoded as a 1-bit PNG on the device).
- `send_keys` — type text / keystrokes into the foreground app (newline or `enter=true` presses Enter; escape sequences drive arrows, Esc, Ctrl combos, etc.).

This lets gpt_rt act as a background assistant that watches and operates another app while you keep talking to it. In agent mode the microphone stays live even when gpt_rt's own screen is not in the foreground.

> Because keyboard input goes to whichever screen is foreground, the `q`/B quit shortcut only works while gpt_rt's own screen is active — switch back to it (or have the agent `switch_screen` back) to quit.

App and agent app lists are loaded from `/config/apps.json` and `/config/agent_apps.json` so the AI knows which apps are available to launch.

### stt

`stt` is a Speech-to-Text app using OpenAI Whisper API. Requires OpenAI API key at `/config/openai_api_key`.

```
stt [options] [wav_file] [-o output_file]
```

- With no arguments: press any key to record, then transcribes and copies result to clipboard. Press `q` to quit.
- `wav_file`: transcribe an existing WAV file directly.
- `-o file`: save transcription to a file instead of clipboard.
- `-s` : Silent mode, record started immediately, and record will not repeat.
- `-l` : Preferred language
- `-d` : recording duration in seconds

### tts

TTS (Text-to-Speech) app. Reads a text file aloud (or saves it to a WAV with `-o`).

```
tts notes.txt
tts notes.txt -o out.wav
tts notes.txt -m kokoro          # use a local/third-party voice backend
tts notes.txt -vm nova           # override the voice
```

- `-m name` : Audio backend — an `api:"audio"` entry from `/config/gpt.json` (e.g. `kokoro`), or a model entry whose `audio` link to follow. Default: the registry `audio` default, else OpenAI (needs `/config/openai_api_key`). See the gpt doc's [Audio backend](gpt_readme.md) section.
- `-vm type` : Voice type, overriding the backend's configured voice.
- `-o file` : Save to a WAV file instead of streaming playback.

### qr

`qr` generates a QR Code from text or URL inputs and displays it centered on the screen.

```
qr [text...] [-c]
```

- `-c` : Generate QR code from clipboard.

### docs

`docs` is an AI help agennt for Pocket Deck. OpenAI API key is required.

```
docs how can I quit PEM editor?
docs give me a summary of Pocket Deck
```

### dic

`dic` looks up the meaning of a word using ChatGPT. Result is not saved to log.

```
dic [-j] word
```

- `-j`: answer in Japanese

### gdrive 

`gdrive` is Google drive integration. You can upload files to Google drive. 

`gdrive src dst`

-n : no save the result to log file
-j : answer in Japanese (It's just adding "and answer in Japanese" at the end of the message). You need to set terminal font to support Japanese characters. setjpf or setuni to change terminal font.

### sync

`sync` is a bidirectional file sync tool that keeps folders on Pocket Deck in sync with a remote machine over SSH. It uses MD5 checksums to detect changes and syncs only what has changed. When both sides have modified the same file, the newer one wins.

Authentication uses the private key at `/config/ssh/id_rsa` by default, or a password per remote.
See [[ssh_scp_readme]] for details.

Config is stored in `/config/sync.json` and is created automatically on first run.

**Managing remotes**

```
sync remote add <name> <host> <local> <remote> [password]
sync remote remove <name>
sync remote list
sync remote
```

Example:

```
sync remote add notes user@192.168.1.10 /sd/Documents /home/user/Documents
```

**Syncing**

```
sync exec <name>
```

Example:

```
sync exec notes
```

### listup

`listup` command adds a file to filelist for netserver sharing (Web and iOS app).
Usage:

`listup filename` 

### ble_kb

`ble_kb` is a background-running program (daemon) to manage BLE keyboad connection. 

The application is launched automatically when user sets to run it by `setup` script, or you can launch it from home app.

-r : Reset config file. It's useful to resolve connection issue.

## Change boot sequence

You can customermize boot sequence.

Edit /main.py and uncomment / comment applications. 

## Micropython Application development

You can make your own applications. Refer [[app_development.md]] for detail.


## Updating built-in applications and firmware

You can update applications and firmware through WiFi connection.

1. Connect to Internet (`wifi` command)

2. Execute `update_firmware` command to update MicroPython applications.

3. Execute `update` command to update firmware. When download is complete, all four LEDs are on and system will reboot the device to enter firmware update mode. When it's done, firmware updater prints `Done. Reset the unit`. Reset the device. (Unplug power without Lipo. Double click power button with Lipo.
