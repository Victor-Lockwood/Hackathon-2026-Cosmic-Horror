import pipeline
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier

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

    start_time = 0

    window = []

    clf = pipeline.load_classifier('../models/classifier.pkl')

    while True:
        sample, timestamp = inlet.pull_sample()

        data_sample = np.array(timestamp)
        data_sample = np.append(data_sample, sample)
        data_sample = np.ndarray.flatten(data_sample)

        window.append(data_sample)

        if start_time == 0:
            start_time = timestamp

        # 250ms
        if timestamp - start_time > 0.25:
            window = np.vstack(window)
            print(f"250ms elapsed {window}")

            col_list = ["timestamp", "GSR"]

            num = 0
            for idx, item in enumerate(sample):
                num = idx + 1
                if num ==1: continue
                col_list.append(f"Ch{num}")

            window_df = pd.DataFrame(data=window, columns=col_list)
            if num == 1:
                window_df["Ch2"] = 0

            preprocessed_df = pipeline.preprocess_emg_df(window_df, 250, True)
            feature_df = pipeline.create_feature_df(preprocessed_df,250, 250, 0.5)


            print(feature_df)

            prediction = pipeline.run_classifier(feature_df, None, "", False, clf)
            print(f"Predicted: {prediction}")

            window = []
            start_time = timestamp

if __name__ == "__main__":
    main()