# MIDI Engine — Biosignal-Controlled Music

**Added by:** AJ
**File:** `src/midi_engine.py`

Turns classifier output into live music. No DAW, no external synth, no extra
software — FluidSynth renders audio directly to your speakers.

## Setup

1. Update your conda environment (one-time):
   ```
   conda env update -f environment.yml
   conda activate hackathon
   ```

2. Download the SoundFont (one-time, ~30 MB):
   ```
   mkdir soundfonts
   curl -L -o soundfonts/GeneralUser_GS.sf2 "https://musical-artifacts.com/artifacts/4625/GeneralUser_GS_v1.471.sf2"
   ```

3. Verify it works:
   ```
   python src/midi_engine.py
   ```
   You should hear piano, guitar, and string chords from your speakers.

## How to Use in the Pipeline

```python
from midi_engine import MidiController

controller = MidiController()
controller.start()

# Called every classification frame from the real-time loop:
controller.on_classification(
    right_hand="palm_up_out",   # chord selection
    left_hand="fist_down_out",  # instrument selection
    amplitude=0.73              # EMG amplitude -> volume (0.0 to 1.0)
)

controller.stop()
```

`on_classification()` is thread-safe and never blocks. Call it from the
classifier loop as fast as you want — the engine handles debouncing internally.

## Gesture Mappings

### Right Hand (chord)

| Gesture | Chord |
|---------|-------|
| `palm_up_out` | C major |
| `palm_down_out` | A minor |
| `palm_down_up` | E minor |
| `fist_down_out` | G major |
| `fist_down_up` | D minor |
| `peace_out` | F major |
| `arm_up` | D major |
| `arm_down` | **Rest** (silence) |

### Left Hand (instrument)

| Gesture | Instrument |
|---------|-----------|
| `fist_down_out` | Piano |
| `palm_up_out` | Nylon Guitar |
| `palm_down_out` | Steel Guitar |
| `palm_down_up` | Electric Guitar |
| `fist_down_up` | Strings |
| `peace_out` | Pad (Warm) |

## Chord Progression Mode

Lock to a song so gestures just advance through the chords in order:

```python
controller.set_progression("save_your_tears")   # C -> Am -> Em -> G
controller.set_progression("blinding_lights")    # Dm -> G -> C -> Am
controller.set_progression("love_story")         # G -> D -> Em -> C
controller.set_progression("careless_whisper")   # Dm -> G -> Am -> Am

controller.clear_progression()  # back to free-play
```

## Other Useful Methods

```python
controller.set_instrument("piano")       # switch instrument directly
controller.play_chord("Am", velocity=90, duration=1.0)  # play a chord manually
controller.panic()                        # all notes off (emergency stop)
controller.get_state()                    # returns dict with current chord, instrument, etc.
```

## Tuning

| Parameter | Default | What it does |
|-----------|---------|-------------|
| `strum_delay_ms` | 15 | Delay between notes in a chord (guitar strum effect). Set to 0 for block chords. |
| `debounce_frames` | 3 | How many consecutive same-gesture frames before triggering a chord change. Increase if the classifier is noisy. |
| `gain` | 0.8 | Master volume (0.0 to 1.0+). |

```python
controller = MidiController(strum_delay_ms=25, debounce_frames=5, gain=1.0)
```
