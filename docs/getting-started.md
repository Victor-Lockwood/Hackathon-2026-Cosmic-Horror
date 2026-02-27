# :material-rocket-launch: Getting Started

## 1. Set up the environment

```bash
conda env create -f environment.yml
conda activate hackathon
```

This installs Python, all scientific deps, FluidSynth (the C library), and pyfluidsynth (Python bindings) in one shot.

## 2. Verify audio works

```bash
make music
```

Or equivalently:

```bash
python src/midi_engine.py
```

You should hear piano, guitar, and string chords from your speakers. If you hear nothing, check that your system volume is on and the correct output device is selected in Windows Settings.

## 3. Launch the GUI

```bash
# With BioRadio connected:
python -m src.hackathon_gui

# Without hardware (mock data for development):
python -m src.hackathon_gui --mock
```

## 4. Train the classifier

The ML pipeline lives in `src/pipeline.py`. Victor's `main()` trains on the team's 8 gesture classes from recorded EMG data:

```bash
cd src && python pipeline.py
```

This produces a saved model in `models/classifier.pkl`.

## 5. Connect MIDI to the classifier

```python
from midi_engine import MidiController

controller = MidiController()
controller.start()

# In your real-time classification loop:
controller.on_classification(
    right_hand="palm_up_out",   # chord
    left_hand="fist_down_out",  # instrument
    amplitude=0.73              # EMG amplitude -> volume
)

controller.stop()
```

!!! tip "Thread safety"

    `on_classification()` is thread-safe and never blocks. Call it from the
    classifier loop as fast as you want — the MIDI engine handles debouncing
    and audio rendering on its own background thread.
