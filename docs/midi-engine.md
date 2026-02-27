# :material-piano: MIDI Engine

## How it works

The MIDI engine uses **pyFluidSynth** to render audio directly to your speakers.
No DAW, no external synth, no virtual MIDI routing. One process, one SoundFont
file, sound comes out.

```
Classifier output ──► MidiController ──► FluidSynth ──► Speakers
                      (thread-safe)     (multiple drivers)
```

The engine is highly portable on Windows, automatically attempting to initialize
using **WASAPI** (preferred for low latency), **DirectSound**, or **WaveOut**.

---

## Quick start

```python
from midi_engine import MidiController

controller = MidiController()
controller.start()

# From the classifier loop:
controller.on_classification(
    right_hand="palm_up_out",   # chord
    left_hand="fist_down_out",  # instrument
    amplitude=0.73              # EMG amplitude -> volume
)

controller.stop()
```

---

## Chords

All 7 chords use full guitar-style voicings (not just triads):

| Chord | MIDI Notes | Pitches |
|-------|-----------|---------|
| **C** | 48, 52, 55, 60, 64, 67 | C3 E3 G3 C4 E4 G4 |
| **Am** | 45, 52, 57, 60, 64 | A2 E3 A3 C4 E4 |
| **Em** | 40, 47, 52, 55, 59, 64 | E2 B2 E3 G3 B3 E4 |
| **G** | 43, 47, 50, 55, 59, 67 | G2 B2 D3 G3 B3 G4 |
| **Dm** | 38, 50, 53, 57, 62 | D2 D3 F3 A3 D4 |
| **F** | 41, 48, 53, 57, 60, 65 | F2 C3 F3 A3 C4 F4 |
| **D** | 38, 45, 50, 54, 57, 62 | D2 A2 D3 F#3 A3 D4 |

---

## Instruments

| Name | GM Program | Gesture |
|------|-----------|---------|
| Piano | 0 | `fist_down_out` |
| Nylon Guitar | 24 | `palm_up_out` |
| Steel Guitar | 25 | `palm_down_out` |
| Electric Guitar | 27 | `palm_down_up` |
| Strings | 48 | `fist_down_up` |
| Pad (Warm) | 88 | `peace_out` |

---

## Chord progression mode

Lock to a song so gestures advance through the chord sequence:

```python
controller.set_progression("save_your_tears")              # full song
controller.set_progression("careless_whisper", section="verse")  # just verse
controller.clear_progression()                               # free-play
```

See the [Playlist](playlist.md) page for all available songs.

---

## Tuning parameters

| Parameter | Default | Effect |
|-----------|---------|--------|
| `strum_delay_ms` | 15 | Delay between notes in a chord (guitar strum effect). Set to 0 for block chords. |
| `debounce_frames` | 3 | Consecutive same-gesture frames required before triggering. Increase if classifier is noisy. |
| `gain` | 0.8 | Master volume (0.0 to 1.0+). |

!!! note "Velocity Mapping"
    EMG amplitude (0.0 to 1.0) is linearly mapped to MIDI velocity values between **40 and 127**. This ensures even soft gestures produce audible sound while allowing for dynamic expression.

    Velocity updates **dynamically during sustain** — if you squeeze harder while holding a chord, the notes are re-voiced at the new velocity in real time.

```python
controller = MidiController(strum_delay_ms=25, debounce_frames=5, gain=1.0)
```

---

## Other useful methods

| Method | Description |
|--------|------------|
| `set_instrument("piano")` | Switch instrument directly |
| `play_chord("Am", velocity=90, duration=1.0)` | Play a chord (blocks the calling thread) |
| `play_chord("Am", blocking=False)` | Play a chord without blocking (notes auto-stop after duration) |
| `play_note(60, velocity=100, duration=0.5)` | Play a single MIDI note |
| `play_note(60, blocking=False)` | Play a note without blocking |
| `panic()` | All notes off (emergency stop) |
| `get_state()` | Returns dict with current chord, instrument, progression position |
