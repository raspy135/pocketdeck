
# Pocket Deck Python application development guide

Pocket deck uses Micropython as core development language, and graphics and sound library are written by C module for performance.

### Limitations

- Pocket deck supports multiple applications running at the same time, but it's just threads, there  are no protection between applications. So all applications must be trusted.
- Pocket deck uses thread to handle multiple applications. Micropython does not allow using asyncio with thread. Do not use asyncio.

### Examples

Examples are located in /sd/lib/examples.

### Screen specification

Pocket deck has monochrome LCD. Resolution is 400 x240. Refresh rate can go more than 60 fps.

### Your first application

1. Create a file in /sd/py, it's the folder for user applications.

You can use Pem editor to create a new file. /sd/py is the standard path that MicroPython will check. You can add new paths by adding items in sys.path list by adding /main.py

2. write basic application

If you want to use existing examples as an application template, there are examples under /sd/lib/examples. [[/sd/lib/examples/hello_world.py]] is the most basic application, and [[/sd/lib/examples/hello_graphic.py]] is a simple graphic application. Copy one example that you want to try under /sd/py and edit as you like. /sd/py has priority than /sd/lib, so you can override the existing apps if you want.

main() is the entry point of the application, it has to be defined. Here is minimal application for Pocket deck:

python
```
def main(vs, args):
  print("Hello Pocket deck", file=vs)
```

`vs` is a **vscreen_stream** object — a Python IO stream that wraps the underlying C `vscreen` object. `args` are command arguments; `args[0]` is always the command name itself.

> **`vs` (vscreen_stream) is not `vs.v` (vscreen).** Use `print(..., file=vs)` and `vs.read()` for text I/O on the stream. For graphics, callbacks, and non-blocking keyboard access, go through `vs.v` — the raw C vscreen object.

Once you finished editing, save the file.

3. Run the application

To run the application, go to command line and execute the command.

If your filename is /sd/py/test.py, the command will be the following:

```
r test
```

`r` ensures reloading module, so it's useful for development. See `Reload Python module` section for detail.

## Pdeck Micropython module

To interact with Pdeck graphical screen, use Pdeck module. Through Pdeck module, you have an access to Keyboard status, and virtual screen status. The graphic engine is u8g2.
Pdeck also provides the interface to virtual screens. You can create your own app for Pocket deck and the process is straight forward, easy to port your existing apps.

## Reloading Python module

By default, Micropython module won't be reloaded when it's invoked from command shell.

It will save loading time for stable applications, but you want to reload the application while development.

To reload the module, use 'r' command to reload the module. For example:

$ r hello_world

Alternatively, you can use pdeck_utils.reimport() to reload module.

If you develop multiple modules like one top module and sub modules, you need to reload all modules. It can be done by 'r' command, pdeck_utils.reimport().

Alternatively, you can manually delete the key from sys.modules array to force reloading.

The following code automates reloading sub module only when the module is loaded at the first time.

```Python
import sys
if not 'loaded' in locals():
  # Deleting item in sys.modules forces module reloading
  del sys.modules['sub_module']
import sub_module
loaded = True
```

## Error handling

Python system error message and print() will be printed on screen 1(REPL). Red LED will be turned on to notify there are new messages. This redirection is useful when graphical application has errors.

If the application becomes unresponsible, try C-S-q. In graphics application, it's safer to try C-S-d first to detatch graphic update callback.

```Python
def main(vs, args):
  print('This message goes to screen 1, this is useful to debug applications.')
  print('This message goes to the current screen', file=vs)
```

## Remote command exection

Remote command is an interface to execute function from the other Python app. 

For example, `analog_clock_set_timer` command sets kitchen timer when the application exists in the system.

To support remote command, follow the steps:

1. In the app, call `vs.register_module(self)` to register the application object.
2. In the caller app, scan pdeck_utils.app_list and get the object, and call the function. Print message for result. The message could be used by AI.

## Pdeck module reference

Pdeck module controls Pocket Deck system features and peripherals.

- `change_screen(screen)` Change screen to the given number.

- `lock(pin=None)` Lock the device. The display switches to a firmware-driven lock screen that asks for a numeric PIN; while locked, screen switching and all system shortcuts are disabled. Pass `pin` as a string of digits (e.g. `pdeck.lock('0912')`) to set the PIN (stored in NVM) and lock. Call with no argument to lock using the already-stored PIN. Raises `ValueError` if the PIN is not 1–10 digits, or if no PIN has ever been set. The PIN can be entered with the USB keyboard or the touchpad (3×3 numpad: top row 7 8 9, middle 4 5 6, bottom 1 2 3; bottom-left button = 0; B = backspace). It unlocks automatically once the correct number of digits is entered — no Enter required. The lock state survives reboot. After 10 wrong attempts the device enters a 2-hour cooldown and then auto-resets (the PIN is cleared) so a forgotten PIN can be recovered.

- `set_lock_pin(pin)` Store/replace the lock PIN (string of digits) without locking. Pass an empty string to clear the PIN and any lock state. Raises `ValueError` for a non-digit PIN.

- `has_lock_pin()` Returns `True` if a lock PIN is currently stored.

- `wifi_connected()` returns wifi connection status.

- `change_priority(priority)` Set current application as priority. This might cause system performance issue, basically it's not recommend to use. Priority is bool. True for priority task.
- `clipboard_copy(string)` Copy string data to clipboard which can be used between applciations. (C-S-v to paste the data from clipboard)

- `clipboard_paste()` Paste data from clipboard. Return: Data in the clipboard.

- `cmd_exists(screen_num)` Checks if an application exists in the specified screen number(0 based).

- `cmd_execute(command, screen_num_cmdshell, screen_num_dest)` Execute command in command shell. Screen_nym_cmdshell is screen numer of command shell instance.
Usually it will be 1(0 based number) because command shell is always running on screen 2). screen_num_dest is the screen number you want to execut the command.

- `command_shell(screen_num)` Launch a new command-line shell on the given screen. This is the equivalent of the cmd shell's `cmd [screen]` command, except `screen_num` here is 0 based (the `cmd` command takes the 1 based GUI number). Valid screens are 2-9, the screen must be free (no shell or app already running there) and must not be the current screen. Returns `True` on success, `False` on error.

- `delay_tick(tick)` Sleep in specified ticks. It's similar to time.sleep_ms(), but the unit is in tick, and it will perform better yielding. MicroPython's sleep_ms() does accurate sleeping but it frequently checks the time. It will give better CPU utilization when you don't need precise time sleep.

- `get_screen_num()` Returns the current screen number.

- `get_screen_size()` Returns a tuple of the screen size. With the current display, it would be (400,240)

- `init()`  Internal use, do not call.

- `led(led_index, brightness)` Light up LED. led_index 1,2,3,4 can be used for user applications. brightness is 0 to 254.

- `rtc(tuple)` Set or get built-in RTC time. Tuple format is (year, month, day, weekday, hour, minute, second). Normally the date and time will be synchronized when you connect to Internet.

- `screen_invert(value)` Passing True to invert screen (White is background). Calling this function without an argument to get the current setting.

- `show_screen_num()` Show current screen nymber at the top right corner.
- `shutdown()` Turn off power of the unit.
- `update_app_list(screen_num, value)` System function, internal use.
- `vscreen()` Create and returns a Vscreen object.

## vscreen vs vscreen_stream — object guide

These two objects are closely related but distinct. Mixing them up is a common source of bugs.

| | `vs` — **vscreen_stream** | `vs.v` — **vscreen** |
|---|---|---|
| **Type** | Python class (`io.IOBase`) | C extension object |
| **How obtained** | Passed as first argument to `main()` | `vs.v`, or `pdeck.vscreen(screen_num)` |
| **Purpose** | IO stream interface — text I/O and app lifecycle | Graphics, callbacks, raw keyboard input |
| **`print(..., file=vs)`** | ✓ works — routes through `write()` | ✗ not a stream |
| **`vs.write(s)`** | ✓ delegates to `vs.v.print(s)` | ✗ |
| **`vs.read(n)`** | ✓ blocking read | ✗ |
| **`vs.v.read_nb(n)`** | ✗ | ✓ non-blocking read |
| **`vs.poll()`** | ✓ delegates to `vs.v.poll()` | ✓ |
| **`vs.v.callback(fn)`** | ✗ | ✓ register frame callback |
| **`vs.v.finished()`** | ✗ | ✓ signal frame done |
| **Drawing methods** | ✗ | ✓ `draw_box`, `draw_str`, etc. |

**Rule of thumb:**
- Text output → `print(..., file=vs)` or `vs.write(...)`
- Blocking keyboard input → `vs.read(n)`
- Non-blocking keyboard input → `vs.v.read_nb(n)`
- Graphics / callbacks → `v = vs.v`, then use `v`

```python
def main(vs, args):
  v = vs.v                      # vscreen — graphics and callbacks

  print("hello", file=vs)       # text output via vscreen_stream
  ch = vs.read(1)               # blocking keyboard read via vscreen_stream

  v.callback(my_draw_fn)        # register draw callback via vscreen
  nb = v.read_nb(1)             # non-blocking read via vscreen
```

---

## vscreen module reference

vscreen represents a virtual screen (0–10). All graphics APIs are on this object.

### Getting a vscreen object

In an app, always get it from the `vs` argument — do not create a new one:

```python
def main(vs, args):
  v = vs.v  # vscreen object for this app's screen
```

To work with a specific screen from outside an app:

```Python
screen = pdeck.vscreen([screen_num])
```

If `screen_num` is omitted, uses the current screen.

### Drawing Methods

All drawing methods work when the vscreen is active (current screen). Basically many of methods are wrapper of u8g2 library. See u8g2 reference manual for detail.

#### Basic Shapes

- `draw_pixel(x, y)`
- `draw_line(x1, y1, x2, y2)`
- `draw_h_line(x, y, w)`
- `draw_v_line(x, y, h)`
- `draw_box(x, y, w, h)`
- `draw_frame(x, y, w, h)`
- `draw_rframe(x, y, w, h, r)` - rounded frame
- `draw_rbox(x, y, w, h, r)` - rounded box
- `draw_circle(x, y, radius, opt)`
- `draw_disc(x, y, radius, opt)`
- `draw_triangle(x0, y0, x1, y1, x2, y2)`
- `draw_arc(x, y, rad, start, end)`
- `draw_ellipse(x, y, rx, ry, opt)`
- `draw_filled_ellipse(x, y, rx, ry, opt)`
- `draw_polygon(points_array)` - Draws a polygon from an `int16_t` array. For a triangle, the format must be `[x1, x2, x3, y1, y2, y3]`.

#### 2D3D batch face operations

- `draw_3d_faces(points, indices, dither)` - Specialized high-speed batch renderer for 3D/2D faces. Draws all triangles in one call with internal state caching for dither levels. This function is used with dsplib module's indexed projection functions. See dsplib module reference and example applications, `sphere_test`, `cube_test`.
    `points`: array('h',...) stores vertecies of triangles. Size is 6*number_of_faces
    `indices`: array('H',...) stores face indices (the order of drawing triangles). Size is number_of_faces.
    `dither`: array('b',...) stores dither(color) of each face. Size is number_of_faces.

- `draw_2d_faces(points, indices, dither)` - Alias for `draw_3d_faces` for API clarity when working with 2D projections. 
    `points`: array('h',...) stores vertecies of triangles. Size is 6*number_of_faces
    `indices`: array('H',...) stores face indices (the order of drawing triangles). Size is number_of_faces.
    `dither`: array('b',...) stores dither(color) of each face. Size is number_of_faces.


#### Text Operations

- `draw_str(x, y, text)`
- `draw_utf8(x, y, text)`
- `draw_utf8_v(x, y, text)` - draws UTF8, Japanese style vertical text
- `draw_button_utf8(x, y, flags, width, padding_h, padding_v, text)`
- `get_str_width(text)` - returns text width in pixels
- `get_utf8_width(text)` - returns UTF-8 text width

#### Bitmap Operations

Pocket deck supports XBM and the original XBMR format for image. XBMR is binary format, basically decoded XBM for performance, it also support multiple frames in one file. It also supports texture rendering.


- `draw_image(x, y, image, frame)` - Higher level function to draw image. image is tuple returned by xbmreader.read() or read_xbmr(), which is (name, width, height, data, num_of_frames).
- `draw_xbm(x, y, w, h, xbm_data)` - Draw XBM. xbm_data is binary data. This function remains for compatibility. Use draw_image().
- `capture_as_xbm(x, y, w, h, buffer)` - Capture screen area to XBM format immediately. Reads the framebuffer at call time, so it can tear if the display task is mid-frame. `x` is rounded down to a multiple of 8; `buffer` must be at least `((w+7)>>3) * h` bytes.
- `take_screenshot(x, y, w, h, buffer)` - Like `capture_as_xbm`, but captures at the exact safe point in the display loop (no tearing) and **blocks** until the frame is ready. Returns `True` on success, `False` on timeout or if this vscreen is not the active screen. **Must not be called from inside an `update()` draw callback** — that runs on the display task and would deadlock; call it from a separate app thread instead. Same buffer/size rules as `capture_as_xbm`.
- `draw_polygon_texture(points_array, map_array, image_tuple, [frame_index])` - Draws an affine textured polygon. 
  `points_array`: `array('h', ...)` of `[x1, x2, ..., xn, y1, y2, ..., yn]`.
  `map_array`: `array('h', ...)` of texture coordinates `[u1, u2, ..., un, v1, v2, ..., vn]`.
  `image_tuple`: Standard image tuple `(name, w, h, data, num_frames)`.
  `frame_index`: Optional frame index for multi-frame images.

**Font and Display Settings:**

- `set_font(font_name)` - font_name can be font name or pointer to font data. The following fonts are built-in and can be specified as font name. For custom fonts, font data is raw font data used in u8g2.
  - `u8g2_font_profont11_mf`
  - `u8g2_font_profont15_mf`
  - `u8g2_font_profont22_mf`
  - `u8g2_font_profont29_mf`
  - `u8g2_font_tenfatguys_tf`
  - `u8g2_font_tenthinnerguys_tf`
  - `u8g2_font_t0_11_me` — includes Unicode box drawing and block element characters
  - `u8g2_font_t0_15_me` — includes Unicode box drawing and block element characters
  - `u8g2_font_t0_15b_me` — bold variant, includes Unicode box drawing and block element characters
  - `u8g2_font_t0_17_me` — includes Unicode box drawing and block element characters
  - `u8g2_font_t0_22_me` — includes Unicode box drawing and block element characters
  - `spleen612`
  - `spleen816`
- `set_draw_color(color)` - 0 is black, 1 is white, 2 is xor
- `set_font_mode(mode)` 
- `set_font_direction(dir)` - sets font orientation (0: 0°, 1: 90°, 2: 180°, 3: 270°)
- `set_font_pos_baseline()` - sets font position mode to baseline
- `set_font_pos_bottom()` - sets font position mode to bottom
- `set_font_pos_center()` - sets font position mode to center
- `set_font_pos_top()` - sets font position mode to top
- `set_bitmap_mode(mode)` - 1 for transparent. 
- `set_dither(dither_level)` - Set dither color level, 0 to 16. (0: empty/no drawing, 16: solid color).

#### Buffer Management

Pocket deck has two screen buffer. 0 is main buffer, and user can use buffer 1 as working area.

- `clear_buffer()` - you don't need to use this for buffer 0, system takes care of clearing buffer 0.
- `switch_buffer(buffer_num)` -  switch between buffers (0 or 1)
- `copy_buffer(to_buffer, from_buffer)` - copy buffer contents

### Screen Properties

- `active` (read-only) - Returns `True` if this vscreen is currently active
- `suspend_inactive_screen` (read/write) - Global setting to suspend callbacks for inactive screens

### Callback System

Callback function to be called for every frame update.

- `callback(handler)` Register an screen update callback function. The handler will be called with a boolean parameter indicating if a screen change was requested. This means if False is passed to update() callback, you don't need to draw full screen, you can just call `finished()` and return if you don't need to update screen. Calling `finished()` without any drawing functions saves power. See `tasks` application to see the real usage. You don't need to clear the screen, it is handled by the system.

- `callback_exists()` Check if the callback is still registered.

- `finished()` Notify that the screen update is finished. Should be called in the callback handler. If finished() function is called without calling any of graphic drawing functions, Vscreen module won't update screen, it will save energy.

### Input/Output Operations

> All methods in this section are on the **vscreen** object (`vs.v`), not on `vscreen_stream` (`vs`).
> For blocking text I/O from app code, use `vs.read()` / `print(..., file=vs)` instead.

- `print(text)` Write text to the terminal. Prefer `print(..., file=vs)` from app code — it goes through `vscreen_stream.write()` which calls this internally.

- `send_char(data)` Inject character data as keyboard input.

- `send_key_event(keycode, modifier, event_type)` Inject a keyboard event. It's hardware keycode, not ascii code. See hid_usage_keyboard for keycode list and modifier list.

- `read_nb(max_bytes)` Non-blocking keyboard read. max_bytes can be up to 29. Returns tuple`(bytes_read, data)` where data is a string. Use `encode('ascii')` to convert to bytes. Special keys are escape sequences, e.g. Up arrow is `b'\x1b[A'`. **For blocking reads from app code, use `vs.read(n)` on the stream instead.** Note: `data` is a validated `str`, so reading a span that splits a multi-byte UTF-8 character (e.g. one byte of a pasted/`send_char`'d 2–4 byte char) raises `UnicodeError`. If your app may receive UTF-8 input, use `read_nb_bytes()`.

- `read_nb_bytes(max_bytes)` Same as `read_nb()` but returns `(bytes_read, data)` where `data` is `bytes`. Carries no UTF-8 validation, so it never raises on a multi-byte character split across reads — use this for binary key handling and UTF-8 paste/`send_char` input. The bytes from successive reads can be concatenated to reassemble a complete UTF-8 sequence.

- `poll()` Returns `True` if keyboard input is available. Also available as `vs.poll()` on the stream.

- `get_key_state(key_code)` Get the state of a specific key. Key code is listed in [[hid_usage_keyboard.h]]

- `get_tp_keys()` Get low-level touchpad keys state as bytes:

byte | bit | Description
---- | --- | ------------
0 | 0-7 | Slider position, range is 0 to 40. It returns 0xFF if slider is not pressed.
1 | 0-7 | Touchpad Y, range is 0 to 80. It returns 0xFF if touchpad is not pressed.
2 | 0-7 | Touchpad X, range is 0 to 100. It returns 0xFF if touchpad is not pressed.
3 | 0 | Bottom left button
3 | 1 | Bottom right button
4 | 0-7 | D-pad angle (It can detect the angle on D-pad), Range is 0 to 160.(160 means 360 degree). It returns 0xFF if D-pad is not pressed.
5 | 0 | Up
5 | 1 | Up-right
5 | 2 | Right
5 | 3 | Bottom-right
5 | 4 | Bottom
5 | 5 | Bottom-left
5 | 6 | Left
5 | 7 | Up-left
6 | 0 | 'A' button
6 | 1 | 'B' Button

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

`vscreen_stream` is a Python `io.IOBase` subclass that wraps a `vscreen` C object and exposes it as a standard IO stream. It is the `vs` argument passed to every app's `main()`.

```python
def main(vs, args):
  print("Hello", file=vs)   # text output
  ch = vs.read(1)            # blocking keyboard input
  v = vs.v                   # access underlying vscreen for graphics
```

### Attributes

- `v` — the underlying `vscreen` object for this screen. Use this for all graphics, callbacks, non-blocking input, and any vscreen method not listed below.

### Methods

- `write(message)` — Write a string or bytes to the terminal. Called implicitly by `print(..., file=vs)`. Delegates to `vs.v.print()`.

- `read(n, wait=7)` — Blocking read of up to `n` bytes from keyboard input. Loops with `pdeck.delay_tick(wait)` until input arrives. Returns a string. Use this in app loops instead of `vs.v.read_nb()` when you want to block.

- `poll()` — Returns `True` if keyboard input is available. Delegates to `vs.v.poll()`.

- `async_read(n, wait=20)` — Async variant of `read()`. Rarely used — asyncio is not recommended with threads (see Limitations).

- `ioctl(op, arg)` — Stream protocol support (used by MicroPython internals).

- `register_module(obj)` — Register the app object for remote command access. See the Remote Command Execution section.

## dsplib module

Transformation and sorting utilities using ESP32-S3 SIMD instructions.

- `set_transform_matrix_4x4(matrix, rotation, position, scale)`: 
  Helper function assembles a Row-Major 4x4 transformation matrix (rotation -> scale -> translation).
  - **`matrix`**: 16-element float array to store result.
  - **`rotation`**: float vector `[rx, ry, rz]` in radians.
  - **`position`**: float vector `[tx, ty, tz]` world coordinates. **Note**: Translation is independent of model scale.
  - **`scale`**: float vector `[sx, sy, sz]` model scale.
- `set_transform_matrix_3x3(matrix, rotation, position, scale)`: 
  Assembles a 3x3 2D transformation matrix. Note rotation is float, not array.
- `matrix_mul_f32(A, B, m, n, k, C)`: 32-bit floating point matrix multiplication.
- `matrix_mul_s16(A, B, m, n, k, C, shift)`: 16-bit fixed point matrix multiplication.

- `project_3d_indexed(matrix, verts, indices, normals, light, num_faces, num_verts, fov, cx, cy, out_poly, out_dither, out_depths, temp_verts, temp_norms)`: 
  Optimized 3D engine for indexed models. Transforms shared vertices once and projects faces using an index buffer. Requires **15 arguments**.
  - **`matrix`**: `array('f',...)` 4x4 float matrix (16 elements) containing rotation, scale, and world translation.
  - **`verts`**: `array('f',...)` Flat float array of unique vertices. Format: `[x, y, z]` per vertex.
  - **`indices`**: `array('H',...)` `uint16_t` array of indices into `verts`. Format: `[i1, i2, i3]` per triangle.
  - **`normals`**: `array('f',...)` Flat float array of face normals. Format: `[nx, ny, nz]` per triangle.
  - **`light`**: `array('f',...)` float vector `[lx, ly, lz]` representing directional light.
  - **`num_faces, num_verts`**: Total face and unique vertex counts.
  - **`fov`**: Projection zoom factor (Field of View).
  - **`cx, cy`**: 2D screen center coordinates (e.g., 200, 120).
  - **`out_poly`**: `array('h',...)` `int16_t` output buffer. Format: `[x1, x2, x3, y1, y2, y3]` per face. 
  - **`out_dither`**: `array('b',...)` `int8_t` output buffer. Level 0-16. Culled faces (pointing away from viewer) are set to **-1**.
  - **`out_depths`**: `array('i',...)` `int32_t` output buffer. Stores face Z-depth (scaled by 1024) for sorting.
  - **`temp_verts, temp_norms`**: `array('f',...)` Temporary float buffers of size `num_verts * 3` and `num_faces * 3` for internal transformation.

- `project_2d_indexed(matrix, verts, indices, colors, light, num_faces, num_verts, cx, cy, out_poly, out_dither, temp_verts)`: 
  Optimized 2D engine for indexed models. Supports rotation, scale, and translation via 3x3 matrix. Requires **12 arguments**.
  - **`matrix`**: `array('f',...)` 3x3 float matrix (9 elements).
  - **`verts`**: `array('f',...)` Flat float array of unique 2D vertices. Format: `[x, y]` per vertex.
  - **`indices`**: `array('H',...)` `uint16_t` array of vertex indices. Format: `[i1, i2, i3]` per triangle.
  - **`colors`**: `array('f',...)` Flat float array of dither values per vertex (1.0 to 16.0).
  - **`light`**: float multiplier for vertex colors.
  - **`num_faces, num_verts`**: Total face and unique vertex counts.
  - **`cx, cy`**: 2D screen center/offset coordinates.
  - **`out_poly`**: `array('h',...)` `int16_t` output buffer. Format: `[x1, x2, x3, y1, y2, y3]` per face. Size: `num_faces * 6`.
  - **`out_dither`**: `array('b',...)` `int8_t` output buffer. Level 0-16. Size: `num_faces`.
  - **`temp_verts`**: `array('f',...)` Temporary float buffer of size `num_verts * 2` for internal transformation.

- `sort_indices(indices, depths, [start_id])`: A helper function for depth sorting. Performs an in-place `qsort` of `uint16_t` face indices based on `int32_t` depths (descending).
  - **`indices`**: `array('H',...)` `uint16_t` array of face indices. Size: `num_faces`. 
  - **`depths`**: `array('i',...)` `int32_t` array of face Z-depths. Size: `num_faces`.
  - **`start_id`** (optional): If provided, the `indices` buffer is automatically filled with a sequential range starting from `start_id` (e.g., `start_id, start_id+1, ...`) before sorting. This is highly recommended for dynamic models where the number of faces changes.

### 3D Programming Notes

See 3D examples under `/sd/lib/examples/`. 

`cube_test`, `sphere_test`, and `bounce_sphere` are good examples.

- **Less-Allocation Rendering**: To reduce heap fragmentation and GC pauses, pre-allocate all transformation buffers (`array.array('f', [0.0]*3)`) and result buffers in `__init__`. 
- **Transform Pipeline**: Use `dl.set_transform_matrix_4x4` to assemble matrices in C. It is significantly faster than Python-side matrix math and maintains consistent rotation order.
- **Time-Based Physics**: For a consistent simulation speed regardless of FPS, use `time.ticks_us()` to calculate `delta time`. If you want to normalize your `dt` based on 60 FPS, then  `dt = ticks_diff(now, last) / 16666.0`. 
- **Depth Sorting**: Always use `dl.sort_indices` for correct transparency and occlusion. Sorting is performed on face Z-depths calculated during projection.

## esclib module

esclib module is a small utility to generate basic escape sequences.

## anm module reference

The `anm` module provides a flexible keyframe-based animation system with various easing curves.

### Interpolation Functions (Curves)

- `linear(t)`: Constant speed.
- `ease_in(t)`: Quadratic acceleration.
- `ease_out(t)`: Quadratic deceleration.
- `ease_in_out(t, [m=0.5])`: Acceleration then deceleration. Optional midpoint `m` shifts the transition timing.
- `ease_out_in(t, [m=0.5])`: Deceleration then acceleration.
- `spring(t)`: Bouncy overshoot effect.
- `jump(t)`: Step function (0.0 until completion, then 1.0).

### anm_object

Represents an individual animation.

- `__init__(duration_ms, props, loop=False, auto_unregister=False)`
    - `duration_ms`: Total animation time.
    - `props`: Dictionary of `{ 'property_name': [easing_func, val0, val1, ...] }`. Keyframes can be lambdas for custom easing: `[lambda t: anm.ease_in_out(t, 0.8), 0, 100]`.
    - `loop`: If True, the animation restarts automatically.
    - `auto_unregister`: If True, the sequencer removes this object upon completion.

- `seek(norm_t)`: Jumps to a specific point in the animation (0.0 to 1.0).
- `get_time()`: Returns current normalized time (resets to 0.0 if looping).
- `get_elapsed()`: Returns absolute progress (continues past 1.0 for loops).

### anm_sequencer

Manages multiple `anm_object` instances.

- `__init__()`: Creates a new sequencer.
- `register(key, obj)`: Adds an animation object and starts it.
- `unregister(key)`: Removes an animation object.
- `update(t_ms)`: Updates all registered animations. Usually called in the screen update loop with `time.ticks_ms()`.
- `get_obj(key)`: Returns the registered `anm_object` by its key.
- `__iter__()`: Allows iterating over active animations: `for anim in sequencer:`.

## font2d module reference

Provides vector-based 2D text rendering using `.g3df` font files.

### font_2d

- `__init__(filename)`: Loads a font file.
- `get_glyph(char)`: Returns a `glyph_2d` object. Glyphs are cached internally after first load.

### text_renderer_2d

- `__init__(font_obj, vscreen)`: Creates a renderer for the specified font and screen.
- `set_font(font_obj)`: Changes the active font.
- `get_width(text, scale)`: Returns the total width of a text string in pixels.
- `draw_text(text, x, y, scale=1.0, rot=0.0, scale_x=None, scale_y=None, light=1.0)`: 
    - `scale_x / scale_y`: Optional independent scaling (stretching/squashing).
    - `light`: Multiplier for vertex colors (useful for fading or highlighting).

### Anm module example usage

See animation_example for complete example code.

```python
import anm
import time

class AnimDemo:
  def __init__(self, v):
    self.v = v
    self.seq = anm.anm_sequencer()
    
    # Animate 'x' with custom 80% midpoint ease
    box_anim = anm.anm_object(2000, {
      'x': [lambda t: anm.ease_in_out(t, 0.8), 0, 300],
      'y': [anm.spring, 50, 150]
    }, loop=True)
    
    self.seq.register('box', box_anim)

  def update(self, e):
    v = self.v
    self.seq.update(time.ticks_ms())
    anim = self.seq.get_obj('box')
    
    v.set_draw_color(0)
    v.draw_box(0, 0, 400, 240)
    v.set_draw_color(1)
    v.draw_box(int(anim.x), int(anim.y), 50, 50)
    v.finished()

```

## ssh module

The `ssh` module provides SSH remote execution and file transfer. Requires an active WiFi connection. The default private key is `/config/ssh/id_rsa`.

`user@host` shorthand is accepted wherever `host` is a parameter — the username embedded in the string is used unless overridden by an explicit `username` argument.

All network operations run in a dedicated FreeRTOS task to avoid stack exhaustion on the MicroPython task.

### ssh.session

Persistent SSH session — connect once, run many operations. Supports the `with` statement.

```python
ssh.session(host [, username, password, identity])
```

- `host`: hostname or IP, optionally `user@host`
- `username`: default `"root"`
- `password`: default `""`
- `identity`: path to private key file; default `/config/ssh/id_rsa`

Raises `OSError` if the connection fails or WiFi is not available.

**Methods:**

- `exec(cmd)` — Run a command. Returns `(exit_code, output_bytes)`. Raises `OSError` on failure.
- `put(local, remote)` — Upload a file. Returns `0` on success.
- `get(remote, local)` — Download a file. Returns `0` on success.
- `close()` — Close the session.

```python
import ssh

with ssh.session("pi@192.168.1.10") as s:
  rc, out = s.exec("uname -a")
  print(out.decode())
  s.put("/sd/data.txt", "/home/pi/data.txt")
```

### ssh.exec

One-shot command execution. Opens a connection, runs the command, and closes.

```python
ssh.exec(host, command [, username, password, identity])
```

Returns `(exit_code, output_bytes)`. Raises `OSError` on failure.

```python
rc, out = ssh.exec("192.168.1.10", "ls /tmp", "pi")
print(rc, out.decode())
```

### ssh.scp

One-shot file copy using SCP protocol.

```python
ssh.scp(src, dst [, username, password, identity])
```

Returns `0` on success. `src` and `dst` follow standard SCP notation (`user@host:path` for remote).

```python
ssh.scp("/sd/file.txt", "pi@192.168.1.10:/home/pi/file.txt")
```

