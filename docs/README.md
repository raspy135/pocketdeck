# Pocket Deck overview

Pocket Deck is a tiny, customizable computer designed for everyday productivity and creative tinkering. It's great for fast text writing, personal organization, and small life-improvement utilities. 

Its applications are not limited to writing; it can also make graphics and music applications.

Powered by MicroPython, it offers a powerful API, C-accelerated responsive graphics, and high-quality audio APIs, including sampler, wavetable, filter, mixer, and effectors. You can build and tailor features to fit your workflow wherever you are.

Pocket deck is designed for standalone use. You don't need PC for application development. You can write Python code in the editor and test it without PC.

Internet connectivity allows you to ask questions to AI, sync with a PC for file transfer, copy and paste, screen casting, and cloud storage integration with Google Drive.

![Product image](images/pocketdeck.jpg)

# Purchase

https://shop.nunomo.net

# Features

## Hardware

- WiFi and Bluetooth for connectivity.
- Touch pad and touch buttons (AVR128 as a sub processor for touch inputs)
- Stereo Audio codec
- Stereo built-in speaker
- Stereo MEMS Microphone
- LEDs
- SD card slot
- Expansion port
- USB-A for USB keyboard, and USB-C for charging.
- RTC clock to keep date and time

## Accessaries

### USB keyboard & cable (Required)

You need a USB keyboard and cable to operate the device. If you want a wireless connection, use a wireless dongle.

**Note**: Even though Pocket Deck is power efficient, some USB keyboards draw current a lot and it reduces battery life. Here are the same examples:

- USB keyboard charges its battery when it's connected. Use wireless dongle or BLE mode to reduce power consumption.

- USB keyboard with many full color LEDs. (It's knows full color LED array consumes power)


### BLE keyboard

BLE keyboards are supported, but they use more DRAM memory, not PSRAM. A wireless dongle for a USB keyboard will save memory.

If you want to use BLE keyboard, edit [[/main.py]] and uncomment ble_kb module. It will be launched on screen 9 and start BLE scanning. Classic Bluetooth keyboards are not supported.

To check the connection, switch screen to 9.
`KB ready` means the connection is established. The second LED (green) shows the status of BLE keyboard.


### LiPo battery (Optional, recommended)

There is JST-PH connector on the main PCB. You can install LiPo battery. LiPo has to be 1 cell(3.7V). 3000mAh or more capacity is recommended.

Battery operation is recommended.

Examples:
https://a.co/d/06c7H5FC
https://a.co/d/07asqJnc


### Magsafe stand (Optional, recommended)

Adding a MagSafe sticker to the back makes the device much more convenient. Place the sticker at the top center. There is a Wi-Fi antenna at the bottom of the unit, so avoid placing the sticker there.

### Disassemble process

The following is an example of the disassembly process for installing a LiPo battery.

1. Remove SD card and remove three screws on the top plate.

2. Remove the front panel. The front panel and the main panel are connected by 0.1-inch pins, so you can simply pull the panel off.

3. Remove the main board. The board is just sitting in the case, with no screws. Use the SD slot or the other holes on the side of the case to get some leverage.

4. Install the LiPo battery. Preferably, use double-sided tape to secure the battery.

5. Install the main board. There is a hole on the right side for the LiPo battery cable.

6. Connect the LiPo battery cable to the main panel. It uses a JST-PH connector. **Check the battery polarity before connecting it! There is no standard polarity for LiPo batteries, so it may be reversed. The PCB has “+” and “-” marks.**


7. Install the front panel. Make sure to align the pin headers.

8. Replace the screws.


## Software overview

- A powerful text editor written entirely in MicroPython. See `[[pem_readme.md]]` for details.
- Some utilities written by MicroPython, such as journal to chart, clock, calendar and kitchen timer.
- Graphics and audio modules optimized for performance and written in C.
- Powerful terminal which supports a lot of escape sequence. This enables practical SSH experience.
- A powerful audio engine; the core is written in C for performance.
  - Stream, Sampler, and Wavetable
  - Filter, Compressor, Delay, and Reverb
  - Flexible routing
  - A Tidal Cycles/Strudel-inspired frontend sequencer that provides flexible music sequencing and sample-accurate timing

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
Up, Down, Right and Left | These work as arrow keys. If the application supports it, the arrow keys can also be used like a dial by circling your finger. See `get_tp_keys()` for details.
A | Enter
B | Backspace
Square shaped button (Left) | Left mouse button, if supported by the app
Square shaped button (Right) | Right mouse button, if supported by the app
touch pad | Can be used as a touch pad (mouse), if supported by the app
`<` | Go to the previous screen
`>` | Go to the next screen
Slide bar at the right side | Scrolls the terminal screen to show previous messages. If the terminal is in raw mode (`esclib.raw_mode(True)`), it works as the Up/Down keys.

Pocket deck has LEDs on the left side and it can be used for status indications.

- The 4 LEDs on the first row indicates battery status with LiPo battery connected.
- The red LED on the second row blinks when there is new output to Python REPL (screen 1).
- The leftmost LED on the third row indicates netowrk status. It will be on when it's connected.
- The rest 3 LEDs are for applications, can be controlled via Python.

There is a power button next to touchpad.

Press the button one time to power up the device with Lipo battery. It's always on when it's connected to power supply.

Press the button twice, like a double click, to shut down the device.

## System shortcuts

`C-a` means Control + A.  
`S-C-a` means Shift + Control + A.

- `C-[0-9]`: Switch screens
- `C-Left`, `C-Right`, or the left/right touch buttons on the device: Switch to the next or previous screen
- `C-Up` or `C-Down`: Scroll on the console
- `S-C-q`: Force-quit the running application. You should avoid this as much as possible, because applications are not protected like normal OSes such as Linux. For graphics applications, try `S-C-d` first.
- `S-C-r`: Restart the device
- `S-C-i`: Invert the screen colors
- `S-C-d`: Detach the screen (suspend the application) for graphical applications. It is useful when the application goes out of control due to a bug or other reason. It is safer than Shift+Ctrl-Q.
- `S-C-=`: Increase the font size. Unless the application is designed to react to font-size changes, restarting the application is usually necessary.
- `S-C--`: Decrease the font size
- `S-C-c`: Copy the current line to the system clipboard. This is useful in text applications.
- `S-C-v`: Paste data from the system clipboard. Note the length of the data is limited due to input buffer length. The application support is needed to paste large data.


## Basic file structure

- `/` : Root folder (Internal flash)
- `/config` : Folder to store config information
- `/sd` : SD card root
- `/sd/Documents` : User documents
- `/sd/lib` : Built Python applications
- `/sd/lib/examples` : Python application examples
- `/sd/py` : Python application folder for user apps

## Getting started

See [[getting_started]]

## Micropython interactive console (REPL)

The MicroPython interactive console (REPL) is always available on screen 1. It is great for small tasks like calculations and debugging.  
Programs can keep running even when the screen is not selected.


## Command Shell

- Pocket deck has a simple command shell to execute built-in commands and Python scripts.

- Only a few commands are built-in, everything else are written by Python.

command | summary
--------|---------
`cmd` | Launch a new command shell. Syntax: `cmd [screen_number]`
`ssh` | SSH command. See `[[ssh_scp_readme]]` for details.
`scp` | SCP command. See `[[ssh_scp_readme]]` for details.
`Python module name` or `py module_name` | Execute a Python command. Syntax: `module_name [args] [args..]`. Normally, the module name is a Python filename. The search path is in the `sys.path` list.

Here are some basic commands written by Python.

command | summary
--------|---------
`ls [file]` | List files
`cp src dst` | Copy a file
`mv src dst` | Move a file
`mkdir dir_name` | Create a directory
`rmdir dir_name` | Delete a directory
`cat file` | Print file contents
`cd [dir]` | Change the working directory. Note that this is a global value shared between shells and applications. Applications such as the Pem editor do not know about the change.
`pwd` | Get the current working directory. The default working directory is `/sd/Documents`.
`netserver` | Launch a network server to provide services. It provides screencasting and clipboard sharing. See `[[netserver/GETTING_STARTED]]` for details.
`setuni` | Change the terminal font to a CJK Unicode font
`setjpf` | Change the terminal font to Japanese. It is lighter than `setuni`


## Basic applications

### home

The `home` app is launched on screen 10 after power-on. You can launch apps and change settings from the app. If you want to save changes, select `Save` in the menu.

The application-launch menu can be customized using the JSON file located at `[[/config/apps.json]]`. To reload the app list, select `Reload app list` in the menu.


### Wi-Fi

The `wifi` command connects to Wi-Fi. 

### Pem editor

Pem (`pem`) is an Emacs-inspired, powerful editor written in Python. See `[[pem_readme.md]]` for details.

### Analog clock

The `analog_clock` application is useful. It includes an analog clock, calendar, and kitchen timer. You can copy the selected date, which is useful for journaling.

- `c`: Copy the date to the clipboard. Format: `<yyyy-mm-dd day>`
- Arrow keys: Move the calendar
- Backspace: Switch between the calendar and timer


### Journal

`journal` analyzes `journal.md` and visualizes it as a chart. See [[journal_readme]] for details.

### Tasks

`tasks` analyzes `tasks.md` and visualizes it as a task list. See [[tasks_readme]] for details.

### Music

`music` is an audio player. See `[[music_readme]]` for details.

### Wavplay

`wavplay` is an audio player and the CLI version of `music`. It can also play a WAV file when you specify the path to the file.

```
wavplay folder_name
```

### Wavfileplay

`wavfileplay` is a simple wav file player.

```
wavfileplay wav_file_name
```

### Recorder

`recorder` is the app to record audio through line in or microphone. Audio configuration can be done via `home` app, under audio menu. Select proper input source(line in or microphone), auto gain setting(on for voice memo, off for audio recording), and input gain.

There are two typical scenario to use the app, one is aircheck, and another one is voice recording.

- `-s` : Sample rate, default is 24k. Select 48k(48000) for high quality recording.
- `-l` : Specify the record length, default is one hour. It's useful when you know the length of audio.

### voicerecorder

`voicerecorder` is the simple wrapper application of `recoarder`. It uses 8k sample rate, mono channel. It's great for recording meeting for Speak To Text (`stt`).

### gpt

`gpt` is a powerful ChatGPT frontend. You can ask questions, attach files and images.

You need an OpenAI API key to use the app. Save your API key to `/config/openapi_api_key`.

- `-f`, `--file` file [file..]: Attach files or URLs as reference data. You can attach multiple files, separated by spaces.
- `-i`, `--image` file [file..]: Attach image files or image URLs. You can attach multiple images, separated by spaces.
- `-v`, `--voice`: Voice mode. It records your voice, transcribes it with the speech-to-text API, and speaks the response with text-to-speech.
- `-vt`, `--voice-type`: Select a voice type (`alloy`, `coral`, `echo`, `fable`, `onyx`, `nova`, `shimmer`)
- `-c`, `--clipboard`: Use data from the clipboard as reference data
- `-n`: Do not save the result
- `-j`: Answer in Japanese. You need to execute the `setuni` command to use Unicode characters in the terminal font.
- `-q`: Specify the content explicitly, for example after the `-f` option you need to use `-q` to mark the start of the question.

### stt 

`stt` is Speak-To-Text program, which requires OpenAI API key (See `gpt` document for details). It's useful with `voicerecorder`.

```
stt [input_wav_file]
```

It will enter recording mode when input_wav_file is not specified.

### dic

dic is dictionary application. This is wrapper application of `gpt`. -j option to get answer in Japanese.

Example:
```
dic squeeze
```

### gdrive 

`gdrive` is Google Drive integration. You can upload files to Google Drive.

`gdrive src dst`


### Zen chamber

`zen_chamber` is a audio demo, meditating sound scape.

## Micropython Application development

You can make your own applications. See `[[app_development.md]]` for details.

## Updating built-in applications and firmware

You can update applications and firmware through a Wi-Fi connection.

1. Connect to the internet using the `wifi` command.

2. Execute the `update` command to update the MicroPython applications.

3. Execute the `update_firmware` command to update the firmware. When the download is complete, all four LEDs turn on and the system reboots to enter firmware update mode. When it is finished, the firmware updater prints `Done. Reset the unit`. Reset the device. (Unplug power if using no LiPo battery. Double-click the power button if using a LiPo battery.)




