
## Audio module reference

The `audio` module provides low-level control over sound synthesis, playback, and streaming. It includes two specialized classes: `sampler` for sample-based playback and `wavetable` for wavetable-based synthesis. It also has a `router` class for signal routing and an `effect` class for audio effects. Effects include `echo`, `filter`, `compressor`, `mixer`, and `delay`.

Audio module supports 16-bit PCM audio data. Default sample rate is 24kHz. You can change the sample rate by `sample_rate(rate)` function.

### Module Level Functions

- `power(state)`
  Sets or gets the power state of the audio system. `state` is a boolean. If no argument is provided, returns the current state.

- `sample_rate(rate)`
  Sets or gets the global sample rate (e.g., 44100). If no argument is provided, returns the current rate.

- `get_current_tick()`
  Returns the current internal I2S tick count (sample count). This is useful for synchronizing events with sample-perfect timing.

- `stream_setup(mod_index, sample_rate, channel, length, [callback])`
  Sets up an audio stream. 
  - `mod_index`: 0 for playback (TX), 1 for recording (RX).
  - `sample_rate`: Sampling frequency.
  - `channel`: Number of channels.
  - `length`: Buffer length.
  - `callback`: A callback function called when a buffer is ready.

- `stream_setdata(mod_index, index, buffer)`
  Sets data for a specific buffer index in the stream.

- `stream_play(state)`
  Starts or stops playback. If no argument is provided, returns the playing status.

- `stream_record(state)`
  Starts or stops recording. If no argument is provided, returns the recording status.

- `stream_position(mod_index)`
  Returns the current position in the stream for the specified module.

### Timing and Scheduling (execute_at)

Many methods in `sampler` and `wavetable` accept an optional `execute_at` parameter. This allows for sample-perfect scheduling of events.
- **Integer**: The exact tick (sample count) at which to execute.
- **String**: 
  - `"+1s"`: Execute in 1 second from now.
  - `"+500ms"`: Execute in 500 milliseconds from now.
  - `"+100"`: Execute in 100 samples from now.

---

### sampler class

The `sampler` class is used for playing back pre-recorded PCM samples.

#### Constructor

```python
s = audio.sampler(max_samples)
```
Creates a sampler instance with `max_samples` slots. It is recommended to use it as a context manager to ensure proper resource cleanup.

```python
with audio.sampler(8) as s:
    # use sampler
```

#### Methods

**The optional parameters are not kwargs, they are positional arguments.**

- `set_sample(slot, data, [channels=1])`
  Assigns raw PCM data (int16) to a sample slot. The sampler automatically determines the length from the buffer size. Data should be kept by variable to avoid GC collection.
```python
import wav_loader

data = None
with open("/sd/data/sample.wav", 'rb') as f:
  loader.open(f)
  if channels is None:
    channels = loader.channels
  data = loader.load_all(f, target_rate=sample_rate, target_channels=channels)
# keep data to avoid gc collection
```

- `play(slot, [loop=False, execute_at=0])`
  Starts playback of the sample in the specified slot.

- `stop(slot, [fadeout_ms=0, execute_at=0])`
  Stops playback.

- `volume(slot, [volume, transition_ms=0, execute_at=0])`
  Sets or gets the playback volume (0.0 to 1.0).

- `speed(slot, [speed, transition_ms=0, execute_at=0])`
  Sets or gets the playback speed (1.0 is normal).

- `is_playing(slot)`
  Returns `True` if the specified slot is currently playing.

- `get_position(slot)`
  Returns current playback position in samples.

- `stop_all()`
  Stops all playing samples in this sampler instance.

---

### wavetable class

The `wavetable` class provides flexible wavetable synthesis with morphing and ADSR envelopes.

#### Constructor

```python
w = audio.wavetable(max_oscillators)
```
Creates a wavetable instance with `max_oscillators`. Supports context manager usage.

Use context manager to ensure proper resource cleanup.

```python
with audio.wavetable(4) as w:
    # use wavetable
```

#### Methods

- `set_wavetable(slot, frames)`
  Sets the wavetable data for an oscillator. `frames` is a list of buffers (frames), each of the same size. 
  Unlike Sampler, you don't need to keep `frames` to avoid GC collection.   

- `note_on(slot, [execute_at=0])`
  Triggers the ADSR envelope (Attack phase).

- `note_off(slot, [execute_at=0])`
  Triggers the Release phase of the ADSR envelope.

- `stop(slot, [execute_at=0])`
  Immediately stops the oscillator.

- `frequency(slot, frequency, [execute_at=0])`
  Sets the fundamental frequency of the oscillator.

- `pitch(slot, [pitch, transition_ms=0, execute_at=0])`
  Sets or gets the pitch multiplier (1.0 is original).

- `volume(slot, [volume, transition_ms=0, execute_at=0])`
  Sets or gets the oscillator volume.

- `morph(slot, [morph, transition_ms=0, execute_at=0])`
  Sets or gets the morph position (0.0 to number of frames - 1.0) to interpolate between wavetable frames.

- `set_adsr(slot, attack_ms, decay_ms, sustain_level, release_ms, [execute_at=0])`
  Configures the ADSR envelope for the oscillator.

- `is_playing(slot)`
  Returns `True` if the oscillator is active.

- `get_position(slot)`
  Returns current phase position of the oscillator.

- `stop_all()`
  Stops all oscillators in this wavetable instance.

- `copy_table(dest_slot, src_slot)`
  Copies wavetable data from one oscillator to another for efficient memory usage.

---

### router class

The `router` class manages hierarchical audio processing, allowing you to group modules and apply effects to whole chains.

#### Methods

- `add(module)`
  Adds an audio module (sampler, wavetable, or another router/effect) to this router. Modules are processed in the order they are added.

---

### mixer class

Provides high-performance volume and panning control.

#### Methods

- `set_params(volume, pan, [transition_ms=0, execute_at=0])`
  - `volume`: 0.0 to 1.0.
  - `pan`: -1.0 (Left) to 1.0 (Right).

---

### echo class

A stereo delay/echo effect with optional ping-pong mode and analog-style feedback filtering.

#### Methods

- `set_params(time_ms, feedback, [transition_ms=0, execute_at=0])`
- `set_type(type)`
  - `"stereo"`: Standard stereo delay.
  - `"ping-pong"`: Cross-feedback delay with a 1.5x time offset on the right channel for extreme stereo width.

---

### filter class

State Variable Filter (SVF) with smooth sweeps and high stability.

#### Methods

- `set_params(cutoff, q, [transition_ms=0, execute_at=0])`
- `set_type(type)`
  - `"lpf"`, `"hpf"`, `"bpf"`, `"notch"`, `"peak"`

---

### compressor class

Dynamic range compressor with warm soft-saturation (clipping).

#### Methods

- `set_params(gain, reduction, [transition_ms=0, execute_at=0])`
  - `reduction`: 0.0 (no compression) to 1.0+ (heavy reduction).
