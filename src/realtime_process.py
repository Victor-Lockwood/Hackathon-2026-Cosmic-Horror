import pipeline
import time
from pylsl import StreamInlet, resolve_streams

# cd into the examples directory first and run this before this script: python 02_stream_to_lsl.py

def main():
    streams = resolve_streams()
    filtered = [s for s in streams if s.type() == 'EMG']

    if not streams:
        print("No stream found")
        return

    inlet = StreamInlet(filtered[0])

    while True:
        sample, timestamp = inlet.pull_sample()
        print(f"Timestamp: {timestamp}\nSample:{sample}")
        time.sleep(1)
        # sample is a list of channel values
        # Process, classify, and control here

if __name__ == "__main__":
    main()