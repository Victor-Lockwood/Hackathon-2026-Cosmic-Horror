# :material-sitemap: Architecture

## System overview

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
    'primaryColor': '#1a1a2e',
    'primaryTextColor': '#e0e0ff',
    'primaryBorderColor': '#9d27b0',
    'lineColor': '#00ffa2',
    'secondaryColor': '#0f0f1a',
    'tertiaryColor': '#12121f',
    'edgeLabelBackground': '#0a0a15',
    'clusterBkg': '#0f0f1a',
    'clusterBorder': '#9d27b0',
    'titleColor': '#e0e0ff',
    'nodeTextColor': '#e0e0ff'
}, 'flowchart': {'nodeSpacing': 30, 'rankSpacing': 40}}}%%
flowchart TD
    subgraph capture ["Signal Capture"]
        BR["BioRadio<br/>EMG Sensors"]
        GUI["Hackathon GUI<br/>hackathon_gui.py"]
    end

    subgraph bridge ["Real-time Bridge · cosmic_ritual.py"]
        CR["LSL Consumer<br/>250ms windows"]
        SP["Bandpass + Notch<br/>signal_processing.py"]
        PP["Feature Extraction<br/>pipeline.py"]
        RF["RandomForest<br/>Classifier"]
    end

    subgraph audio ["Audio Output"]
        MC["MidiController<br/>midi_engine.py"]
        FS["FluidSynth + SoundFont"]
        SPK["Speakers"]
    end

    BR -->|"raw EMG"| GUI
    GUI -->|"LSL stream + status callbacks"| CR
    CR -->|"raw window"| SP
    SP -->|"filtered"| PP
    PP -->|"features"| RF
    RF -->|"gesture + amplitude"| MC
    MC -->|"MIDI messages"| FS
    FS -->|"audio"| SPK

    style BR fill:#1a1a2e,stroke:#9d27b0,stroke-width:2px,color:#e0e0ff
    style GUI fill:#1a1a2e,stroke:#9d27b0,stroke-width:2px,color:#e0e0ff
    style CR fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style SP fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style PP fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style RF fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style MC fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style FS fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style SPK fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
```

---

## Signal flow

| Stage | File | What it does |
|-------|------|-------------|
| **Capture** | <nobr>`hackathon_gui.py`</nobr> | Streams raw EMG from BioRadio (serial), LSL, or mock source; records CSVs; hosts Music Mode toggle |
| **Real-time Bridge** | <nobr>`cosmic_ritual.py`</nobr> | Consumes LSL stream, windows data (250ms, 50% overlap), classifies gestures, and feeds the MIDI engine. Reports status back to the GUI via callbacks. Falls back to `SimpleFeatureClassifier` if the ML pipeline is unavailable. |
| **Preprocessing** | <nobr>`signal_processing.py`</nobr> | Bandpass filter (20-450 Hz) + 60 Hz notch filter |
| **Feature extraction** | <nobr>`pipeline.py`</nobr> | Sliding window: RMS, MAV, Variance, Waveform Length, Zero Crossings |
| **Classification** | <nobr>`pipeline.py`</nobr> | RandomForestClassifier trained on 8 gesture classes |
| **Music synthesis** | <nobr>`midi_engine.py`</nobr> | Maps gestures to chords/instruments; renders audio via FluidSynth (WASAPI/DirectSound/WaveOut) |

---

## Gesture mapping

### Right hand — chord selection

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {
    'primaryColor': '#1a1a2e',
    'primaryTextColor': '#e0e0ff',
    'primaryBorderColor': '#00ffa2',
    'lineColor': '#00ffa2',
    'edgeLabelBackground': '#0a0a15',
    'nodeTextColor': '#e0e0ff'
}}}%%
flowchart LR
    PUO["palm_up_out"] --> C["C major"]
    PDO["palm_down_out"] --> Am["A minor"]
    PDU["palm_down_up"] --> Em["E minor"]
    FDO["fist_down_out"] --> G["G major"]
    FDU["fist_down_up"] --> Dm["D minor"]
    PO["peace_out"] --> F["F major"]
    AU["arm_up"] --> D["D major"]
    AD["arm_down"] --> REST["Rest / Silence"]

    style PUO fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style PDO fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style PDU fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style FDO fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style FDU fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style PO fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style AU fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style AD fill:#1a1a2e,stroke:#9d27b0,stroke-width:2px,color:#b0b0d0
    style C fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style Am fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style Em fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style G fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style Dm fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style F fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style D fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
    style REST fill:#0a0a15,stroke:#9d27b0,stroke-width:2px,stroke-dasharray:5 5,color:#b0b0d0
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
%%{init: {'theme': 'base', 'themeVariables': {
    'primaryColor': '#1a1a2e',
    'primaryTextColor': '#e0e0ff',
    'primaryBorderColor': '#00ffa2',
    'lineColor': '#00ffa2',
    'secondaryColor': '#0f0f1a',
    'tertiaryColor': '#12121f',
    'nodeTextColor': '#e0e0ff'
}}}%%
flowchart TD
    START(( )) --> IDLE

    IDLE["Idle State"]
    PLAYING["Playing Note"]
    SUSTAIN["Sustain Mode"]

    IDLE -->|"New gesture"| PLAYING
    PLAYING -->|"Hold gesture"| SUSTAIN
    SUSTAIN -->|"Change gesture"| PLAYING
    PLAYING -->|"arm_down"| IDLE
    SUSTAIN -->|"arm_down"| IDLE

    style START fill:#00ffa2,stroke:#00ffa2,color:#00ffa2
    style IDLE fill:#1a1a2e,stroke:#9d27b0,stroke-width:2px,color:#e0e0ff
    style PLAYING fill:#1a1a2e,stroke:#00ffa2,stroke-width:2px,color:#e0e0ff
    style SUSTAIN fill:#1a1a2e,stroke:#d05ce3,stroke-width:2px,color:#e0e0ff
```

The state machine debounces noisy classifier output (default: 3 consecutive frames) and handles chord transitions by triggering note-off before note-on. EMG amplitude maps to MIDI velocity (linear mapping from 0.0–1.0 to MIDI values 40–127).

During **sustain**, velocity updates dynamically — if the performer squeezes harder mid-chord, the held notes are re-voiced at the new velocity for real-time expression.

The engine automatically attempts to use the **WASAPI** driver for low latency on Windows, falling back to DirectSound or WaveOut if necessary.

---

## Key files

| File | Purpose |
|------|---------|
| <nobr>`src/midi_engine.py`</nobr> | MIDI engine: state machine, controller, playlist loader |
| <nobr>`src/cosmic_ritual.py`</nobr> | Real-time bridge: LSL stream to classifier to MIDI, with GUI status callbacks |
| <nobr>`src/midi_demo.py`</nobr> | Standalone demo: cycles instruments, chords, songs, and simulated classifier input |
| <nobr>`src/pipeline.py`</nobr> | ML pipeline: preprocessing, features, classifier |
| <nobr>`src/hackathon_gui.py`</nobr> | GUI: BioRadio/LSL/mock streaming, data recording, Music Mode toggle |
| <nobr>`src/signal_processing.py`</nobr> | Signal processing utilities (bandpass, notch filters) |
| <nobr>`playlist/*.json`</nobr> | Song chord progressions (6 songs) |
| <nobr>`soundfonts/GeneralUser_GS.sf2`</nobr> | SoundFont for FluidSynth (~30 MB, gitignored) |
