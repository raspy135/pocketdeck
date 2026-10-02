# Trip plan

Purpose: Write a day/weekend trip plan as Markdown that `tripplan` renders as a
scrolling OpenStreetMap + stop panel. The AI authors the file; the app only
reads it. Coordinates are baked in at authoring time so the viewer works
offline on the beach with no network.

Trigger: "make a trip plan for ...", "plan a day in ...", "tripplan <name>".

## Inputs to settle first

Ask only what is missing; do not interrogate.

- Where and when (one day? multi-day?), and who is coming.
- What the day is *for* (surf / food / museums / kids) - it decides which stops
  earn their place.
- Start and end point (hotel, airport, home).
- Anything already booked or non-negotiable.
- Seasonal facts worth putting in the header bar: tide window, sunset, park
  open/close, a game or festival that will move traffic.

## sequence

1. **List the candidate stops in order**, with a one-line reason for each. Keep
   8-14 for one day. Fewer is better than optimistic.

2. ** Confirm the items with user first before you go further**, make sure the user is happy with the list. Save as normal Markdown if user asks.

3. **Geocode every place with tripgeo, and validate.** Compute a generous
   bounding box around the area first (roughly +/- 0.15 deg), then:

   ```
   tripgeo -b 33.90,34.20,-119.10,-118.10 "30000 Pacific Coast Hwy, Malibu" ...
   tripgeo -f /sd/work/places.txt -b south,north,west,east     # batch, 1 place/line
   ```

   Verdicts: `ok` = name matched and inside the box - usable. `OUT` = real place
   but outside your box (wrong town, or your box is too tight). `far` = inside
   the box but the name does not look like the query. `FAIL` = no answer.

   Query-form rules learned on this device (Nominatim):
   - **Use `street address, city`**, not `brand, neighborhood`.
     `Trader Joes Silver Lake` -> FAIL; `2738 Hyperion Avenue, Los Angeles` -> ok.
   - Drop apostrophes and punctuation from the brand; they break matching.
   - A park/venue often resolves to its **entrance**, ~1 km from the feature
     itself. Fine for a map dot; if the exact spot matters (a specific beach
     access, a pier end), query the street address instead.
   - Natural features want the feature word: `Point Dume`, `Zuma Beach` work;
     adding `, Montana` returns nothing at all.
   - Rate limit is one request/second; `tripgeo` enforces it and caches in
     `/sd/work/tripgeo.json`, so re-running costs nothing.

   **Never write a coordinate that is not `ok`.** Never estimate one from
   memory, and never reuse a neighbour's. If a place will not geocode, ask the
   user or replace it with one that does.

4. **Write the plan** to `/sd/Documents/trips/<name>.md`. `<name>` is short,
   lowercase, no spaces (`malibu-sun` is fine - `tag:` sanitises it).

   Prose is free-form and the app never reads it. The app reads **only** `#`
   and `##` headings and the ```tripplan fences:

   ````markdown
   # MALIBU SUN SEP 20                     <- H1 = header bar, <= 21 chars

   ```tripplan
   facts: LOW 12:14  SET 18:53             <- repeatable, one per line
   provider: osm                           <- osm (fast) | topo (relief)
   tag: malibu                             <- tile cache key, <= 12 chars
   map_note: Map data (c) OpenStreetMap    <- keep this, OSM policy requires it
   ```

   ## Surf: Zuma Beach                     <- H2 = stop title, <= 32 chars

   Full prose for the human reader goes here - parking, fees, what to bring,
   backup plans. Markdown tables, lists, bold: all ignored by the parser.

   ```tripplan
   when: 9:45                             <- <= 10 chars
   label: Zuma                            <- map marker word, <= 13 chars
   cat: SURF                              <- chip: START FOOD SURF TOUR DRIVE VIEW
   addr: 30000 PCH - park the north lots  <- <= 51 chars
   lat: 34.0214393
   lon: -118.8310349
   body: Wide sand, sand bottom, a lifeguard tower every few hundred yards.
     The rock points at Surfrider are a no for a first day. Put the 8 ft
     soft-top on him.                      <- <= 220 chars, indent to wrap
   tip: Leash is not optional             <- <= 54 chars
   ```

   ## PCH to the 101                       <- a leg, not a destination

   ```tripplan
   when: 9:00
   label: Leg
   cat: DRIVE
   addr: Kanan Rd
   body: Fill the tank in the valley; Malibu fuel is expensive.
   tip: Dodgers play at 1:10, avoid Chavez Ravine after
   lat: 34.05
   lon: -118.70
   drive: true                            <- route bends through it, no number
   ```
   ````

   - `lat`/`lon` are separate keys, decimal degrees, no quotes.
   - A long `body`/`tip` wraps by **indenting the continuation lines one or two
     spaces**; the parser rejoins them with a single space.
   - `drive: true` is for a point on the road so the drawn route actually bends.
     It keeps the panel and the hop distance but draws a small tick instead of a
     numbered disc. Never give a real destination this flag.
   - Plain ASCII: `profont` has no `(c)`, no curly quotes, no emoji, no em dash.
     Write `(c)` and `-`.
   - `tag` names every cached tile file. Reusing an earlier trip's tag (e.g.
     `tag: malibu` for a second Malibu plan) means **no re-download**; a new tag
     means the tiles fetch again on first open.

5. **Check the budgets while writing.** These are the real panel limits,
   measured with `get_utf8_width()`, not style advice - over budget is clipped
   with ` ..` and looks broken:

   | field | limit | where it is drawn |
   |---|---|---|
   | H1 title | 21 | inverted header bar |
   | `title` (H2) | 32 | profont22 headline |
   | `when` | 10 | rounded chip |
   | `cat` | 14 | framed chip |
   | `addr` | 51 | profont11, 80px reserved for "N km drive" |
   | `body` | 220 | 55 chars/line x 4 lines, then ` ..` |
   | `tip` | 54 | profont11, after the app's `TIP: ` prefix |
   | `label` | 13 | map marker (11 when it is a neighbour of the current stop) |

   Compress by cutting clauses, not by abbreviating words. `body` is one
   decision-relevant paragraph, never a checklist - the checklist belongs in
   the prose above it. If two stops are the same place (`Sunset` on the beach
   you are already at), reuse the coordinates so the app can say `same spot`.

6. **Validate mechanically before you show it:**

   ```
   tripplan <name> --check      # errors are fatal, warnings are budget clips
   tripplan <name> --dump       # the exact 9/10-tuples the engine receives
   ```

   Fix every `warn:` by shortening the text, not by raising the limit. Treat
   `need at least 2 usable stops` as a sign the fences are malformed.

7. **Open it** with `tripplan <name>` (or launch the `tripplan` app with the name as its argument). Don't debug the app, do this step quick.

8. **Tell the user** the file path, the stop count, and anything you could not
   geocode or verify. Say plainly which numbers are estimates (fees, drive
   times) - the plan is used in the real world.

## notes

- The document is the source of truth. Edit the `.md`, re-run `--check`, reopen.
  `tripmap.py` never needs touching to add a trip.
- Keys the app knows are silently ignored otherwise: `facts provider zoom tag
  map_note invert` at trip level, `when label cat addr body tip lat lon drive`
  per stop. A misspelled key vanishes - `--dump` catches that.
- Reference implementation of the data shape: `/sd/py/trip_malibu.py` (a
  hand-written `trip_<name>.py`, still works via `tripmap malibu`).
  `/sd/Documents/trips/malibu.md` is its markdown twin, proven to produce the
  identical `TRIP` dict.
- Coordinates must come from `tripgeo` (or a web lookup you then cross-check),
  never from memory. This is the rule that makes the rest of the file safe to
  skim.
- WiFi is not needed to *view* a plan once the tiles are cached, but the first
  open of a new trip downloads them. Do `tripplan <name>` at home, not at the
  trailhead. Press `g` in the app to refetch tiles if the map shows hatching
  where a hole should not be.
