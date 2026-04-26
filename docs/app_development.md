
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

`vs` is vscreen_stream object for the app, and `args` are command arguments passed to the app.

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



## Pdeck module reference

Pdeck module controls Pocket Deck system features and peripherals.

- `change_screen(screen)` Change screen to the given number.

- `change_priority(priority)` Set current application as priority. This might cause system performance issue, basically it's not recommend to use. Priority is bool. True for priority task.
- `clipboard_copy(string)` Copy string data to clipboard which can be used between applciations. (C-S-v to paste the data from clipboard)

- `clipboard_paste()` Paste data from clipboard. Return: Data in the clipboard.

- `cmd_exists(screen_num)` Checks if an application exists in the specified screen number(0 based).

- `cmd_execute(command, screen_num_cmdshell, screen_num_dest)` Execute command in command shell. Screen_nym_cmdshell is screen numer of command shell instance.
Usually it will be 1(0 based number) because command shell is always running on screen 2). screen_num_dest is the screen number you want to execut the command.

- `delay_tick(tick)` Sleep in specified ticks. It's similar to time.sleep_ms(), but the unit is in tick, and it will perform better yielding. MicroPython's sleep_ms() does accurate sleeping but it frequently checks the time. It will give better CPU utilization when you don't need precise time sleep.

- `get_screen_num()` Returns the current screen number.

- `get_screen_size()` Returns a tuple of the screen size. With the current display, it would be (400,240)

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

#### 3D operations

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

Pocket deck supports XBM and the original XBMR format for image. XBMR is binary format, basically decoded XBM for performance, it also support multiple frames in one file.


- `draw_image(x, y, image, frame)` - Higher level function to draw image. image is tuple returned by xbmreader.read() or read_xbmr(), which is (name, width, height, data, num_of_frames).
- `draw_xbm(x, y, w, h, xbm_data)` - Draw XBM. xbm_data is binary data. This is tuned version for performance.
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

- `callback(handler)` Register an screen update callback function. The handler will be called with a boolean parameter indicating if a screen change was requested. This means if False is passed to update() callback, you don't need to draw full screen, you can just call `finished()` and return if you don't need to update screen. Calling `finished()` without any drawing functions saves power. See `tasks` application to see the real usage.

- `callback_exists()` Check if the callback is still registered.

- `finished()` Notify that the screen update is finished. Should be called in the callback handler. If finished() function is called without calling any of graphic drawing functions, Vscreen module won't update screen, it will save energy.

### Input/Output Operations

- `print(text)` Print text to the terminal. 

- `send_char(data)` Send character data as keyboard input.

- `send_key_event(key, modifier, event_type)` Send keyboard event.

- `read_nb(max_bytes)` Read up to `max_bytes` from keyboard input. Returns tuple `(bytes_read, data)`. This is non-blocking function. Special keys are recorded as escape sequence. For example, Up arrow key is b'\x1b[A'.

- `poll()` Check if there's input available. Returns `True` if data is available.

- `get_key_state(key_code)` Get the state of a specific key. Key code is listed in [[hid_usage_keyboard.h]]

- `get_tp_keys()` Get low-level touchpad keys state as bytes. 

byte | bit | Description
---|-----|------
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

vscreen_stream is Python wrapper of vscreen object.  vscreen_stream provides stream object interface. read(), write(), async_read(), ioctl() and poll() are supported.

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

## misc_utils module

misc_utils module is a small utility to support some functions. Currently it only supports input().
