# Pocket Deck

Pocket Deck is a tiny, customizable computer designed for everyday productivity and creative tinkering. It's great for fast text writing, personal organization, and small life-improvement utilities. 

And the applications are not limited to writing, it is capable doing graphics and music applicaitons.

Powered by MicroPython, it offers a powerful API, responsive graphics, and high-quality audio so you can build and tailor features to fit your workflow wherever you are.

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
- SD card slot (Tested up to 128GB, technically you can go more)
- Expansion port
- USB-A for USB keyboard, and USB-C for charging.
- RTC clock to keep date and time
- 8 pin external port (2 pins are available for I/O)

## Accessaries

### USB keyboard & cable (Required)

You need USB keyboard and cable to operate the device.

### LiPo battery (Optional, recommended)

There is JST-PH connector on the main PCB. You can install LiPo battery. Around 3000mAh to 4000mAh is recommended. (Put some Amazon link here)
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

## Basic file structure

- `/` : Root folder (Internal flash)
- `/config` : Folder to store config information
- `/sd` : SD card root
- `/sd/Documents` : User documents
- `/sd/lib` : Built Python applications
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
scp | scp command. Syntax is "scp host username password copy_from copy_to". Remote path starts with ":". Example: scp 192.168.1.100 user password test.txt :/home/user/test.txt  .
Python module name or py module_name | Execute Python command. Syntax is "module_name [args] [args..]". Normally  module name is Python filename. Searching path is in sys.path list.

Here are some basic commands written by Python.

command | summary
--------|---------
ls [file] | List files. 
cp src dst | Copy file
mv src dst | Move file
mkdir dir_name | Create a directory
rmdir dir_name | Delete a directory
cat file | Print a file content
cd [dir] | Change working directory. Note this is global value, shared between shells and applications. The applicaitons (such as pem editor) do not know the change.
pwd | Get current working directory
netserver | launch network server to serve services. It provide screencast and clipboard sharing. See [[netserver/GETTING_STARTED]] for detail.
setuni | Change terminal font to CJK Unicode font,.
setjpf | Change terminal font to Japanese. It's lighter than setuni.


## Basic applications

### Home app

Home app is an app to launch apps and change settings.

- Arrow keys, Enter and BS : Navigate menu
- R bottom button in launch app list : Open application list menu. You can add, move and delete app. The data is saved in /config/apps.json. You can edit the file manually.

### Pem editor

Pem (`pem`) is emacs-inspired powerful editor written by Python. See [[pem_readme.md]] for detail. 

### Analog clock

Analog clock (`analog_clock`) is useful application, it has analog clock, calendar and kicken timer. You can copy select date, it's useful for journaling.

- B button (BS) : Toggle timer
- C key in calendar mode : Copy selected date to clipboard (C-S-v to paste)

### Journal

Journal (`journal`) analizes [[journal.md]] and visualizes to chart. Refer [[journal_readme.md]] for detail.

### Music

Music (`music`) is an audio player. Refer [[music_readme.md]] for detail.

### Wavplay

Wavplay (`wavplay`) is an audio player, CLI version of music. It also can play wav file when you specify path to wav file.

### gpt

gpt (`gpt`) is ChatGPT frontend. You can ask questions.

### dic

dic is dictionary application. This uses chatGPT to get the answer. -j option to get answer in Japanese.

### gdrive 

`gdrive` is Google drive integration. You can upload files to Google drive. 

`gdrive src dst`

-n : no save the result to log file
-j : answer in Japanese (It's just adding "and answer in Japanese" at the end of the message). You need to set terminal font to support Japanese characters. setjpf or setuni to change terminal font.

## Micropython Application development

You can make your own applications. Refer [[app_development.md]] for detail.


## Updating built-in applications and firmware

You can update applications and firmware through WiFi connection.

1. Connect to Internet (`wifi` command)

2. Execute `update` command to update MicroPython applications.

3. Execute `update_firmware' command to update firmware. When download is complete, all four LEDs are on and system will reboot the device to enter firmware update mode. When it's done, firmware updater prints `Done. Reset the unit`. Reset the device. (Unplug power without Lipo. Double click power button with Lipo.




