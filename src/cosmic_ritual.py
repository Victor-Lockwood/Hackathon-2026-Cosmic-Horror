"""
cosmic_ritual.py — The real-time bridge for Cosmic Horror.

Connects to LSL, processes EMG windows, classifies gestures,
and triggers the MidiController.

Designed to be launched from the GUI (with status callbacks) or
standalone from the command line.
"""

import sys
import os
import time
import logging
import pickle
import numpy as np
from pathlib import Path

# Ensure src is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Project imports — MIDI engine is required
from midi_engine import MidiController

# Optional imports — degrade gracefully if the ML pipeline isn't available
try:
    from signal_processing import bandpass_filter, notch_filter
    HAS_SIGNAL_PROCESSING = True
except ImportError:
    HAS_SIGNAL_PROCESSING = False

try:
    from pipeline import extract_features_window
    HAS_PIPELINE = True
except ImportError:
    HAS_PIPELINE = False

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    from pylsl import StreamInlet, resolve_byprop
    HAS_LSL = True
except ImportError:
    HAS_LSL = False

# Terminal styling
C_GRN = "\033[92m"
C_YLW = "\033[93m"
C_CYN = "\033[96m"
C_BLD = "\033[1m"
C_RST = "\033[0m"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ritual")


class MockClassifier:
    """Fallback classifier when no trained model is found."""
    def __init__(self):
        self.gestures = [
            "palm_up_out", "palm_down_out", "palm_down_up",
            "fist_down_out", "fist_down_up", "peace_out", "arm_up"
        ]
        self.last_change = time.time()
        self.idx = 0

    def predict(self, X):
        # Cycle gestures every 3 seconds for the demo
        if time.time() - self.last_change > 3.0:
            self.idx = (self.idx + 1) % len(self.gestures)
            self.last_change = time.time()
        return [self.gestures[self.idx]]


class SimpleFeatureClassifier:
    """Minimal RMS-threshold classifier when pipeline.py is unavailable.

    Allows the ritual to run with basic amplitude-based gesture cycling
    even if the full ML pipeline isn't installed.
    """
    def __init__(self):
        self.gestures = [
            "palm_up_out", "palm_down_out", "palm_down_up",
            "fist_down_out", "fist_down_up", "peace_out", "arm_up"
        ]
        self.idx = 0
        self._last_change = time.time()

    def predict_from_window(self, window_data, channel_names):
        """Classify from raw window data. Returns (gesture, amplitude)."""
        rms = np.sqrt(np.mean(window_data ** 2))
        amplitude = float(np.clip(rms / 1500.0, 0.0, 1.0))

        # Low signal -> rest
        if rms < 50:
            return "arm_down", amplitude

        # Cycle through gestures on a timer (simple demo mode)
        if time.time() - self._last_change > 3.0:
            self.idx = (self.idx + 1) % len(self.gestures)
            self._last_change = time.time()
        return self.gestures[self.idx], amplitude


class CosmicRitual:
    """Real-time LSL -> Classifier -> MIDI bridge.

    Args:
        model_path: Path to a pickled sklearn model.
        stream_name: LSL stream name to resolve.
        status_callback: Optional callable(str) invoked with status messages.
                         The GUI hooks into this to update its label in real time.
        max_resolve_attempts: Number of 1-second LSL resolution attempts before
                              giving up (replaces single 5s blocking call).
    """

    def __init__(self, model_path="models/classifier.pkl", stream_name="BioRadio",
                 status_callback=None, max_resolve_attempts=8):
        self.stream_name = stream_name
        self.model_path = Path(model_path)
        self.status_callback = status_callback or (lambda msg: None)

        self.clf = None
        self.inlet = None
        self.midi = None
        self._simple_clf = None  # fallback when pipeline is missing

        # Buffer settings (matching pipeline.py: 250ms window)
        self.fs = 250  # Default, will be updated from LSL
        self.window_ms = 250
        self.window_samples = 0
        self.n_channels = 0
        self.channel_names = []
        self.buffer = []
        self.running = False
        self.setup_complete = False
        self.setup_error = None
        self._max_resolve_attempts = max_resolve_attempts

    def _status(self, msg):
        """Emit a status message to both logger and the callback."""
        logger.info(msg)
        try:
            self.status_callback(msg)
        except Exception:
            pass

    def setup(self):
        """Initialize MIDI, load model, and connect to LSL.

        Raises RuntimeError if LSL stream cannot be found after retries.
        Sets self.setup_complete = True on success, self.setup_error on failure.
        """
        try:
            self._status("Initializing MIDI engine...")

            # 1. Start MIDI Engine
            self.midi = MidiController()
            self.midi.start()

            # 2. Load Classifier
            self._load_classifier()

            # 3. Resolve LSL Stream (with retries instead of one long block)
            if not HAS_LSL:
                self._cleanup_on_failure()
                self.setup_error = "pylsl not installed"
                self._status("ERROR: pylsl not installed")
                raise RuntimeError("pylsl is not installed")

            self._resolve_lsl_stream()
            self.setup_complete = True
            self._status(f"Connected: {self.n_channels}ch @ {self.fs}Hz")

        except Exception as e:
            self.setup_error = str(e)
            self._status(f"Setup failed: {e}")
            raise

    def _load_classifier(self):
        """Load the trained model, falling back gracefully."""
        if self.model_path.exists():
            try:
                with open(self.model_path, 'rb') as f:
                    self.clf = pickle.load(f)
                self._status(f"Loaded model: {self.model_path.name}")
                return
            except Exception as e:
                self._status(f"Model load failed: {e}")

        # No trained model — choose fallback based on available dependencies
        if HAS_PIPELINE and HAS_PANDAS and HAS_SIGNAL_PROCESSING:
            self._status("No model found. Using MockClassifier.")
            self.clf = MockClassifier()
        else:
            missing = []
            if not HAS_PIPELINE:
                missing.append("pipeline")
            if not HAS_PANDAS:
                missing.append("pandas")
            if not HAS_SIGNAL_PROCESSING:
                missing.append("signal_processing")
            self._status(f"Using SimpleFeatureClassifier (missing: {', '.join(missing)})")
            self._simple_clf = SimpleFeatureClassifier()

    def _resolve_lsl_stream(self):
        """Resolve the LSL stream with multiple short attempts instead of one long block."""
        for attempt in range(1, self._max_resolve_attempts + 1):
            if not self.running and attempt > 1:
                # Cancelled during setup
                self._cleanup_on_failure()
                raise RuntimeError("Ritual cancelled during LSL resolution")

            self._status(f"Searching for '{self.stream_name}'... ({attempt}/{self._max_resolve_attempts})")
            streams = resolve_byprop("name", self.stream_name, timeout=1.0)

            if streams:
                self._connect_inlet(streams[0])
                return

        # All attempts exhausted
        self._cleanup_on_failure()
        raise RuntimeError(
            f"Could not find LSL stream '{self.stream_name}' "
            f"after {self._max_resolve_attempts} attempts"
        )

    def _connect_inlet(self, stream_info):
        """Open the LSL inlet and read stream metadata."""
        self.inlet = StreamInlet(stream_info)
        info = self.inlet.info()
        self.fs = info.nominal_srate()
        self.n_channels = info.channel_count()
        self.window_samples = int(self.fs * self.window_ms / 1000)

        # Extract channel labels
        self.channel_names = []
        ch = info.desc().child("channels").child("channel")
        while not ch.empty():
            self.channel_names.append(ch.child_value("label"))
            ch = ch.next_sibling("channel")

        if not self.channel_names:
            self.channel_names = [f"Ch{i+1}" for i in range(self.n_channels)]

    def _cleanup_on_failure(self):
        """Shut down MIDI if setup fails partway through."""
        if self.midi:
            try:
                self.midi.stop()
            except Exception:
                pass
            self.midi = None

    def run(self):
        """Main classification loop. Blocks until self.running is set to False."""
        if not self.setup_complete:
            raise RuntimeError("Call setup() before run()")

        self._status("Entering The Void...")
        last_prediction = ""
        self.running = True

        try:
            while self.running:
                # Pull chunk of data
                samples, timestamps = self.inlet.pull_chunk(timeout=0.1)
                if not samples:
                    continue

                self.buffer.extend(samples)

                # If we have a full window
                if len(self.buffer) >= self.window_samples:
                    # Take the most recent window
                    window_data = np.array(self.buffer[-self.window_samples:])
                    # Keep some overlap (50%)
                    self.buffer = self.buffer[-(self.window_samples // 2):]

                    # Classify
                    gesture, amplitude = self._classify_window(window_data)

                    # Control MIDI
                    self.midi.on_classification(
                        right_hand=gesture,
                        left_hand=gesture,
                        amplitude=amplitude
                    )

                    if gesture != last_prediction:
                        color = C_YLW if gesture == "arm_down" else C_GRN
                        print(f"Gesture: {color}{gesture:<15}{C_RST} | Amp: {amplitude:.2f}")
                        last_prediction = gesture

        except KeyboardInterrupt:
            print(f"\n{C_YLW}Ritual interrupted.{C_RST}")
        finally:
            self.running = False
            if self.midi:
                self.midi.stop()

    def _classify_window(self, window_data):
        """Run classification on a single window. Returns (gesture, amplitude).

        Uses the full ML pipeline if available, otherwise falls back to
        SimpleFeatureClassifier for basic amplitude-based classification.
        """
        # Fast path: SimpleFeatureClassifier (no pipeline deps needed)
        if self._simple_clf is not None:
            return self._simple_clf.predict_from_window(window_data, self.channel_names)

        # Full pipeline path: preprocess -> extract features -> classify
        filtered = window_data.copy()
        if HAS_SIGNAL_PROCESSING:
            for i in range(self.n_channels):
                filtered[:, i] = bandpass_filter(filtered[:, i], sample_rate=self.fs)
                filtered[:, i] = notch_filter(filtered[:, i], sample_rate=self.fs)

        feat_dict = extract_features_window(filtered, self.channel_names)
        X = pd.DataFrame([feat_dict])

        gesture = self.clf.predict(X)[0]

        # Calculate amplitude (MAV across all channels, normalized)
        amp_raw = np.mean([feat_dict[f"MAV_{ch}"] for ch in self.channel_names])
        amplitude = float(np.clip(amp_raw / 1500.0, 0.0, 1.0))

        return gesture, amplitude


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Cosmic Ritual — biosignal-to-music bridge")
    parser.add_argument("--stream", default="BioRadio", help="LSL stream name")
    parser.add_argument("--model", default="models/classifier.pkl", help="Path to trained pickle")
    args = parser.parse_args()

    def print_status(msg):
        print(f"{C_BLD}{C_CYN}[Ritual] {msg}{C_RST}")

    ritual = CosmicRitual(
        model_path=args.model,
        stream_name=args.stream,
        status_callback=print_status,
    )
    try:
        ritual.running = True  # allow cancellation during setup
        ritual.setup()
        ritual.run()
    except Exception as e:
        logger.error(f"Ritual failed: {e}")
