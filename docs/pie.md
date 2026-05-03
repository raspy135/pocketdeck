# Pie audio sequencer

The `Pie` framework is a high-level, mini-notation based sequencer designed for the Pocket deck audio engine, and the syntax is inspired by TidalCycles and Strudel. It allows you to compose complex rhythms, melodies, and effects chains using simple strings.

## The Pie Class

The `Pie` class is the central heart of the sequencer. It manages timing (BPM), schedules events, and coordinates playback between instruments and effects.

## Supported audio modules

Pie supports all audio modules in Pocket deck's audio module. 

- Sampler : Play samples, great for drums
- Wavetable : Wavetable synth, great for melodies
- Echo, compressor, filter for effects
- Router : for signal routing

### Basic Usage

```python
from pie import Pie, PieSampler
import time

def main(vs, args):
    p = Pie(bpm=120)
    with p, PieSampler(4) as drums:
        drums.load_wav(0, "/sd/kick.wav")
        
        p.add(drums, "0 . . . 0 . . .") # Simple kick pattern
        
        with p:
            while True:
                # process_event must be called in your main loop periodically
                p.process_event()
                time.sleep(0.1)
                # Your main loop logic here
```

### Methods

- `__init__(bpm=120, startup_delay_ms=100)`
- `add(instrument, pattern)`
  Adds an instrument and a pattern (string or pre-configured `Pattern` object) to the mix. Returns an index for later updates.
- `pattern(instrument, data)`
  Creates a `Pattern` object for a specific instrument. You can apply pattern methods to modify the pattern.
- `update(index, pattern)`
  Hot-swaps a pattern string for an existing track.
- `remove(index)`
  Removes a track from the sequencer.
- `schedule_update(cycle, index, pattern)`
  Schedules an update to occur automatically at a specific cycle in the future. The pattern is pre-compiled immediately to ensure it does not cause audio glitches when the update fires.
- `schedule_remove(cycle, index)`
  Schedules a track removal to occur automatically at a specific cycle.
- `process_event()`
  **Must be called in your main loop.** This processes timing and dispatches events to the audio engine.
- `process_interactive(filename, loc)`: Standard interactive mode entry point.
- `get_tick_from_cycle(cycle)`: Calculates the specific audio tick (sample count) for a given cycle. Useful for scheduling timed events with `master.add(module, tick)`.
- `clear()`: Clears all tracks from the sequencer.
- `start()`: Starts the sequencer manually, it's useful when `with` statement is not suitable.
- `stop()`: Stops the sequencer manually, it's useful when `with` statement is not suitable.



---

## Interactive Mode (Live Coding)

Pie supports a powerful interactive mode that allows you to change patterns and parameters in real-time without restarting your script. You still need to setup modules in the main script.

### Setup

In your main loop, call `process_interactive` with a filename and a dictionary of local variables you want to expose to the live script.

```python
loc = {
    'p': p,
    'drums': drums,
    'synth': synth
}

while True:
    p.process_event()
    p.process_interactive("/sd/data/int.py", loc)
    time.sleep(0.1)
```

### The Live Script (`int.py`)

In your live script, you can clear existing tracks and add new ones using the exposed objects:

```python
# int.py
p.clear()
p.add(drums, "[0 0 1 0]*2")
p.add(synth, "C3maj Amin")
```

The sequencer will automatically reload this file once per cycle when the progress is past 30%, ensuring smooth updates.

---

## Pattern Syntax (Mini-Notation)

Pie uses a "mini-notation" inspired by TidalCycles to represent time and rhythm.

### 1. Steps and Silence
- **Space-separated**: Each element occupies one equal "step" of the cycle.
- **Rests (`~` or `.`)**: Represent silence.
- `"0 . 0 ~"`: Plays on steps 1 and 3 of 4.

### 2. Groups `[ ]`
- Groups fit multiple notes into a single step.
- `"[0 1 2 3] 4"`: Plays four rapid notes in the first half of the cycle, and a '4' in the second half.

### 3. Alternation `< >`
- Picks one element per cycle, rotating through the list.
- `"<0 1 2> 3"`: 
  - Cycle 0: `0 3`
  - Cycle 1: `1 3`
  - Cycle 2: `2 3`
- **Nesting**: Alternations can be nested inside groups for complex variations.
  - `"[0 1 <2 0>]"`: The third step will alternate between `2` and `0` every cycle.

### 4. Layers `,`
- Plays multiple patterns simultaneously within a group or at the top level.
- `"[0 1, 4 5]"`: Plays `0 1` and `4 5` at the same time.

### 5. Modifiers
- **Repeat `*n`**: Repeats the preceding element `n` times within its step.
  - `"0*4"`: Plays `0` four times in one step.
- **Stretch `/n`**: Stretches the element to last over `n` cycles.
  - `"0/2"`: Plays `0` once every 2 cycles.
- **Weight `@n`**: Adjusts the relative duration of an element in a group.
  - `"[0@3 1]"`: `0` occupies 75% of the step, `1` occupies 25%.

---

## Synthesizer & Note Data

These features are primarily available for `PieWavetable` instruments.

### 1. Pitch and Notes
- **MIDI Numbers**: Integers (e.g., `60`).
- **Note Strings**: Standard notation (e.g., `C4`, `F#3`).
- **Chords**: Parsed into simultaneous notes (e.g., `Cmaj`, `Cm`).
- **Chord Voicing (Inversions)**: Use `:n` suffix to rotate notes.
  - `C4maj:1`: First inversion (move bottom note up an octave).
  - `C4maj:2`: Second inversion.
  - `C4maj:-1`: Move top note down an octave.
- **Scale Indices**: When a scale is set via `.scale()`, integers are treated as scale degrees (e.g., `0 1 2`).

### 2. Available Chords
The following chord shorthands are supported. Intervals are relative to the root MIDI note.

| Suffix | Intervals | Type |
| :--- | :--- | :--- |
| `maj` | `0, 4, 7` | Major Triad |
| `m` | `0, 3, 7` | Minor Triad |
| `maj7` | `0, 4, 7, 11` | Major 7th |
| `m7`, `min7` | `0, 3, 7, 10` | Minor 7th |
| `7`, `sev` | `0, 4, 7, 10` | Dominant 7th |
| `6` | `0, 4, 7, 9` | Major 6th |
| `m6` | `0, 3, 7, 9` | Minor 6th |
| `9`, `dom9` | `0, 4, 7, 10, 14` | Dominant 9th |
| `add9` | `0, 4, 7, 14` | Added 9th |
| `sus2` | `0, 2, 7` | Suspended 2nd |
| `sus4` | `0, 5, 7` | Suspended 4th |
| `dim` | `0, 3, 6` | Diminished Triad |
| `dim7` | `0, 3, 6, 9` | Diminished 7th |
| `aug` | `0, 4, 8` | Augmented Triad |

### 3. Scales
Pie supports a variety of common scales. You can apply them to influence how relative notes (integers) are mapped to actual frequencies.
- **Available Scales**: `maj`, `m`, `pent_maj`, `pent_m`, `chrom`.
- **Usage**: `pat.scale("Cmajor")` or `pat.scale("Cm")`
- **Dynamic Scales**: `<Cmajor Dm>` rotates the scale per cycle.

---

## Pattern Modifiers (Chaining)

When you create a pattern using `p.pattern(instrument, string)`, it returns a `Pattern` object. You can chain modifier methods to this object before adding it to the mix to radically alter how it plays.

### 1. `.scale(name)`
Sets the current musical scale for relative sequencing. Integers in your pattern string will be treated as degrees of this scale rather than raw MIDI notes.
- **Usage**: `pat.scale("Cmaj")` or `pat.scale("Cm")`
- **Dynamic Scales**: Pass a pattern string to rotate scales over time.
  ```python
  # Alternates between C Major and D Minor every cycle
  pat = p.pattern(synth, "0 2 4 6").scale("<Cmaj Dm>")
  p.add(synth, pat)
  ```

### 2. `.clip(n)`
Sets the note duration multiplier (default is typically 0.9 to leave a tiny gap between notes). A clip of `1.0` means legato (the note plays for the full duration of its step). A clip of `0.5` means staccato (half the step).
- **Usage**: `pat.clip(0.5)`
- **Dynamic Clip**: You can pass a pattern string to automate note lengths.
  ```python
  # First two notes are short (0.5), last two are long (1.0)
  p.add(synth, p.pattern(synth, "C4 E4 G4 B4").clip("0.5 0.5 1.0 1.0"))
  ```

### 3. `.transpose(n)`
Shifts all notes by `n` semitones. This works on raw MIDI numbers, note strings, and scale indices.
- **Usage**: `pat.transpose(-12)` (Drops the pattern by one octave)
- **Dynamic Transposition**:
  ```python
  # Transposes the pattern up by 7 semitones every other cycle
  p.add(synth, p.pattern(synth, "C4 E4 G4").transpose("<0 7>"))
  ```

### 4. `.strum(amount)`
Adds an incremental time delay (in seconds) between notes in a chord, simulating a strummed guitar or harp. 
- **Usage**: Positive values strum "up" (lowest to highest note). Negative values strum "down".
  ```python
  # Strums the C Major chord with a 20ms delay between each note
  p.add(synth, p.pattern(synth, "C4maj").strum(0.02))
  ```

### 5. `.slow(n)`
Stretches the pattern to last over `n` cycles instead of fitting into 1 cycle.
- **Usage**:
  ```python
  # Plays the pattern at half speed (spread over 2 cycles)
  p.add(synth, p.pattern(synth, "C4 D4 E4 F4").slow(2))
  ```

---

## Instrument Automation

### 1. Primary Parameter
Each instrument has a primary parameter that can be automated just by passing values in the basic string.

For example, `PieFilter`'s primary parameter is `cutoff`.
The following pattern will sweep the cutoff frequency between 200 and 2000 every cycle:
```python
with Pie(bpm=120) as p, PieFilter() as lpf:
    lpf.set_type("lpf")
    p.add(lpf, "[200 2000]")
```

| Class | Primary Parameter |
| :--- | :--- |
| **PieSampler** | Slot number |
| **PieWavetable** | Note value |
| **PieFilter** | Cutoff frequency |
| **PieCompressor** | Gain |
| **PieEcho** | Delay time |
| **PieMixer** | Volume |

### 2. Parameter Commands
For other parameters (and for smooth transitions), you can use the `command:value:transition` syntax.
The following pattern will sweep the cutoff frequency to 200 then to 2000 every cycle with a 500ms smooth transition:
```python
with Pie(bpm=120) as p, PieFilter() as lpf:
    lpf.set_type("lpf")
    p.add(lpf, "cutoff:200:500 cutoff:2000:500")
```

| Class | Command | Description |
| :--- | :--- | :--- |
| **PieSampler** | `vol` | Volume (0.0 to 1.0) |
| **PieWavetable** | `vol` | Volume (0.0 to 1.0) |
| | `mrp` | Wavetable morph position |
| **PieFilter** | `cutoff` | Cutoff frequency (Hz) |
| | `q` | Filter resonance |
| **PieCompressor** | `gain` | Post-compression gain |
| | `reduction` | Compression intensity |
| **PieEcho** | `time` | Delay time in ms |
| | `fb` | Feedback amount |
| **PieMixer** | `vol` | Volume (0.0 to 1.0) |
| | `pan` | Panning (-1.0 to 1.0) |

---

## Pattern Examples
Practical examples of combining patterns with the Pie API:

```python
# drums are PieSampler instances
# synth is PieWavetable instance

# 1. Simple drum sequence (assuming 0 is kick, 1 is snare)
p.add(drums, "[0 1 0 1]")

# 2. Simple drum sequence with hihat (assuming 0 is kick, 1 is snare, 2 is hihat), with volume alternation for hihat.
p.add(drums, "[0 1 0 1], [2 2 2 2], [vol2:0.8:0 vol2:0.4:0]*2")

# 3. Transposed chord (moves C3maj down an octave)
p.add(synth, p.pattern(synth, "C3maj").transpose(-12))

# 4. Chained configuration: Clipping (Note duration) + Scale
pat = p.pattern(synth, "0 2 4 6").scale("Ebmaj").clip("0.5 1.0")
p.add(synth, pat)

# 5. Multi-cycle rotation (Note alternates every cycle)
p.add(synth, "[<c4 g4> e4]")

# 6. Weighted sequence (C4m is 3x longer than G3maj) with struming
p.add(synth, p.pattern(synth, "C4m@3 G3maj@1").strum(0.02))

# 7. First inversion drop voicing
p.add(synth, "C4m:1")

# 8. Fast repetition within a step
p.add(synth, "60 67 [60 62 64 65]*2")

# 9. Voicing by inversions
p.add(synth, "<A2m C2maj:2 D2maj:1 F2maj A2m E2maj:1 A2m E27:1>")

```

---

## Automation and Effects

Pie allows you to automate any parameter of an effect or instrument using the sequence string.

### Automation Syntax: `command:value:transition_ms`

You can use a track purely for automation by adding an effect module to the `Pie` instance:

The following example will pan the mixer back and forth every cycle.
```python
with Pie(bpm=120) as p, PieMixer() as mixer:
    p.add(mixer, "pan:-1:500 pan:1:500") 
```

---

## Instrument Wrappers

Pie provides wrappers for the low-level audio classes to support pattern parsing.

### Common Methods (All Wrappers)
All instrument and effect wrappers support the following methods:

- `detach(state=True)`: Toggles the "independent processing" of the module. Setting it to `True` prevents the module from being processed in the main mix, saving CPU cycles. Use this if you have created a module but are not currently using it in a signal chain.
- `trigger(value, ...)`: Initiation method for pattern events.

### PieSampler
- `load_wav(slot, filename)`: Helper to load WAV files from SD card or internal flash. Optimized files(16bit with target sample rate) are recommended.

### PieWavetable
- Automatically handles frequency conversions for notes like `"C4"`.
- `set_table(self, slot, frames)`: Load wavetable from data array. data array is a list of frames, each frame is bytearry.
- `load_wavetable(self, slot, filename, stride=1, max_frames=256, frame_size=2048)`: Load wavetable from file for wavetable synthesis such as Serum. Internally the sample length is converted to 256 samples per framem 16bit. Optimized files are recommended.
- `morph(val)`: Can be automated via the pattern.
- `pitch_transition(transition_ms)`: Set smooth pitch transition time. 

---

### PieRouter (The Signal Chain)

`PieRouter` can be used for signal routing and to group your instruments and effects. It supports sample-accurate timing for signal chain modifications:

- `add(module, execute_at=0)`: Adds an instrument or effect to the router's processing chain at the specified tick (0 for immediate).
- `clear(execute_at=0)`: Removes all children from the router at the specified tick (0 for immediate).

```python
with PieRouter() as master, PieSampler(4) as drums, PieFilter() as lpf:
    drums.load_wav(0, "/sd/kick.wav")
    lpf.set_type("lpf")
    
    master.add(drums)
    master.add(lpf) # Drums now flow into the filter
```

---

## Effect Wrappers

### PieFilter
The `PieFilter` wrapper provides cut-off and resonance control for a State Variable Filter (SVF).

- `set_type(type_str)`: Sets the filter type (`"lpf"`, `"hpf"`, `"bpf"`, `"notch"`, `"peak"`).
- `set_params(cutoff, q=0.707, [transition_ms=0, execute_at=0])`: Standard parameter control.
- `q(val, [transition_ms=0, execute_at=0])`: Shorthand to set resonance.

### PieEcho
A stereo delay effect with ping-pong and cross-feedback support.

- `set_type(type_str)`: Sets the delay behavior (`"stereo"`, `"ping_pong"`).
- `set_params(time_ms, feedback, [transition_ms=0, execute_at=0])`: Configures the delay time and feedback amount.

### PieCompressor
A dynamic range compressor with built-in soft-clipping saturation.

- `set_params(gain, reduction, [transition_ms=0, execute_at=0])`: Standard parameter control.
- `gain(val, [transition_ms=0, execute_at=0])`: Shorthand for output gain.
- `reduction(val, [transition_ms=0, execute_at=0])`: Shorthand for compression intensity.

### PieMixer
High-performance gain and panning control.

- `set_params(volume, pan, [transition_ms=0, execute_at=0])`: Standard parameter control.
- `volume(val, [transition_ms=0, execute_at=0])`: Shorthand for volume.
- `pan(val, [transition_ms=0, execute_at=0])`: Shorthand for panning (-1.0 to 1.0).
