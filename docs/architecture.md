# :material-sitemap: Architecture

## System overview

```mermaid
flowchart TD
    subgraph capture ["Signal Capture"]
        BR["BioRadio<br/>EMG Sensors"]
        GUI["Hackathon GUI<br/>hackathon_gui.py"]
    end

    subgraph ml ["ML Pipeline"]
        SP["Signal Processing<br/>signal_processing.py"]
        PP["Feature Extraction<br/>pipeline.py"]
        RF["RandomForest<br/>Classifier"]
    end

    subgraph audio ["Audio Output"]
        MC["MidiController<br/>midi_engine.py"]
        FS["FluidSynth + SoundFont"]
        SPK["Speakers"]
    end

    BR -->|raw EMG| GUI
    GUI -->|channels| SP
    SP -->|filtered| PP
    PP -->|features| RF
    RF -->|gesture + amplitude| MC
    MC -->|MIDI messages| FS
    FS -->|audio| SPK
```

---

## Signal flow

| Stage | File | What it does |
|-------|------|-------------|
| **Capture** | `hackathon_gui.py` | Streams raw EMG from BioRadio (or mock data) |
| **Preprocessing** | `pipeline.py` | Bandpass filter (20-450 Hz) + 60 Hz notch filter |
| **Feature extraction** | `pipeline.py` | Sliding window: RMS, MAV, Variance, Waveform Length, Zero Crossings |
| **Classification** | `pipeline.py` | RandomForestClassifier trained on 8 gesture classes |
| **Music synthesis** | `midi_engine.py` | Maps gestures to chords/instruments, renders audio via FluidSynth |

---

## Gesture mapping

### Right hand — chord selection

```mermaid
flowchart LR
    PUO["palm_up_out"] --> C["C major"]
    PDO["palm_down_out"] --> Am["A minor"]
    PDU["palm_down_up"] --> Em["E minor"]
    FDO["fist_down_out"] --> G["G major"]
    FDU["fist_down_up"] --> Dm["D minor"]
    PO["peace_out"] --> F["F major"]
    AU["arm_up"] --> D["D major"]
    AD["arm_down"] --> REST["Rest / Silence"]
```

### Left hand — instrument selection

| Gesture | Instrument |
|---------|-----------|
| `fist_down_out` | Piano |
| `palm_up_out` | Nylon Guitar |
| `palm_down_out` | Steel Guitar |
| `palm_down_up` | Electric Guitar |
| `fist_down_up` | Strings |
| `peace_out` | Pad (Warm) |
| `arm_up` | Nylon Guitar |
| `arm_down` | Nylon Guitar |

---

## MIDI engine internals

```mermaid
stateDiagram-v2
    state "Idle State" as IDLE
    state "Playing Note" as PLAYING
    state "Sustain Mode" as SUSTAIN

    [*] --> IDLE
    IDLE --> PLAYING : New gesture
    PLAYING --> SUSTAIN : Hold gesture
    SUSTAIN --> PLAYING : Change gesture
    PLAYING --> IDLE : arm_down
    SUSTAIN --> IDLE : arm_down
```

The state machine debounces noisy classifier output (default: 3 consecutive frames) and handles chord transitions (note-off before note-on). EMG amplitude maps to MIDI velocity (louder flex = louder note).

---

## Key files

| File | Purpose |
|------|---------|
| `src/midi_engine.py` | MIDI engine: state machine, controller, playlist loader |
| `src/pipeline.py` | ML pipeline: preprocessing, features, classifier |
| `src/hackathon_gui.py` | GUI for BioRadio streaming and data collection |
| `src/signal_processing.py` | Signal processing utilities |
| `playlist/*.json` | Song chord progressions |
| `soundfonts/GeneralUser_GS.sf2` | SoundFont for FluidSynth (~30 MB) |
