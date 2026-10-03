# Pocket Deck file browser
#
# Browse internal storage and SD-card directories.
# Text files open in PEM; WAV files open in wavfileplay.

import os
import pdeck
import pdeck_utils


START_PATH = "/sd"


def join_path(parent, name):
  if parent == "/":
    return "/" + name
  return parent.rstrip("/") + "/" + name


def parent_path(path):
  if path == "/":
    return "/"

  clean = path.rstrip("/")
  slash = clean.rfind("/")

  if slash <= 0:
    return "/"

  return clean[:slash]


def format_size(size):
  if size < 1024:
    return "%d B" % size

  if size < 1024 * 1024:
    return "%.1f KB" % (size / 1024)

  return "%.1f MB" % (size / (1024 * 1024))


def read_directory(path):
  entries = []

  try:
    for item in os.ilistdir(path):
      name = item[0]
      file_type = item[1]
      is_dir = bool(file_type & 0x4000)

      size = 0
      if len(item) > 3 and item[3] is not None:
        size = item[3]

      entries.append({
        "name": name,
        "path": join_path(path, name),
        "is_dir": is_dir,
        "size": size,
      })

  except OSError as error:
    return [], str(error)

  entries.sort(
    key=lambda entry: (
      0 if entry["is_dir"] else 1,
      entry["name"].lower(),
    )
  )

  return entries, None


def find_free_screen():
  # Screen numbers are zero-based. Leave screen 9 for Home.
  for screen_num in range(2, 9):
    if not pdeck.cmd_exists(screen_num):
      return screen_num

  return None


def open_file(path):
  lower = path.lower()

  if lower.endswith((
    ".txt",
    ".md",
    ".py",
    ".json",
    ".csv",
    ".log",
    ".ini",
    ".cfg",
  )):
    command = ["pem", path]

  elif lower.endswith(".wav"):
    command = ["wavfileplay", path]

  else:
    return "unsupported", None

  screen_num = find_free_screen()

  if screen_num is None:
    return "no_screen", None

  launched = pdeck_utils.launch(command, screen_num)

  if launched:
    return "opened", screen_num

  return "failed", screen_num


def terminal_geometry(vs):
  try:
    terminal_width, terminal_height = vs.v.get_terminal_size()
  except Exception:
    terminal_width = 48
    terminal_height = 20

  # Never draw in the final column. Filling the final column can trigger
  # automatic wrapping on terminal implementations.
  content_width = max(20, terminal_width - 1)
  visible_rows = max(4, terminal_height - 6)

  return content_width, visible_rows


def fit_line(text, width):
  text = str(text)

  if len(text) > width:
    return text[:width]

  return text + (" " * (width - len(text)))


def cursor_to(row, column=1):
  return "\x1b[%d;%dH" % (row, column)


def entry_line(entry, is_selected, width):
  marker = ">" if is_selected else " "
  description = "[DIR]" if entry["is_dir"] else format_size(entry["size"])

  size_width = 10
  name_width = max(8, width - size_width - 3)

  row = "%s %-*s %*s" % (
    marker,
    name_width,
    entry["name"][:name_width],
    size_width,
    description,
  )

  return fit_line(row, width)


def render_browser(vs, path, entries, selected, scroll, message):
  width, visible_rows = terminal_geometry(vs)
  chunks = []

  chunks.append(cursor_to(1) + fit_line("FILES  %s" % path, width))
  chunks.append(cursor_to(2) + fit_line("=" * width, width))

  for row_offset in range(visible_rows):
    screen_row = 3 + row_offset
    entry_index = scroll + row_offset

    if entry_index < len(entries):
      line = entry_line(
        entries[entry_index],
        entry_index == selected,
        width,
      )
    elif not entries and row_offset == 0:
      line = fit_line("  This folder is empty.", width)
    else:
      line = " " * width

    chunks.append(cursor_to(screen_row) + line)

  footer_row = 3 + visible_rows
  chunks.append(cursor_to(footer_row) + fit_line("-" * width, width))
  chunks.append(
    cursor_to(footer_row + 1)
    + fit_line("Up/Down select | Enter open | Backspace back", width)
  )
  chunks.append(
    cursor_to(footer_row + 2)
    + fit_line("R refresh | Q quit", width)
  )
  chunks.append(cursor_to(footer_row + 3) + fit_line(message, width))

  vs.write("".join(chunks))
  return visible_rows


def redraw_selection(vs, entries, old_selected, new_selected, scroll):
  width, visible_rows = terminal_geometry(vs)
  chunks = []

  for index in (old_selected, new_selected):
    if index < scroll or index >= scroll + visible_rows:
      continue

    if index < 0 or index >= len(entries):
      continue

    screen_row = 3 + (index - scroll)
    chunks.append(
      cursor_to(screen_row)
      + entry_line(entries[index], index == new_selected, width)
    )

  if chunks:
    vs.write("".join(chunks))


def redraw_message(vs, message):
  width, visible_rows = terminal_geometry(vs)
  footer_row = 3 + visible_rows
  vs.write(cursor_to(footer_row + 3) + fit_line(message, width))


def main(vs, args):
  vs.write("\x1b[2J\x1b[H\x1b[?25l")

  path = START_PATH
  if len(args) > 1:
    path = args[1]

  selected = 0
  scroll = 0
  message = ""
  entries = []
  needs_reload = True
  needs_full_redraw = True

  try:
    while True:
      if needs_reload:
        entries, error = read_directory(path)

        if error:
          path = parent_path(path)
          selected = 0
          scroll = 0
          message = "Cannot read folder: %s" % error
          entries, error = read_directory(path)

          if error:
            entries = []

        if selected >= len(entries):
          selected = max(0, len(entries) - 1)

        needs_reload = False
        needs_full_redraw = True

      width, visible_rows = terminal_geometry(vs)

      if selected < scroll:
        scroll = selected
        needs_full_redraw = True

      if selected >= scroll + visible_rows:
        scroll = selected - visible_rows + 1
        needs_full_redraw = True

      if needs_full_redraw:
        render_browser(vs, path, entries, selected, scroll, message)
        needs_full_redraw = False

      key = vs.read(1)

      if key == "\x1b":
        key += vs.read(2)

      old_selected = selected
      old_scroll = scroll

      if key == "\x1b[A":
        if selected > 0:
          selected -= 1
        message = ""

      elif key == "\x1b[B":
        if selected < len(entries) - 1:
          selected += 1
        message = ""

      elif key in ("\r", "\n"):
        if not entries:
          continue

        entry = entries[selected]

        if entry["is_dir"]:
          path = entry["path"]
          selected = 0
          scroll = 0
          message = ""
          needs_reload = True
          continue

        result, screen_num = open_file(entry["path"])

        if result == "opened":
          message = "Opened on screen %d" % (screen_num + 1)
        elif result == "no_screen":
          message = "No free application screen"
        elif result == "unsupported":
          message = "No viewer assigned for this file type"
        else:
          message = "Viewer failed to launch"

        redraw_message(vs, message)
        continue

      elif key in ("\b", "\x7f"):
        if path != "/":
          path = parent_path(path)
          selected = 0
          scroll = 0
          message = ""
          needs_reload = True
        continue

      elif key in ("q", "Q"):
        return

      elif key in ("r", "R"):
        message = "Refreshed"
        needs_reload = True
        continue

      else:
        continue

      if selected < scroll:
        scroll = selected
      elif selected >= scroll + visible_rows:
        scroll = selected - visible_rows + 1

      if scroll != old_scroll:
        needs_full_redraw = True
      elif selected != old_selected:
        redraw_selection(vs, entries, old_selected, selected, scroll)
        redraw_message(vs, "")

      pdeck.delay_tick(1)

  finally:
    vs.write("\x1b[?25h")
