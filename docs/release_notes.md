## Release Note, July 17, 2026

## Firmware

- screenrec support

## Application

- screenrec provides recording screen, the raw file will be saved to SD card.

## Release Note, July 16, 2026

### Firmware

- ble_kb : Better handling when high load.
- Stability improvement

### Application

- gpt : Fix web search issue with Tavily
- gpt_rt : Experimental : gpt_rt supports X.ai with X.ai API key. However OpenAI is recommended for smarter agentic tasks.


## Release Note, July 13, 2026

### Firmware

- BLE keyboard support: bug fix, more stable connection.

- USB keyboard support: bug fix, some keyboards were not recognized properly.

### Applications

- gpt: Tavily(www.tavily.com) search support for better AI web research. Puy Tavily API key to /config/tavily_api_key to make web search more robust.
- gpt: New tools for beter agentic tasks, bug fixes.
- gpt: Tab completion for skills.

## Release Note, July 9, 2026

### Applications

- cd : bug fix

## Release Note, July 5, 2026

### firmware

- pipe('|') support for command line tools.

### Application

- BLE keyboard manager fix. It has an issue with some BLE keyboards.
- System shortcut is added. Applications can register system shortcut by vscreen.register_shortcut(). The feature is used in gpt_rt.
- rm : bug fix
- echo : echo command
- grep : more options
- curl : more options
- listup : A simple new application to add a file to shared filelist(Web and iOS)

#### AI apps (gpt, gpt_rt)

- gpt : Add multiple models and multiple endpoints support, and Chat Completion API support. Chat Completion API is standard API for most of LLMs, so you can use most of LLM models in the market or local LLMs. Models are configured in `/config/gpt.json` (an Ollama-style registry) and selected with `-m` / `/model`; the previous separate `gpt_c` app is now merged into `gpt` as an internal client.
- AI apps (gpt and gpt_rt) can read PEM status in agent mode (-a), inspect content, and edit the currently open file. For example: "Check the line I'm editing in PEM and add a wrap-up to the end."
- Added `/improve`. It generates a self-improvement memo at `/sd/Documents/ai_memory/ai_memory.md` and is auto-executed periodically in the `gpt` (conversation mode, every 8 turns by default; `/auto-improve` to tune) and `gpt_rt` apps.
- AI apps now has skills. System skills are located under /sd/lib/skills, and user skills are located under /sd/Documents/skills.
- AI apps has personal memory, it will be stored in /sd/Documents/ai_memory/ai_memory.md
- gpt_rt : The microphone can be toggled with the system shortcut slider + A.
- A lot of tweeks to gpt and gpt_rt for more efficient tool calls, better agent performance.

## Release Note, June 26, 2026

### firmware

- pem : tab handling fix 

## Release Note June 22, 2026

### firmware

Now gpt, gpt_rt, home and some libraries are part of the firmware. You can still customize them by copying the Python files to /sd/py.

### Application

- gpt_rt: Menu to reset session When BS is pressed.
- clip: A new app. The app saves clipboard content to file.

## Release Note June 16, 2026

### firmware

- PEM bug fix
- Boot banner


## Release Note June 6, 2026

### Firmware

#### PEM

- Bug fix

## Applications

- gpt.py : bug fixes
- `graph` application is added. This will show Obsidian-style Markdown graph view.
- Journal application rebuild, to support mutiple files, performance improvement, and YYYY-MM-DD.md.

## Release Note June 3, 2026

## Firmware

- firmware sends proper keycode for Shift + tab ('\x1b[Z')

## Application

- pem_open command added, this command will open a file in existing pem instance.

- gpt_rt command now can send keys, take screenshot.

- some utility commands (head, tail, diff) were added.

### gpt

- Conversation mode -C is added.
- In agent mode, it uses function call.
- Now AI can read file, execute command, and switch screen and take a screenshot.
- Old version of gpt is available as gpt_l.

## Release Note June 2, 2026

## Firmware

- `update` command will delete unknown files in /sd/lib. Do not put user files in it.

## Application

- Folder structure change, non-application python files moved under /sd/lib/noa.


## Release Note May 31, 2026

### PEM

- Now pem is part of the firmware
- Undo (C-/)
- little enhancements
- C mode
- The script supports Linux.
- Mark set (C-space), copy (M-w), cut (C-w)
- Incremental search on select dialog (such as file list)
- Cursor move, insert text on input dialog 

### Firmware

- Add some missing key bindings.

### Emulator

- Emulator is available.
https://pdemulator.nunomo.net/emulator/



## Release Note May 30, 2026

## Application

- QR code generater app `qr` added.

## Release Note May 23, 2026

## Firmware

- GC optimization
- BT keyboard bugfix
- Setup script to configure boot sequence

## Application

- `setup` command to configure boot sequence


## Release Note May 23, 2026

## Firmware

- command shell : history crash fix
- modiication for TAB completion

## Application

- analog_clock : Filling arc was added to the timer.
- Command line shell : Powerful command line TAB completion, it works on command and files and command history. Just press TAB to show command list.

## Release Note May 21, 2026

### Firmware

- Add ctrl-d support on command line
- Alt+1 for '`' , and Alt+2 for '~'

### Application 

- Recorder : Level indicator added
- Music : Multi-level folder support
- gpt : added --effort option.

## Release Note, May 20, 2026

### Firmware

- Escape sequence engine overhaul, mostly for SSH apps on Linux.

### Application

- stt : silent and language option added
- pem : speech-to-text command added (C-c s)
- gpt_rt : Less audio glitches


## Release Note, May 19, 2026

### Application

- PEM : Jump history Bug fix 
- reader : Markdown table support

## Release note, May 18, 2026

### Firmware

- Bug fix : Incorrect GC collection.

### Application

- gpt_rt is added for realtime voice agent.
- curl tools added  


## Release note, May 17, 2026

### Firmware 

- Escape sequence handling bug fix
- Netserver improvement. When traffic is separate, constant 40 to fps is possible.
- Some extra chars are added to system fonts to support modern CLI apps.
- More system fonts.

### Application

- Slide bar support for menu navigation
  - home, nudoc, music app
- PEM : syntax hightlight fix, supports hashtag highlighting(#tag) in Markdown mode.




## Release note, May 15, 2026

### Firmware

- Smooth scrolling changing between virtual screens.
- Faster font rendering
- Selective update (no longer update all files, recommend to execute update_firmware first then update)
- More robust escape sequence support to support more Linux apps via SSH.
- SSH Python module to execute remote command on Linux, WSL and Mac via SSH, and SCP to copy files.
- Large SD card (ExFAT) support more than 32GB. You need to update Firmware updater by `update_updater -f` to add ExFAT support for firmware updater.
- Texture drawing support, you can scale images. See texture_example.py.
- 2D scalable font support. See font2d_demo.py.
- More system font options
- Micropython tuning for performance.

### Applications

- Home app: Now you can add, move and delete app in the app, without editing apps.json. Hit R bottom button in app list to open menu.
- gpt: bug fixes, better response
- journal: Performance improvement
- analog_clock: Kitchen timer improvement
- reader : Bug fix, missing fonts, better word-wrapping
- nudoc: Custom board support
- Standalone text-to-speech app(tts)

### New Apps

- A new Flashcards app(Requires OpenAPI key)
- `sync` app for selective file sync via SSH/SFTP.
- tts app (Text to speech). OpenAPI key needed.

### Libraries

- Anm (Animation) module support for easy animation.

### PEM

- Syntax highlighting for Python and Markdown
- Incremental help screen when you press Ctrl-x or Ctrl-c.(This can be turned off by pem_keymap.py configuration)
- `F1` key to open document.
- Now the editor asks to confirm when you close file and quit the app.
- Performance tuning
