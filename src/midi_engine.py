"""
midi_engine.py — Real-time MIDI synthesis for Cosmic Horror hackathon.

Self-contained audio: loads a SoundFont via FluidSynth, renders audio
directly to the soundcard. No DAW, no external synth, no extra software.

Usage (standalone test):
    python midi_engine.py

Usage (from classifier pipeline):
    from midi_engine import MidiController
    ctrl = MidiController(soundfont_path="soundfonts/GeneralUser_GS.sf2")
    ctrl.start()
    ctrl.on_classification(right_hand="palm_up_out", left_hand="fist_down_up", amplitude=0.7)
    ctrl.stop()
"""

import json
import os
import time
import threading
import queue
from enum import Enum, auto
from pathlib import Path

try:
    import fluidsynth
    HAS_FLUIDSYNTH = True
except ImportError:
    HAS_FLUIDSYNTH = False

# ---------------------------------------------------------------------------
# Phase 2: Chord & Instrument Mapping
# ---------------------------------------------------------------------------

# Chord voicings as MIDI note numbers.
# Covers all candidate songs: Save Your Tears, Careless Whisper, Love Story,
# Blinding Lights, etc.
CHORDS = {
    "C":   [48, 52, 55, 60, 64, 67],  # C3 E3 G3 C4 E4 G4
    "Am":  [45, 52, 57, 60, 64],       # A2 E3 A3 C4 E4
    "Em":  [40, 47, 52, 55, 59, 64],   # E2 B2 E3 G3 B3 E4
    "G":   [43, 47, 50, 55, 59, 67],   # G2 B2 D3 G3 B3 G4
    "Dm":  [38, 50, 53, 57, 62],       # D2 D3 F3 A3 D4
    "F":   [41, 48, 53, 57, 60, 65],   # F2 C3 F3 A3 C4 F4
    "D":   [38, 45, 50, 54, 57, 62],   # D2 A2 D3 F#3 A3 D4
}

# Right-hand gestures -> chord mapping
GESTURE_TO_CHORD = {
    "palm_up_out":   "C",
    "palm_down_out": "Am",
    "palm_down_up":  "Em",
    "fist_down_out": "G",
    "fist_down_up":  "Dm",
    "peace_out":     "F",
    "arm_up":        "D",
    "arm_down":      None,  # rest / silence
}

# GM instrument program numbers
INSTRUMENTS = {
    "piano":          0,    # Acoustic Grand Piano
    "nylon_guitar":   24,   # Acoustic Guitar (Nylon)
    "steel_guitar":   25,   # Acoustic Guitar (Steel)
    "electric_guitar": 27,  # Electric Guitar (Clean)
    "strings":        48,   # String Ensemble 1
    "pad":            88,   # Pad 2 (Warm)
}

# Left-hand gestures -> instrument mapping
GESTURE_TO_INSTRUMENT = {
    "palm_up_out":   "nylon_guitar",
    "palm_down_out": "steel_guitar",
    "palm_down_up":  "electric_guitar",
    "fist_down_out": "piano",
    "fist_down_up":  "strings",
    "peace_out":     "pad",
    "arm_up":        "nylon_guitar",
    "arm_down":      "nylon_guitar",
}

# ---------------------------------------------------------------------------
# Playlist loader — reads song JSON files from the playlist/ folder
# ---------------------------------------------------------------------------

PLAYLIST_DIR = Path(__file__).parent.parent / "playlist"


def load_song(song_name):
    """Load a song JSON from the playlist/ folder. Returns the parsed dict."""
    path = PLAYLIST_DIR / f"{song_name}.json"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return json.load(f)


def list_songs():
    """Return a list of available song names from the playlist/ folder."""
    if not PLAYLIST_DIR.exists():
        return []
    return [p.stem for p in sorted(PLAYLIST_DIR.glob("*.json"))]


def get_song_progression(song_name, section=None):
    """
    Get the chord progression for a song.
    If section is given (e.g. "verse", "chorus"), return just that section.
    If section is None, return the full structure expanded into chords.
    """
    song = load_song(song_name)
    if song is None:
        return None

    sections = song.get("sections", {})

    if section:
        return sections.get(section)

    # Expand full_structure into a flat chord list
    structure = song.get("full_structure", [])
    if not structure:
        # Fallback: just use the first section
        first = next(iter(sections.values()), [])
        return first

    chords = []
    for s in structure:
        chords.extend(sections.get(s, []))
    return chords

# ---------------------------------------------------------------------------
# Phase 3: State Machine
# ---------------------------------------------------------------------------

class PlayerState(Enum):
    IDLE = auto()
    PLAYING = auto()
    SUSTAIN = auto()


class MidiStateMachine:
    """Manages chord playback state with debouncing and transitions."""

    def __init__(self, debounce_frames=3, strum_delay_ms=15):
        self.state = PlayerState.IDLE
        self.current_chord_name = None
        self.current_instrument_name = None
        self.active_notes = []
        self.debounce_frames = debounce_frames
        self.strum_delay_ms = strum_delay_ms

        # Debounce tracking
        self._pending_chord = None
        self._pending_count = 0

    def process_classification(self, right_hand, left_hand, amplitude=0.5):
        """Process a classification frame. Returns an action dict or None."""
        # Map gestures
        chord_name = GESTURE_TO_CHORD.get(right_hand)
        instrument_name = GESTURE_TO_INSTRUMENT.get(left_hand, self.current_instrument_name)

        action = {"type": None, "chord": None, "instrument": None, "velocity": 0, "notes": []}

        # Instrument change (immediate, no debounce needed)
        if instrument_name and instrument_name != self.current_instrument_name:
            action["instrument"] = instrument_name
            self.current_instrument_name = instrument_name

        # Map amplitude to velocity (0.0-1.0 -> 40-127)
        velocity = int(40 + amplitude * 87)
        velocity = max(40, min(127, velocity))
        action["velocity"] = velocity

        # Rest gesture -> stop playing
        if chord_name is None:
            if self.state != PlayerState.IDLE:
                action["type"] = "stop"
                action["notes"] = list(self.active_notes)
                self.state = PlayerState.IDLE
                self.current_chord_name = None
                self.active_notes = []
                self._pending_chord = None
                self._pending_count = 0
            return action if action["type"] else None

        # Same chord as currently playing -> sustain (do nothing)
        if chord_name == self.current_chord_name and self.state == PlayerState.PLAYING:
            self.state = PlayerState.SUSTAIN
            self._pending_chord = None
            self._pending_count = 0
            return None

        if chord_name == self.current_chord_name and self.state == PlayerState.SUSTAIN:
            return None

        # New chord -> debounce
        if chord_name == self._pending_chord:
            self._pending_count += 1
        else:
            self._pending_chord = chord_name
            self._pending_count = 1

        if self._pending_count < self.debounce_frames:
            return None  # Not enough consecutive frames yet

        # Debounce passed — trigger chord change
        notes = CHORDS.get(chord_name, [])
        action["type"] = "play"
        action["chord"] = chord_name
        action["notes"] = notes
        action["old_notes"] = list(self.active_notes)

        self.current_chord_name = chord_name
        self.active_notes = list(notes)
        self.state = PlayerState.PLAYING
        self._pending_chord = None
        self._pending_count = 0

        return action


# ---------------------------------------------------------------------------
# Phase 1 & 4: Audio Foundation + Integration API
# ---------------------------------------------------------------------------

class MidiController:
    """
    Public interface for the MIDI engine.
    Thread-safe — the classifier pipeline calls on_classification() from any thread,
    audio rendering happens on a dedicated background thread.
    """

    def __init__(self, soundfont_path=None, strum_delay_ms=15, debounce_frames=3,
                 gain=0.8):
        if soundfont_path is None:
            # Auto-find the SoundFont relative to this file or the repo root
            candidates = [
                Path(__file__).parent.parent / "soundfonts" / "GeneralUser_GS.sf2",
                Path("soundfonts") / "GeneralUser_GS.sf2",
            ]
            for c in candidates:
                if c.exists():
                    soundfont_path = str(c)
                    break
            if soundfont_path is None:
                raise FileNotFoundError(
                    "No SoundFont found. Place GeneralUser_GS.sf2 in the soundfonts/ directory."
                )

        self.soundfont_path = str(soundfont_path)
        self.strum_delay_ms = strum_delay_ms
        self.gain = gain

        self.state_machine = MidiStateMachine(
            debounce_frames=debounce_frames,
            strum_delay_ms=strum_delay_ms,
        )

        # Chord progression mode
        self._progression = None
        self._progression_index = 0

        self._queue = queue.Queue()
        self._running = False
        self._thread = None
        self._fs = None
        self._sfid = None
        self._channel = 0

    # -- Lifecycle --

    def start(self):
        """Initialize FluidSynth and start the audio thread."""
        if self._running:
            return

        if not HAS_FLUIDSYNTH:
            raise RuntimeError(
                "pyfluidsynth is not installed. Run: pip install pyfluidsynth"
            )

        self._fs = fluidsynth.Synth(gain=self.gain)

        # Try audio drivers in order of preference for Windows
        for driver in ["wasapi", "dsound", "waveout"]:
            try:
                self._fs.start(driver=driver)
                print(f"[MidiController] Audio driver: {driver}")
                break
            except Exception:
                continue
        else:
            # Last resort: let FluidSynth pick
            self._fs.start()

        self._sfid = self._fs.sfload(self.soundfont_path)
        if self._sfid == -1:
            raise RuntimeError(f"Failed to load SoundFont: {self.soundfont_path}")

        # Default to nylon guitar
        self._fs.program_select(self._channel, self._sfid, 0, 24)
        self.state_machine.current_instrument_name = "nylon_guitar"

        self._running = True
        self._thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._thread.start()
        print(f"[MidiController] Started — SoundFont: {self.soundfont_path}")

    def stop(self):
        """Shut down gracefully: all notes off, clean up FluidSynth."""
        if not self._running:
            return
        self._running = False
        self._queue.put(None)  # sentinel
        if self._thread:
            self._thread.join(timeout=2.0)
        self._all_notes_off()
        if self._fs:
            self._fs.delete()
            self._fs = None
        print("[MidiController] Stopped.")

    # -- Public API --

    def on_classification(self, right_hand=None, left_hand=None, amplitude=0.5):
        """
        Called every classification frame from the real-time loop.
        Thread-safe — enqueues the classification for the audio thread.
        """
        self._queue.put({
            "right_hand": right_hand,
            "left_hand": left_hand,
            "amplitude": amplitude,
        })

    def set_progression(self, song_name, section=None):
        """
        Lock to a song's chord progression from the playlist/ folder.
        Gestures advance through it. Pass section="verse" or "chorus" to
        loop just that section, or None for the full song structure.
        """
        prog = get_song_progression(song_name, section=section)
        if prog is None:
            available = list_songs()
            print(f"[MidiController] Unknown song: {song_name}")
            print(f"[MidiController] Available: {available}")
            return
        self._progression = prog
        self._progression_index = 0
        song = load_song(song_name)
        title = song.get("title", song_name) if song else song_name
        print(f"[MidiController] Progression mode: {title} -> {prog}")

    def clear_progression(self):
        """Exit progression mode, return to free-play."""
        self._progression = None
        self._progression_index = 0

    def advance_progression(self):
        """Move to the next chord in the progression (wraps around)."""
        if self._progression:
            self._progression_index = (self._progression_index + 1) % len(self._progression)
            return self._progression[self._progression_index]
        return None

    def panic(self):
        """All notes off — emergency stop."""
        self._all_notes_off()
        self.state_machine.state = PlayerState.IDLE
        self.state_machine.active_notes = []
        self.state_machine.current_chord_name = None

    def play_chord(self, chord_name, velocity=100, duration=1.0):
        """Play a chord by name (convenience for testing)."""
        notes = CHORDS.get(chord_name)
        if notes is None:
            print(f"[MidiController] Unknown chord: {chord_name}")
            return
        self._strum_on(notes, velocity)
        time.sleep(duration)
        self._notes_off(notes)

    def play_note(self, note, velocity=100, duration=0.5):
        """Play a single note (convenience for testing)."""
        if self._fs:
            self._fs.noteon(self._channel, note, velocity)
            time.sleep(duration)
            self._fs.noteoff(self._channel, note)

    def set_instrument(self, instrument_name):
        """Switch instrument by name."""
        program = INSTRUMENTS.get(instrument_name)
        if program is None:
            print(f"[MidiController] Unknown instrument: {instrument_name}")
            return
        if self._fs and self._sfid is not None:
            self._fs.program_select(self._channel, self._sfid, 0, program)
            self.state_machine.current_instrument_name = instrument_name

    def get_state(self):
        """Return current state for GUI feedback."""
        return {
            "state": self.state_machine.state.name,
            "chord": self.state_machine.current_chord_name,
            "instrument": self.state_machine.current_instrument_name,
            "progression": self._progression,
            "progression_index": self._progression_index,
        }

    # -- Internal --

    def _audio_loop(self):
        """Background thread: drains the classification queue and renders audio."""
        while self._running:
            try:
                msg = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue

            if msg is None:  # sentinel for shutdown
                break

            right = msg.get("right_hand")
            left = msg.get("left_hand")
            amp = msg.get("amplitude", 0.5)

            # In progression mode, any non-rest right-hand gesture advances the progression
            if self._progression and right and GESTURE_TO_CHORD.get(right) is not None:
                chord_name = self._progression[self._progression_index]
                # Override the gesture -> chord mapping
                right = self._chord_to_gesture(chord_name) or right

            action = self.state_machine.process_classification(right, left, amp)
            if action is None:
                continue

            # Instrument change
            if action.get("instrument"):
                self.set_instrument(action["instrument"])

            if action["type"] == "play":
                # Stop old notes first
                old = action.get("old_notes", [])
                if old:
                    self._notes_off(old)
                # Strum new chord
                self._strum_on(action["notes"], action["velocity"])
                # Advance progression if in that mode
                if self._progression:
                    self._progression_index = (self._progression_index + 1) % len(self._progression)

            elif action["type"] == "stop":
                self._notes_off(action["notes"])

    def _strum_on(self, notes, velocity):
        """Play notes with a strum delay for a guitar-like effect."""
        if not self._fs:
            return
        for note in notes:
            self._fs.noteon(self._channel, note, velocity)
            if self.strum_delay_ms > 0 and note != notes[-1]:
                time.sleep(self.strum_delay_ms / 1000.0)

    def _notes_off(self, notes):
        """Turn off a list of notes."""
        if not self._fs:
            return
        for note in notes:
            self._fs.noteoff(self._channel, note)

    def _all_notes_off(self):
        """Send all-notes-off on channel (CC 123)."""
        if not self._fs:
            return
        self._fs.cc(self._channel, 123, 0)

    @staticmethod
    def _chord_to_gesture(chord_name):
        """Reverse lookup: chord name -> first gesture that maps to it."""
        for gesture, chord in GESTURE_TO_CHORD.items():
            if chord == chord_name:
                return gesture
        return None


# ---------------------------------------------------------------------------
# Standalone demo
# ---------------------------------------------------------------------------

def demo():
    """Quick demo: plays through chords and instruments to verify audio works."""
    print("=== MIDI Engine Demo ===")
    print()

    ctrl = MidiController()
    ctrl.start()
    time.sleep(0.5)  # Let FluidSynth initialize audio

    # Demo 1: Single notes
    print("Playing C4 (middle C)...")
    ctrl.play_note(60, velocity=100, duration=0.8)
    time.sleep(0.3)

    # Demo 2: Chords with different instruments
    for inst in ["nylon_guitar", "piano", "strings", "electric_guitar"]:
        print(f"  {inst}: C major chord")
        ctrl.set_instrument(inst)
        ctrl.play_chord("C", velocity=90, duration=0.8)
        time.sleep(0.3)

    # Demo 3: Play songs from the playlist/ folder
    print()
    print(f"Available songs: {list_songs()}")
    print()

    # Play the verse of Save Your Tears
    verse = get_song_progression("save_your_tears", section="verse")
    if verse:
        print(f"Save Your Tears (verse): {verse}")
        ctrl.set_instrument("nylon_guitar")
        for chord in verse:
            print(f"  {chord}")
            ctrl.play_chord(chord, velocity=85, duration=0.7)
            time.sleep(0.2)

    # Play the verse of Careless Whisper
    verse = get_song_progression("careless_whisper", section="verse")
    if verse:
        print()
        print(f"Careless Whisper (verse): {verse}")
        ctrl.set_instrument("piano")
        for chord in verse:
            print(f"  {chord}")
            ctrl.play_chord(chord, velocity=80, duration=0.9)
            time.sleep(0.2)

    # Demo 4: Simulate classifier output
    print()
    print("Simulating classifier input (on_classification)...")
    gestures = [
        ("palm_up_out", "fist_down_out", 0.8),   # C chord, piano
        ("palm_up_out", "fist_down_out", 0.8),   # same (debounce frame 2)
        ("palm_up_out", "fist_down_out", 0.8),   # same (debounce frame 3 -> triggers)
        ("palm_down_out", "fist_down_out", 0.6),  # Am chord
        ("palm_down_out", "fist_down_out", 0.6),
        ("palm_down_out", "fist_down_out", 0.6),
        ("arm_down", None, 0.0),                   # rest -> silence
    ]
    for rh, lh, amp in gestures:
        ctrl.on_classification(right_hand=rh, left_hand=lh, amplitude=amp)
        time.sleep(0.4)

    time.sleep(1.0)
    ctrl.stop()
    print()
    print("Demo complete!")


if __name__ == "__main__":
    demo()
