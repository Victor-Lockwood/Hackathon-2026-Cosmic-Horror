"""
app.py — Cosmic Horror prototype
Run: streamlit run app.py  (inside hackathon_v2 conda env)
"""

import sys
import time
import json
from pathlib import Path

import numpy as np
import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).parent
SRC_DIR      = ROOT / "src"
PLAYLIST_DIR = ROOT / "playlist"
MODEL_PATH   = ROOT / "models" / "classifier.pkl"
sys.path.insert(0, str(SRC_DIR))

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Cosmic Horror", page_icon="🎵", layout="centered")

st.markdown("""
<style>
  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding-top: 2.5rem; max-width: 780px; }

  .pill {
    display: inline-block;
    padding: .2rem .65rem;
    border-radius: 999px;
    font-weight: 700;
    font-size: .95rem;
    color: #fff;
    margin: .15rem .1rem;
  }
  .chord-card {
    border-radius: 12px;
    padding: 1rem .7rem;
    text-align: center;
    border-width: 2px;
    border-style: solid;
    margin-bottom: .4rem;
  }
  .card {
    background: rgba(255,255,255,.04);
    border: 1px solid rgba(255,255,255,.10);
    border-radius: 12px;
    padding: 1rem 1.1rem;
  }
  .card-on {
    border-color: #a78bfa !important;
    background: rgba(167,139,250,.10) !important;
  }
  .stepbar { font-size: .82rem; color: rgba(255,255,255,.4); margin-bottom: 1.6rem; }
  .s-done  { color: #4ade80; }
  .s-now   { color: #a78bfa; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# ── Constants (mirrored from midi_engine.py) ──────────────────────────────────
GESTURE_TO_CHORD = {
    "palm_up_out":   "C",
    "palm_down_out": "Am",
    "palm_down_up":  "Em",
    "fist_down_out": "G",
    "fist_down_up":  "Dm",
    "peace_out":     "F",
    "arm_up":        "D",
    "arm_down":      None,   # rest / silence
}
CHORD_TO_GESTURE = {c: g for g, c in GESTURE_TO_CHORD.items() if c}

GESTURE_TO_INSTRUMENT = {
    "palm_up_out":   ("Nylon Guitar",    "🎸"),
    "palm_down_out": ("Steel Guitar",    "🪕"),
    "palm_down_up":  ("Electric Guitar", "⚡"),
    "fist_down_out": ("Piano",           "🎹"),
    "fist_down_up":  ("Strings",         "🎻"),
    "peace_out":     ("Pad",             "🎛️"),
    "arm_up":        ("Nylon Guitar",    "🎸"),
}

CHORD_COLORS = {
    "C": "#4ade80", "Am": "#c084fc", "Em": "#60a5fa",
    "G": "#fb923c", "Dm": "#f87171", "F": "#22d3ee", "D": "#fb7185",
}

GESTURE_LABEL = {
    "palm_up_out":   "Palm Up Out",
    "palm_down_out": "Palm Down Out",
    "palm_down_up":  "Palm Down Up",
    "fist_down_out": "Fist Down Out",
    "fist_down_up":  "Fist Down Up",
    "peace_out":     "Peace Out",
    "arm_up":        "Arm Up",
    "arm_down":      "Arm Down (rest)",
}

CALIB_STEPS = [
    "Measuring baseline noise floor",
    "Recording resting muscle activity",
    "Computing signal thresholds",
    "Detecting active EMG channels",
    "Finalizing calibration",
]

# Amplitude + frequency profile per gesture for fake EMG generation.
# Frequencies kept in 20-110 Hz range so they survive the bandpass filter.
EMG_PROFILES = {
    "arm_down":      (50,    [5,  15]),
    "arm_up":        (800,   [20, 50, 80]),
    "fist_down_out": (2000,  [40, 70, 100]),
    "fist_down_up":  (2500,  [50, 80, 110]),
    "palm_down_out": (1000,  [30, 60,  90]),
    "palm_down_up":  (1200,  [35, 65,  95]),
    "palm_up_out":   (1100,  [30, 60,  90]),
    "peace_out":     (1500,  [40, 75, 105]),
}

# ── Singletons ────────────────────────────────────────────────────────────────
@st.cache_resource
def _get_midi():
    try:
        from midi_engine import MidiController
        ctrl = MidiController()
        ctrl.start()
        return ctrl, None
    except Exception as e:
        return None, str(e)


@st.cache_resource
def _get_classifier():
    """Load the trained gesture classifier once per process."""
    if not MODEL_PATH.exists():
        return None, f"Model not found at {MODEL_PATH}. Run `make train` first."
    try:
        import pipeline
        clf = pipeline.load_classifier(str(MODEL_PATH))
        return clf, None
    except Exception as e:
        return None, str(e)


# ── EMG simulation helpers ────────────────────────────────────────────────────
def generate_fake_emg(gesture: str, n: int = 125) -> "pd.DataFrame":
    """
    Synthetic 2-channel EMG window (0.5 s at 250 Hz).
    Mirrors the format realtime_process.py receives from the LSL inlet:
    columns = [timestamp, GSR, Ch2]
    """
    import pandas as pd

    fs  = 250.0
    t   = np.linspace(0, n / fs, n)
    amp, freqs = EMG_PROFILES.get(gesture, (500, [50, 100]))

    ch1 = np.zeros(n)
    ch2 = np.zeros(n)
    for f in freqs:
        ch1 += np.sin(2 * np.pi * f * t + np.random.uniform(0, 2 * np.pi))
        ch2 += np.sin(2 * np.pi * f * t + np.random.uniform(0, 2 * np.pi)) * 0.7

    ch1 = ch1 * amp / len(freqs) + np.random.normal(0, amp * 0.15, n)
    ch2 = ch2 * amp / len(freqs) + np.random.normal(0, amp * 0.10, n)

    return pd.DataFrame({
        "timestamp": np.arange(n) / fs,
        "GSR":       ch1,
        "Ch2":       ch2,
    })


def classify_window(window_df, clf) -> str:
    """
    Exact same pipeline as realtime_process.py:
      preprocess_emg_df → create_feature_df → run_classifier
    Returns the predicted gesture label string.
    """
    import pipeline
    preprocessed = pipeline.preprocess_emg_df(window_df, 250, True)
    features     = pipeline.create_feature_df(preprocessed, 250, 250, 0.5)
    prediction   = pipeline.run_classifier(features, None, "", False, clf)
    if prediction is not None and len(prediction) > 0:
        return str(prediction[0])
    return "arm_down"


# ── General helpers ───────────────────────────────────────────────────────────
def load_songs():
    songs = {}
    if PLAYLIST_DIR.exists():
        for p in sorted(PLAYLIST_DIR.glob("*.json")):
            with open(p) as f:
                songs[p.stem] = json.load(f)
    return songs


def init_state():
    defaults = {
        "stage":            "landing",
        "det_gesture":      None,
        "lock_gesture":     None,
        "lock_inst":        None,
        "song_key":         None,
        "active_chord":     None,
        "simulating":       False,
        "sim_gesture":      "palm_up_out",
        "last_prediction":  None,
        "songs":            load_songs(),
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset():
    for k in ["stage", "det_gesture", "lock_gesture", "lock_inst",
              "song_key", "active_chord", "simulating", "last_prediction"]:
        st.session_state.pop(k, None)


def pill(chord):
    c = CHORD_COLORS.get(chord, "#888")
    return f'<span class="pill" style="background:{c};">{chord}</span>'


def step_bar(current):
    order  = ["landing", "instrument", "song", "perform"]
    labels = ["Calibrate", "Instrument", "Song", "Perform"]
    idx    = order.index(current) if current in order else 0
    parts  = []
    for i, lbl in enumerate(labels):
        if i < idx:
            parts.append(f'<span class="s-done">✓ {lbl}</span>')
        elif i == idx:
            parts.append(f'<span class="s-now">● {lbl}</span>')
        else:
            parts.append(f'<span>{lbl}</span>')
        if i < len(labels) - 1:
            parts.append("›")
    st.markdown(f'<div class="stepbar">{" ".join(parts)}</div>',
                unsafe_allow_html=True)


def play(gesture, locked_gesture, amplitude=0.82):
    ctrl, _ = _get_midi()
    if ctrl:
        ctrl.on_classification(
            right_hand=gesture,
            left_hand=locked_gesture,
            amplitude=amplitude,
        )


def stop_audio():
    ctrl, _ = _get_midi()
    if ctrl:
        ctrl.panic()


# ── Page: Landing ──────────────────────────────────────────────────────────────
def page_landing():
    st.title("🎵 Cosmic Horror")
    st.caption("EMG-controlled music — your arm gestures play real chords in real time")
    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown("**1 · Calibrate**\nRecord your resting baseline")
    c2.markdown("**2 · Instrument**\nHold a gesture → lock your sound")
    c3.markdown("**3 · Song**\nPick what to play")
    c4.markdown("**4 · Perform**\nSimulate or tap chords live")

    st.divider()

    ctrl, midi_err = _get_midi()
    clf,  clf_err  = _get_classifier()

    col1, col2 = st.columns(2)
    with col1:
        if midi_err:
            st.warning(f"🔇 Audio unavailable — {midi_err}")
        else:
            st.success("🔊 Audio engine ready")
    with col2:
        if clf_err:
            st.warning(f"🤖 No model — {clf_err}")
        else:
            st.success("🤖 Classifier loaded")

    st.markdown("")
    if st.button("⚡ Begin", type="primary", use_container_width=True):
        _calibrate()


def _calibrate():
    with st.status("Calibrating…", expanded=True) as s:
        for step in CALIB_STEPS:
            st.write(step)
            time.sleep(0.5)
        s.update(label="Calibration complete ✓", state="complete")
    time.sleep(0.3)
    st.session_state.stage = "instrument"
    st.rerun()


# ── Page: Instrument Detection ─────────────────────────────────────────────────
def page_instrument():
    step_bar("instrument")
    st.markdown("## Pick Your Instrument")
    st.caption("Select the gesture you'll hold — it locks in your instrument sound.")
    st.divider()

    gestures = list(GESTURE_TO_INSTRUMENT.keys())

    for row_start in range(0, len(gestures), 4):
        row  = gestures[row_start:row_start + 4]
        cols = st.columns(len(row))
        for col, g in zip(cols, row):
            inst_name, inst_icon = GESTURE_TO_INSTRUMENT[g]
            chord  = GESTURE_TO_CHORD.get(g, "—")
            active = st.session_state.det_gesture == g

            with col:
                cls = "card card-on" if active else "card"
                st.markdown(
                    f'<div class="{cls}" style="text-align:center;">'
                    f'<div style="font-size:1.8rem">{inst_icon}</div>'
                    f'<div style="font-weight:700;font-size:.9rem;margin:.25rem 0">'
                    f'{inst_name}</div>'
                    f'<div style="font-size:.78rem;color:rgba(255,255,255,.4)">'
                    f'{GESTURE_LABEL[g]}</div>'
                    f'<div style="margin-top:.4rem">{pill(chord) if chord else ""}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Select", key=f"g_{g}",
                             type="primary" if active else "secondary",
                             use_container_width=True):
                    st.session_state.det_gesture = g
                    st.rerun()
        st.markdown("")

    st.divider()

    if st.session_state.det_gesture:
        g = st.session_state.det_gesture
        inst_name, inst_icon = GESTURE_TO_INSTRUMENT[g]
        st.success(f"**{inst_icon} {inst_name}** detected via *{GESTURE_LABEL[g]}*")
        if st.button("🔒 Lock & Continue", type="primary", use_container_width=True):
            st.session_state.lock_gesture = g
            st.session_state.lock_inst    = GESTURE_TO_INSTRUMENT[g]
            st.session_state.stage        = "song"
            st.rerun()
    else:
        st.info("Click a card above to choose your instrument.")


# ── Page: Song Selection ───────────────────────────────────────────────────────
def page_song():
    step_bar("song")
    inst_name, inst_icon = st.session_state.lock_inst

    st.markdown("## Pick a Song")
    st.caption(f"Instrument locked: {inst_icon} {inst_name}")
    st.divider()

    songs = st.session_state.songs
    if not songs:
        st.error("No songs found in playlist/ folder.")
        return

    for row_start in range(0, len(songs), 3):
        row_keys = list(songs.keys())[row_start:row_start + 3]
        cols     = st.columns(len(row_keys))

        for col, sk in zip(cols, row_keys):
            s      = songs[sk]
            title  = s.get("title",  sk.replace("_", " ").title())
            artist = s.get("artist", "")
            bpm    = s.get("bpm",    "?")
            secs   = s.get("sections", {})
            seen, chords = set(), []
            for cc in secs.values():
                for c in cc:
                    if c not in seen:
                        seen.add(c); chords.append(c)

            active = st.session_state.song_key == sk
            cls    = "card card-on" if active else "card"
            badges = " ".join(pill(c) for c in chords)

            with col:
                st.markdown(
                    f'<div class="{cls}">'
                    f'<div style="font-weight:700">{title}</div>'
                    f'<div style="font-size:.8rem;color:rgba(255,255,255,.4)">'
                    f'{artist} · {bpm} BPM</div>'
                    f'<div style="margin-top:.5rem">{badges}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if st.button("Select", key=f"s_{sk}",
                             type="primary" if active else "secondary",
                             use_container_width=True):
                    st.session_state.song_key = sk
                    st.rerun()
        st.markdown("")

    st.divider()

    if st.session_state.song_key:
        title = songs[st.session_state.song_key].get("title", st.session_state.song_key)
        st.success(f"**{title}** selected")
        if st.button("🎼 Perform", type="primary", use_container_width=True):
            st.session_state.stage = "perform"
            st.rerun()
    else:
        st.info("Select a song above.")

    st.markdown("")
    if st.button("← Back", use_container_width=True):
        st.session_state.stage       = "instrument"
        st.session_state.det_gesture = None
        st.rerun()


# ── Page: Performance ──────────────────────────────────────────────────────────
def page_perform():
    step_bar("perform")

    songs    = st.session_state.songs
    sk       = st.session_state.song_key
    song     = songs[sk]
    inst_name, inst_icon = st.session_state.lock_inst
    locked_g = st.session_state.lock_gesture

    title    = song.get("title",    sk.replace("_", " ").title())
    artist   = song.get("artist",   "")
    bpm      = song.get("bpm",      "?")
    note     = song.get("note",     "")
    sections = song.get("sections", {})
    struct   = song.get("full_structure", list(sections.keys()))

    st.markdown(f"## {title}")
    st.caption(f"{artist} · {bpm} BPM · {inst_icon} {inst_name}")
    if note:
        st.caption(f"ℹ️ {note}")

    _, midi_err = _get_midi()
    clf, clf_err = _get_classifier()
    if midi_err:
        st.warning(f"Audio unavailable: {midi_err}")

    # ── Unique chords for this song ────────────────────────────────────────────
    seen, song_chords = set(), []
    for cc in sections.values():
        for c in cc:
            if c not in seen:
                seen.add(c); song_chords.append(c)

    # ══════════════════════════════════════════════════════════════════════════
    # LIVE EMG SIMULATION
    # Mirrors realtime_process.py:
    #   fake window → preprocess_emg_df → create_feature_df → run_classifier
    # ══════════════════════════════════════════════════════════════════════════
    st.divider()
    st.markdown("#### 📡 Live EMG Simulation")
    st.caption(
        "Generates a synthetic 250 Hz EMG window every 500 ms and runs it through "
        "the same pipeline as `realtime_process.py`."
    )

    sim_col, btn_col = st.columns([3, 1])
    with sim_col:
        sim_gesture = st.selectbox(
            "Gesture to simulate:",
            options=list(GESTURE_LABEL.keys()),
            format_func=lambda g: GESTURE_LABEL[g],
            index=list(GESTURE_LABEL.keys()).index(
                st.session_state.get("sim_gesture", "palm_up_out")
            ),
            key="sim_gesture_select",
        )
        st.session_state.sim_gesture = sim_gesture

    with btn_col:
        st.markdown("<div style='margin-top:1.75rem'></div>", unsafe_allow_html=True)
        if not st.session_state.simulating:
            if st.button("▶ Run", type="primary", use_container_width=True):
                st.session_state.simulating      = True
                st.session_state.last_prediction = None
                st.rerun()
        else:
            if st.button("■ Stop", type="secondary", use_container_width=True):
                st.session_state.simulating = False
                stop_audio()
                st.session_state.active_chord = None
                st.rerun()

    # ── Simulation loop (one step per Streamlit rerun) ─────────────────────────
    if st.session_state.simulating:
        gesture = st.session_state.sim_gesture

        # 1. Generate fake EMG window (same shape as LSL inlet output)
        window_df = generate_fake_emg(gesture)

        # 2. Classify — identical pipeline to realtime_process.py
        if clf:
            predicted = classify_window(window_df, clf)
        else:
            # No model: echo the selected gesture so the demo still works
            predicted = gesture

        # 3. Play MIDI only when prediction changes (avoids re-strumming same chord)
        predicted_chord = GESTURE_TO_CHORD.get(predicted)
        if predicted != st.session_state.last_prediction:
            if predicted_chord:
                play(CHORD_TO_GESTURE.get(predicted_chord, predicted), locked_g)
                st.session_state.active_chord = predicted_chord
            else:
                stop_audio()
                st.session_state.active_chord = None
            st.session_state.last_prediction = predicted

        # 4. Display waveform
        chart_df = window_df[["GSR", "Ch2"]].rename(
            columns={"GSR": "Inner forearm (flexor)", "Ch2": "Bicep"}
        )
        st.line_chart(chart_df, height=130, use_container_width=True)

        # 5. Show classifier output
        p_color = CHORD_COLORS.get(predicted_chord, "#888") if predicted_chord else "#555"
        chord_tag = (
            f'<span class="pill" style="background:{p_color};">{predicted_chord}</span>'
            if predicted_chord else "<span style='color:rgba(255,255,255,.4)'>🔇 rest</span>"
        )
        st.markdown(
            f"Classified: **{GESTURE_LABEL.get(predicted, predicted)}** → {chord_tag}",
            unsafe_allow_html=True,
        )

        # 6. Pause then trigger next iteration
        time.sleep(0.5)
        st.rerun()

    # ── Manual chord buttons ───────────────────────────────────────────────────
    st.divider()
    st.markdown("**Or tap a chord manually**")

    active_chord = st.session_state.active_chord
    cols = st.columns(len(song_chords))
    for col, chord in zip(cols, song_chords):
        gesture   = CHORD_TO_GESTURE.get(chord, "")
        color     = CHORD_COLORS.get(chord, "#888")
        is_active = (chord == active_chord)
        border    = f"3px solid {color}" if is_active else f"2px solid {color}"
        bg        = f"{color}30" if is_active else f"{color}14"

        with col:
            playing_tag = (
                f'<div style="font-size:.65rem;color:{color};margin-top:.2rem">▶ playing</div>'
                if is_active else ""
            )
            st.markdown(
                f'<div class="chord-card" style="background:{bg};border:{border};">'
                f'<div style="font-size:1.9rem;font-weight:900;color:{color}">{chord}</div>'
                f'<div style="font-size:.75rem;color:rgba(255,255,255,.5);margin-top:.2rem">'
                f'{GESTURE_LABEL.get(gesture, "")}</div>'
                f'{playing_tag}'
                f'</div>',
                unsafe_allow_html=True,
            )
            if st.button("▶ Play", key=f"play_{chord}", use_container_width=True,
                         type="primary" if is_active else "secondary"):
                play(gesture, locked_g)
                st.session_state.active_chord = chord
                st.rerun()

    st.markdown("")
    if st.button("■ Stop", key="manual_stop", use_container_width=True):
        stop_audio()
        st.session_state.active_chord = None
        st.rerun()

    # ── Song structure ─────────────────────────────────────────────────────────
    st.divider()
    with st.expander("📜 Song structure"):
        display = []
        for sec in struct:
            if not display or display[-1][0] != sec:
                display.append([sec, 1])
            else:
                display[-1][1] += 1
        for sec_name, count in display:
            chords = sections.get(sec_name, [])
            label  = sec_name.replace("_", " ").title()
            cnt    = f" (×{count})" if count > 1 else ""
            badges = " ".join(pill(c) for c in chords)
            st.markdown(f"**{label}{cnt}**")
            st.markdown(badges, unsafe_allow_html=True)
            st.markdown("")

    # ── Nav ────────────────────────────────────────────────────────────────────
    st.divider()
    ca, cb = st.columns(2)
    with ca:
        if st.button("← Change Song", use_container_width=True):
            stop_audio()
            st.session_state.simulating   = False
            st.session_state.stage        = "song"
            st.session_state.song_key     = None
            st.session_state.active_chord = None
            st.rerun()
    with cb:
        if st.button("🏠 Start Over", use_container_width=True):
            stop_audio()
            reset()
            st.rerun()


# ── Router ─────────────────────────────────────────────────────────────────────
def main():
    init_state()
    stage = st.session_state.stage
    if stage == "landing":
        page_landing()
    elif stage == "instrument":
        page_instrument()
    elif stage == "song":
        page_song()
    elif stage == "perform":
        page_perform()
    else:
        page_landing()


if __name__ == "__main__":
    main()
