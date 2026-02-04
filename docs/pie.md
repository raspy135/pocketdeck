# Pie audio sequencer

The `Pie` framework is a high-level, mini-notation based sequencer designed for the Pocket deck audio engine, and the syntax is inspired by TidalCycles and Strudel. It allows you to compose complex rhythms, melodies, and effects chains using simple strings.

## The Pie Class

The `Pie` class is the central heart of the sequencer. It manages timing (BPM), schedules events, and coordinates playback between instruments and effects.

### Basic Usage

```python
from pie import Pie, PieSampler
import time

def main(vs, args):
    with Pie(bpm=120) as p, PieSampler(4) as drums:
        drums.load_wav(0, "/sd/kick.wav")
        
        p.add(drums, "0 . . . 0 . . .") # Simple kick pattern
        
        while True:
            # process_event must be called in your main loop periodically
            p.process_event()
            time.sleep(0.1)
            # Your main loop logic here
```

### Methods

- `__init__(bpm=120, startup_delay_ms=100)`
- `add(instrument, pattern)`
  Adds an instrument and a pattern string to the mix. Returns an index for later updates.
- `update(index, pattern)`
  Hot-swaps a pattern string for an existing track.
- `remove(index)`
  Removes a track from the sequencer.
- `process_event()`
  **Must be called in your main loop.** This processes timing and dispatches events to the audio engine.
- `process_interactive(filename, loc)`: Standard interactive mode entry point.
- `get_tick_from_cycle(cycle)`: Calculates the specific audio tick (sample count) for a given cycle. Useful for scheduling timed events with `master.add(module, tick)`.
- `start() / stop()`
  Manual control over the sequencer clock.

---

## Interactive Mode (Live Coding)

Pie supports a powerful interactive mode that allows you to change patterns and parameters in real-time without restarting your script.

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

### 5. Primary parameter

Each instrument has a primary parameter that can be automated.

For example, `PieFilter`'s primary parameter is `cutoff`.
The following pattern will sweep the cutoff frequency changes 200 then 2000 every cycle.

```python
with Pie(bpm=120) as p, PieFilter() as lpf:
    lpf.set_type("lpf")
    p.add(lpf, "[200 2000]")
```

For other parameters and for smooth transitions, you can use the `command:value:transition` syntax.
The following pattern will sweep the cutoff frequency changes 200 then 2000 every cycle with a 500ms transition.
```python
with Pie(bpm=120) as p, PieFilter() as lpf:
    lpf.set_type("lpf")
    p.add(lpf, "cutoff:200:500 cutoff:2000:500")
```

| Class | Primary Parameter |
| :--- | :--- |
| **PieSampler** | Slot number |
| **PieWavetable** | Note value |
| **PieFilter** | Cutoff frequency |
| **PieCompressor** | Gain |
| **PieEcho** | Delay time |
| **PieMixer** | Volume |

The above primary parameters are what get passed to the `trigger()` method when a note or value is encountered in a pattern.

### 6. Pitch and Notes
They are only available for `PieWavetable`.
- **MIDI Numbers**: Integers (e.g., `60`).
- **Note Strings**: Standard notation (e.g., `C4`, `F#3`).
- **Chords**: Parsed into simultaneous notes (e.g., `Cmaj`).

### 7. Instrument Automation
Each instrument supports specific commands that can be used in the `command:value:transition` syntax.

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
- `load_wav(slot, filename)`: Helper to load WAV files from SD card or internal flash.

### PieWavetable
- Automatically handles frequency conversions for notes like `"C4"`.
- `morph(val)`: Can be automated via the pattern.

---

### PieRouter (The Signal Chain)

`PieRouter` can be used for signal routing and to group your instruments and effects. It supports sample-accurate timing for signal chain modifications:

- `add(module, execute_at=0)`: Adds an instrument or effect to the router's processing chain at the specified tick (0 for immediate).
- `clear(execute_at=0)`: Removes all children from the router at the specified tick (0 for immediate).
- `clear_events()`: Cancels any pending timed `add` or `clear` operations.

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
