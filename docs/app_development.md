
## Python application development

Pocket deck uses Micropython as core development language, and graphics and sound library are written by C module for performance.

### Your first application

1. Create a file in /sd/py, it's the folder for user applications.

You can use Pem editor to create a new file. /sd/py is the standard path that MicroPython will check. You can add new paths by adding items in sys.path list by adding /main.py

2. write basic application

There are examples under /sd/lib/examples. 'hello_world' is the most basic application, and 'hello_grachic' is a simple graphic application.

## Pdeck Micropython module

To interact with Pdeck graphical screen, use Pdeck module. Through Pdeck module, you have an access to Keyboard status, and virtual screen status. The graphic engine is u8g2.
Pdeck also provides the interface to virtual screens. You can create your own app for Pocket deck and the process is straight forward, easy to port your existing apps.

## Reload Python module

By default, Micropython module won't be reloaded when it's invoked from command shell.

It's good for stable applications, but you want to reload the application in development.

To reload the module, use 'r' command to reload the module. For example:

$ r hello_world

Alternatively, you can use pdeck_utils.reimport() to reload module.

## Error handling

Python system error message and print() will be printed on screen 1(REPL). Red LED will be lit to notify there are  new messages. This redirection is useful when graphical application has errors.

If the application becomes unresponsible, try S-C-d (Shift+Ctrl+D) to unsubscribe update() callback and quit the main app. 

```Python
def main(vs, args):
  print('This message goes to screen 1, this is useful to debug applications.')
  print('This message goes to the current screen', file=vs)
```



## Pdeck module reference

Pdeck module controls Pocket Deck system features and peripherals.

- `change_screen(screen)` Change screen to the given number.

- `change_priority(priority)` Set current application as priority. This might cause system performance issue, basically it's not recommend to use. Priority is bool. True for priority task.
- `clipboard_copy(string)` Copy string data to clipboard which can be used between applciations.

- `clipboard_paste()` Paste data from clipboard. Return: Data in the clipboard.

- `cmd_exists(screen_num)` Checks if an application exists in the specified screen number(0 based).

- `cmd_execute(command, screen_num_cmdshell, screen_num_dest)` Execute command in command shell. Screen_nym_cmdshell is screen numer of command shell instance.
Usually it will be 1(0 based number) because command shell is always running on screen 2). screen_num_dest is the screen number you want to execut the command.

- `delay_tick(tick)` Sleep in specified ticks. It's similar to time.sleep_ms(), but the unit is in tick, and it will perform better yielding. MicroPython's sleep_ms() does accurate sleeping but it frequently checks the time. It will give better CPU utilization when you don't need precise time sleep.

- `get_screen_num()` Returns the current screen number.

- `get_screen_size()` Returns a tuple of the screen size.

- `init()`  Internal use, do not call.

- `led(led_index, brightness)` Light up LED. led_index 1,2,3 can be used for user applications. brightness is 0 to 254.

- `rtc(tuple)` Set or get built-in RTC time. Tuple format is (year, month, day, weekday, hour, minute, second). Normally the date and time will be synchronized when you connect to Internet.

- `screen_invert(value)` Passing True to invert screen (White is background). Calling this function without an argument to get the current setting.

- `show_screen_num()` Show current screen nymber at the top right corner.
- `shutdown()` Turn off power of the unit.
- `update_app_list(screen_num, value)` System function, internal use.
- `vscreen()` Create and returns a Vscreen object.

## vscreen module reference

vscreen represents virtual screen(0-10). All graphics APIs are implemented in this class.

### Graphics Operations (via vscreen object)

#### Creating a vscreen object

Normally you can get vscreen object via vscreen_stream

```python
def main(vs, args):
	v = vs.v #v is vscreen object
```

Or 

```Python
screen = pdeck.vscreen([screen_num])
```

This creates a new vscreen object. If `screen_num` is not provided, uses the current screen.

### Drawing Methods

All drawing methods work when the vscreen is active (current screen). Basically many of methods are wrapper of u8g2 library. See u8g2 reference manual for detail.

**Basic Shapes:**

- `draw_pixel(x, y)`
- `draw_line(x1, y1, x2, y2)`
- `draw_h_line(x, y, w)`
- `draw_v_line(x, y, h)`
- `draw_box(x, y, w, h)`
- `draw_frame(x, y, w, h)`
- `draw_rframe(x, y, w, h, r)` - rounded frame
- `draw_rbox(x, y, w, h, r)` - rounded box
- `draw_circle(x, y, rad, opt)`
- `draw_disc(x, y, rad, opt)`
- `draw_triangle(x0, y0, x1, y1, x2, y2)`
- `draw_arc(x, y, rad, start, end)`
- `draw_ellipse(x, y, rx, ry, opt)`
- `draw_filled_ellipse(x, y, rx, ry, opt)`
- `draw_polygon(points_array)` - points as int16_t array [x1,x2,..., y1,y2,...]

**Text Operations:**

- `draw_str(x, y, text)`
- `draw_utf8(x, y, text)`
- `draw_button_utf8(x, y, flags, width, padding_h, padding_v, text)`
- `get_str_width(text)` - returns text width in pixels
- `get_utf8_width(text)` - returns UTF-8 text width

**Bitmap Operations:**

- `draw_xbm(x, y, w, h, xbm_data)` - This is tuned version for performance.
- `capture_as_xbm(x, y, w, h, buffer)` - Capture screen area to XBM format

**Font and Display Settings:**

- `set_font(font_name)` - font_name can be font name or pointer to font data. The following fonts are built-in and can be specified as font name. For custom fonts, font data is raw font data used in u8g2.
  - `u8g2_font_profont11_mf`
  - `u8g2_font_profont15_mf`
  - `u8g2_font_profont22_mf`
  - `u8g2_font_profont29_mf`
  - `u8g2_font_tenfatguys_tf`
  - `u8g2_font_tenthinnerguys_tf`
- `set_draw_color(color)` - 0 is black, 1 is white, 2 is xor
- `set_font_mode(mode)` 
- `set_bitmap_mode(mode)` - 1 for transparent. 
- `set_dither(dither_level)` - Set dither color level, 0 to 16.

**Buffer Management:**

Pocket deck has two screen buffer. 0 is main buffer, and user can use buffer 1 as working area.

- `clear_buffer()` - you don't need to use this for buffer 0, system takes care of clearing buffer 0.
- `switch_buffer(buffer_num)` -  switch between buffers (0 or 1)
- `copy_buffer(to_buffer, from_buffer)` - copy buffer contents

### Screen Properties

- `active` (read-only) - Returns `True` if this vscreen is currently active
- `suspend_inactive_screen` (read/write) - Global setting to suspend callbacks for inactive screens

### Callback System

Callback function to be called for every frame update.

- `callback(handler)` Register an update callback function. The handler will be called with a boolean parameter indicating if a screen change was requested.

- `callback_exists()` Check if the callback is still registered.

- `finished()` Notify that the screen update is finished. Should be called in the callback handler. If finished() function is called without calling any of graphic drawing functions, Vscreen module won't update screen, it will save energy.

### Input/Output Operations

- `print(text)` Print text to the terminal. 

- `send_char(data)` Send character data as keyboard input.

- `send_key_event(key, modifier, event_type)` Send keyboard event.

- `read_nb(max_bytes)` Read up to `max_bytes` from input. Returns tuple `(bytes_read, data)`. This is non-blocking function.

- `poll()` Check if there's input available. Returns `True` if data is available.

- `get_key_state(key_code)` Get the state of a specific key.

- `get_tp_keys()` Get touchpad keys state as bytes.

### Terminal Settings

- `get_terminal_size()` Returns terminal dimensions as tuple `(width, height)`.

- `set_terminal_font(normal_font, bold_font, width, height)` Set terminal font from binary data.

- `set_terminal_font_size(size)` Set terminal font size.

- `pdeck.set_default_terminal_font_size(size)` Set default terminal font size globally.

- `pdeck.get_default_terminal_font_size()` Get default terminal font size.

- get_tp_keys() Get touch panel button status.


## pdeck_utils class

pdeck_utils has some useful commands to launch and manage applications. Many functions are used for internal purpose to communicate with C-based command line shell, they are internal use.

- `reimport(module_name)` Reimport Python module from source. It's useful for application development.

- `launch(command,screen_num)` Launch Python module. command is a list that contain Python module name and arguments. screen_num is the screen number you want to launch the module.

Here is an example to launch Pem editor on screen 3.

```Python
pdeck_utils.launch(['pem','/sd/Documents/journal.md'],2)
```

- `timezone` This is system property that stores timezone. It increases the value by 15 minute timezone offset from UTC. For example, -8 hours is stored as -32 (8*4).

## vscreen_stream class

vscreen_stream is Python wrapper of vscreen object.  vscreen_stream provides stream object interface.

```Python
# vs is vscreen_stream object
def main(vs, args):
	print("Helloworld", file=vs)
```


- `v` vscreen object associated in the object. Application can get vscreen object by accessing the member.

```Python
def main(vs,args):
  v = vs.v # Getting vscreen object for the app.
```

