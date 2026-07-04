# Building a good-looking dashboard / graphical app

Read this before you write a graphical Pocket Deck app that shows data — a
dashboard, a chart, a status screen, a meter. It captures the house style so
your app looks designed, not thrown together. Follow it, then copy the closest
example as a starting skeleton.

The screen is **400 x 240, 1-bit monochrome**. There is no colour and no
grayscale — only ink or no-ink, plus ordered **dither** to fake shades.

## Worked examples

All under `/sd/lib/examples/`. Each is a complete, self-contained app you can
`cp` to `/sd/py/` and edit:

- **`dashboard_bars.py`** — bar chart. Staggered grow-in animation, dither-filled
  bars with the peak solid, value labels centered over each bar, a KPI footer
  and metric pager. `r dashboard_bars`
- **`dashboard_line.py`** — line / area trend. Dithered area fill, journal-style
  morph-from-flat animation, a big current value + delta chip, min/max axis
  labels on cleared boxes. `r dashboard_line`
- **`dashboard_gauge.py`** — radial gauges. A 270° main gauge plus two donut
  rings, each precomputed once as a fan of `draw_polygon` quads (fast — no
  per-frame trig) and filled to the real value, spring sweep, centered
  percentages. `r dashboard_gauge`
- **`journal.py`** (in `/sd/lib/`, not examples) — a full real dashboard: month
  paging with slide animation, checkbox grid, and a numeric line graph. The gold
  standard for a data screen with navigation.

## Design rules

1. **Flat, not skeuomorphic.** No gradients, no drop shadows, no fake bevels.
   Compose from solid boxes, thin rules (`draw_h_line`), frames, and dither
   fills. A solid **inverted header bar** (`draw_box(0,0,400,20)` then draw text
   in `set_draw_color(0)`) is the standard title anchor — see every example.

2. **Always measure text before you place it.** Never hard-code an x for a label
   whose contents vary. Use `get_utf8_width(text)` (or `get_str_width`):
   - center in a box:  `x + (w - v.get_utf8_width(s)) // 2`
   - right-align to an edge:  `right_edge - v.get_utf8_width(s)`
   - truncate with an ellipsis when it would overflow.
   Unmeasured text is the #1 way a dashboard ends up with numbers running off
   the edge or overlapping. The examples wrap these in `center_x` / `right_x` /
   `fit` helpers — copy them.

4. **Fonts: stick to the profont family** (matches `journal.py` and
   `analog_clock.py`): `u8g2_font_profont15_mf` for body/labels,
   `u8g2_font_profont22_mf` and `u8g2_font_profont29_mf` for big read-out
   numbers. They are monospaced and crisp at this size. Avoid mixing in lots of
   different faces — one body size and one big size reads as designed.

5. **Animate the entrance with `anm`.** A dashboard that draws itself in feels
   alive. Use one `anm_sequencer` + an `anm_object` timeline and apply an easing
   curve: `ease_out` for reveals/bars, `spring` for a needle that overshoots and
   settles, or morph each value from a flat baseline up to the data
   (journal.py / dashboard_line.py). Re-play on data change by `seek(0.0)`. See
   the `anm module` section of `app_development.md` and the examples' `replay()`.

6. **Keep frames cheap — precompute geometry, batch with `draw_polygon`.** Don't
   recompute `sin`/`cos` or issue hundreds of `draw_line`/`draw_arc` calls every
   frame. If a shape's vertices are fixed (a gauge ring, a dial), build them once
   into an `array('h')` and each frame just `draw_polygon()` the slices — one
   batched C call per face. `set_dither()` still shades the fill. See
   `dashboard_gauge.py` and `analog_clock.py`'s timer disc. Only the *how much*
   (how many faces to draw) changes per frame, not the vertices.

## The app skeleton (frame callback + key loop)

Every example shares this shape. Draw in a `callback` the system calls per
frame; **only actually redraw while animating or after input**, otherwise just
`finished()` so the device stays cool. Block for keys on the `vs` stream in a
separate loop.

```python
def main(vs, args):
  v = vs.v
  import esclib as elib
  el = elib.esclib()
  v.print(el.erase_screen()); v.print(el.home())
  v.print(el.display_mode(False))          # hide the text cursor
  app = MyDashboard(vs)
  v.callback(app.update)                    # update(e) draws one frame
  try:
    app.key_loop()                          # blocks on vs.read(1)
  finally:
    v.callback(None)
    v.print(el.display_mode(True))
```

```python
def update(self, e):
  if not self.v.active:
    self.v.finished(); return
  self.seq.update(time.ticks_ms())
  if e or self.dirty or self._animating():
    self.draw()                             # clear_buffer(); ...; v.finished()
    self.dirty = False
  else:
    self.v.finished()                       # nothing changed — cheap frame
```

Arrow keys arrive as escape sequences (`\x1b[C` = Right, `\x1b[D` = Left,
`\x1b[A` = Up, `\x1b[B` = Down); the examples' `_read_key()` decodes them.


