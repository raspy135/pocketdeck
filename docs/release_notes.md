## Release Note, May 20, 2026

### Firmware

- Escape sequence engine overhaul, mostly for SSH apps on Linux.

### Application

- stt : silent and language option added
- pem : speech-to-text command added (C-c s)


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
