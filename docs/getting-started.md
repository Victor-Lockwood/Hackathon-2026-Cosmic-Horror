# :material-rocket-launch: Getting Started

## 1. Set up the environment

```bash
make setup
conda activate hackathon
```

This installs Python, all scientific deps, FluidSynth (the C library), and pyfluidsynth (Python bindings) in one shot.

## 2. Verify audio works

```bash
make music
```

This runs the `src/midi_demo.py` script, which cycles through instruments and chords to ensure FluidSynth is correctly configured and communicating with your speakers.

If you hear nothing, check that your system volume is on and the correct audio driver (WASAPI is preferred) is available in Windows Settings.

## 3. Launch the GUI

```bash
# Without hardware (mock data for development):
make gui

# With BioRadio connected:
make gui-live
```

## 4. Train the classifier

The ML pipeline lives in `src/pipeline.py`. Victor's `main()` trains on the team's 8 gesture classes from recorded EMG data:

```bash
make train
```

This produces a saved model in `models/classifier.pkl`.

## 5. Perform the Ritual

Once your classifier is trained and the GUI is streaming to LSL, start the real-time bridge:

```bash
make ritual
```

This will:

1. Initialize the MIDI engine (FluidSynth + SoundFont).
2. Load `models/classifier.pkl` (falls back to a mock classifier if not found).
3. Search for the `BioRadio` LSL stream (retries up to 8 times, 1 second each).
4. Process EMG signals in 250ms windows with 50% overlap.
5. Classify gestures and trigger the MIDI engine.

You can also start the ritual from the GUI by enabling the **Music Mode** checkbox during acquisition. The GUI shows real-time status updates as the ritual connects.

## 6. Manual Integration (Alternative)

If you're building a custom script, connect MIDI to your own classifier loop:

```python
from midi_engine import MidiController

controller = MidiController()
controller.start()

# Called every classification frame:
controller.on_classification(
    right_hand="palm_up_out",   # chord selection
    left_hand="fist_down_out",  # instrument selection
    amplitude=0.73              # EMG amplitude -> velocity
)

controller.stop()
```

!!! tip "Thread safety"

    `on_classification()` is thread-safe and never blocks. Call it from the
    classifier loop as fast as you want — the MIDI engine handles debouncing
    and audio rendering on its own background thread.
