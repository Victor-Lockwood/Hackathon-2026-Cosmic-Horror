import math

import pandas as pd
import numpy as np
import re

from scipy.signal import butter, filtfilt, iirnotch

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import StandardScaler

import pickle

def bandpass_filter(signal, fs, low=20, high=450, order=4):
    """
    Apply a bandpass filter.
    """

    nyq = 0.5 * fs
    if high >= nyq:
        high = nyq * 0.95  # safe margin
    b, a = butter(order, [low/nyq, high/nyq], btype='band')
    return filtfilt(b, a, signal)

def notch_filter(signal, fs, freq=60, Q=30):
    """
    Apply a notch filter, which handles outside electrical noise.  In the US, it is 60Hz.
    """
    nyq = 0.5 * fs
    b, a = iirnotch(freq/nyq, Q)
    return filtfilt(b, a, signal)

# --- Preprocessing for DataFrame ---
def preprocess_emg_df(df, fs, apply_notch=False):
    """
    df: pandas DataFrame with columns: timestamp, Mock_Ch1, Mock_Ch2, ...
    fs: sampling rate (Hz)
    apply_notch: whether to apply 60 Hz notch
    Returns: DataFrame with filtered EMG channels (timestamp preserved)
    """
    df_filtered = df.copy()

    # Assume first column is timestamp
    channels = df.columns[1:]

    for ch in channels:
        signal = df[ch].values
        signal = bandpass_filter(signal, fs)
        if apply_notch:
            signal = notch_filter(signal, fs)
        df_filtered[ch] = signal

    return df_filtered

def extract_features_window(window, channel_names):
    """
    Extract features from a given window of data.
    """
    features = {}
    for i, ch in enumerate(channel_names):
        sig = window[:, i]
        features[f"RMS_{ch}"] = np.sqrt(np.mean(sig**2))
        features[f"MAV_{ch}"] = np.mean(np.abs(sig))
        features[f"Var_{ch}"] = np.var(sig)
        features[f"WL_{ch}"] = np.sum(np.abs(np.diff(sig)))
        features[f"ZC_{ch}"] = np.sum(np.diff(np.sign(sig)) != 0)
    return features

# --- Windowing + feature extraction ---
def create_feature_df(df, fs, window_ms=250, overlap=0.5, labels=None):
    """
    Create the feature data frame from the filtered EMG data.  Window size is time in ms.
    df: filtered EMG DataFrame (timestamp + channels)
    fs: sampling rate
    labels: optional array of labels per window
    """
    channels = df.columns[1:]
    data = df[channels].values
    window_size = int(fs * window_ms / 1000)
    step = int(window_size * (1-overlap))

    feature_rows = []
    for start in range(0, len(data) - window_size, step):
        window = data[start:start+window_size, :]
        features = extract_features_window(window, channels)
        feature_rows.append(features)

    if len(data) <= window_size:
        features = extract_features_window(data, channels)
        feature_rows.append(features)

    feature_df = pd.DataFrame(feature_rows)

    if labels is not None:
        feature_df["label"] = labels[:len(feature_df)]

    return feature_df

def pipeline(csv, fs, window_size, overlap, label, pipeline_df=None):
    """
    Pipeline for preprocessing.  Named somewhat poorly.  I'm tired.
    """

    if pipeline_df is None:
        pipeline_df = pd.read_csv(csv, skiprows=8)

    preprocessed_df = preprocess_emg_df(pipeline_df, 250, True)
    pipeline_feature_df = create_feature_df(preprocessed_df, fs, window_size, overlap)
    pipeline_feature_df['label'] = label

    return pipeline_feature_df

def batch_pipeline(csv_dictionary: dict, fs, window_size, overlap, standardize=False):
    """
    Preprocess a batch of CSV data.
    """
    df_batch = pd.DataFrame()

    for key, val in csv_dictionary.items():
        result = re.sub(r'[^a-zA-Z]+', '', key)
        csv_df = pipeline(val, fs, window_size, overlap, result)
        df_batch = pd.concat([df_batch, csv_df])

    label_col = 'label'
    feature_cols = [col for col in df_batch.columns if col != label_col and col != 'timestamp']

    if standardize:
        scaler = StandardScaler()


        X = df_batch[feature_cols]
        Y = df_batch[label_col]

        X_scaled = scaler.fit_transform(X)
        final_df = pd.DataFrame(X_scaled, columns=feature_cols, index=df_batch.index)
        final_df[label_col] = Y
        return X, Y

    return df_batch[feature_cols], df_batch[label_col]

def train_classifier(X, y, n_estimators):
    """
    Train the random forest classifier and save the classifier.
    """
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=.2, random_state=42)

    clf = RandomForestClassifier(n_estimators=n_estimators, random_state=42)
    clf.fit(X_train, y_train)

    path = '../models/classifier.pkl'
    with open(path, 'wb') as file:
        pickle.dump(clf, file)
    print(f"Classifier saved to {path}")

    return X_test, y_test, path


def load_classifier(path):
    with open(path, 'rb') as file:
        clf = pickle.load(file)

    return clf


def run_classifier(X, y, classifier_path="", print_stats=True, clf=None):
    """
    Run the classifier on the input data.  If true labels aren't known, pass in None for y.
    """
    if clf is None:
        if classifier_path == "":
            print("No path specified for classifier")
            return

        clf = load_classifier(classifier_path)

    y_pred = clf.predict(X)

    if print_stats:
        if y is None:
            print("No labels to compare against.")
            return y_pred

        print(classification_report(y, y_pred))

    return y_pred

def main():

    # Change these to point at training data CSVs
    # the keys are the labels

    csv_dict = {
        "armdown_01": "../data/Grant/armdown_01_20260227_143904.csv",
        "armdown_02": "../data/Grant/armdown_02_20260227_143914.csv",
        "armdown_03": "../data/Grant/armdown_03_20260227_143923.csv",
        "armdown_04": "../data/Grant/armdown_04_20260227_143932.csv",
        "armdown_05": "../data/Grant/armdown_05_20260227_143943.csv",
        "armdown_06": "../data/Grant/armdown_06_20260227_143953.csv",
        "armdown_07": "../data/Grant/armdown_07_20260227_144003.csv",
        "armdown_08": "../data/Grant/armdown_08_20260227_144013.csv",
        "armdown_09": "../data/Grant/armdown_09_20260227_144022.csv",
        "armdown_10": "../data/Grant/armdown_10_20260227_144041.csv",
        "armdown_11": "../data/Grant/armdown_11_20260227_152953.csv",
        "armdown_12": "../data/Grant/armdown_12_20260227_153025.csv",
        "armdown_13": "../data/Grant/armdown_13_20260227_153048.csv",
        "armdown_14": "../data/Grant/armdown_14_20260227_153110.csv",
        "armdown_15": "../data/Grant/armdown_15_20260227_153142.csv",
        "baseline_01": "../data/Grant/baseline_01_20260227_143554.csv",
        "baseline_02": "../data/Grant/baseline_02_20260227_143614.csv",
        "baseline_03": "../data/Grant/baseline_03_20260227_143629.csv",
        "baseline_04": "../data/Grant/baseline_04_20260227_143727.csv",
        "baseline_05": "../data/Grant/baseline_05_20260227_143736.csv",
        "baseline_06": "../data/Grant/baseline_06_20260227_143746.csv",
        "baseline_07": "../data/Grant/baseline_07_20260227_143756.csv",
        "baseline_08": "../data/Grant/baseline_08_20260227_143806.csv",
        "baseline_09": "../data/Grant/baseline_09_20260227_143816.csv",
        "baseline_10": "../data/Grant/baseline_10_20260227_143829.csv",
        "baseline_11": "../data/Grant/baseline_11_20260227_153340.csv",
        "baseline_12": "../data/Grant/baseline_12_20260227_153404.csv",
        "baseline_13": "../data/Grant/baseline_13_20260227_153423.csv",
        "baseline_14": "../data/Grant/baseline_14_20260227_153439.csv",
        "baseline_15": "../data/Grant/baseline_15_20260227_153454.csv",
        "superman_01": "../data/Grant/superman_01_20260227_144517.csv",
        "superman_02": "../data/Grant/superman_02_20260227_144526.csv",
        "superman_03": "../data/Grant/superman_03_20260227_144537.csv",
        "superman_04": "../data/Grant/superman_04_20260227_144546.csv",
        "superman_05": "../data/Grant/superman_05_20260227_144612.csv",
        "superman_06": "../data/Grant/superman_06_20260227_144622.csv",
        "superman_07": "../data/Grant/superman_07_20260227_144631.csv",
        "superman_08": "../data/Grant/superman_08_20260227_144641.csv",
        "superman_09": "../data/Grant/superman_09_20260227_144730.csv",
        "superman_10": "../data/Grant/superman_10_20260227_144741.csv",
        "superman_11": "../data/Grant/superman_11_20260227_154841.csv",
        "superman_12": "../data/Grant/superman_12_20260227_154815.csv",
        "superman_13": "../data/Grant/superman_13_20260227_154726.csv",
        "superman_14": "../data/Grant/superman_14_20260227_153937.csv",
        "superman_15": "../data/Grant/superman_15_20260227_153525.csv",
        "uppercut_01": "../data/Grant/uppercut_01_20260227_144815.csv",
        "uppercut_02": "../data/Grant/uppercut_02_20260227_144825.csv",
        "uppercut_03": "../data/Grant/uppercut_03_20260227_144909.csv",
        "uppercut_04": "../data/Grant/uppercut_04_20260227_144845.csv",
        "uppercut_05": "../data/Grant/uppercut_05_20260227_144918.csv",
        "uppercut_06": "../data/Grant/uppercut_06_20260227_145049.csv",
        "uppercut_07": "../data/Grant/uppercut_07_20260227_145131.csv",
        "uppercut_08": "../data/Grant/uppercut_08_20260227_145151.csv",
        "uppercut_09": "../data/Grant/uppercut_09_20260227_145201.csv",
        "uppercut_10": "../data/Grant/uppercut_10_20260227_145212.csv",
        "uppercut_11": "../data/Grant/uppercut_11_20260227_155140.csv",
        "uppercut_12": "../data/Grant/uppercut_12_20260227_155453.csv",
        "uppercut_13": "../data/Grant/uppercut_13_20260227_155527.csv",
        "uppercut_14": "../data/Grant/uppercut_14_20260227_155548.csv",
        "uppercut_15": "../data/Grant/uppercut_15_20260227_155615.csv",
        "zombie_01": "../data/Grant/zombie_01_20260227_144247.csv",
        "zombie_02": "../data/Grant/zombie_02_20260227_144256.csv",
        "zombie_03": "../data/Grant/zombie_03_20260227_144306.csv",
        "zombie_04": "../data/Grant/zombie_04_20260227_144316.csv",
        "zombie_05": "../data/Grant/zombie_05_20260227_144326.csv",
        "zombie_06": "../data/Grant/zombie_06_20260227_144336.csv",
        "zombie_07": "../data/Grant/zombie_07_20260227_144345.csv",
        "zombie_08": "../data/Grant/zombie_08_20260227_144420.csv",
        "zombie_09": "../data/Grant/zombie_09_20260227_144430.csv",
        "zombie_10": "../data/Grant/zombie_10_20260227_144440.csv",
        "zombie_11": "../data/Grant/zombie_11_20260227_154912.csv",
        "zombie_12": "../data/Grant/zombie_12_20260227_154936.csv",
        "zombie_13": "../data/Grant/zombie_13_20260227_154956.csv",
        "zombie_14": "../data/Grant/zombie_14_20260227_155024.csv",
        "zombie_15": "../data/Grant/zombie_15_20260227_155043.csv"
    }

    # Feed in the CSVs for training
    X_batch, y_batch = batch_pipeline(csv_dict, 250, 250, 0.5, True)

    # Train based on CSV data, get out the test X and Y data from the test train split as well as the path the model was saved to
    # You can toy with the n_estimators parameter a bit
    X_test, y_test, path = train_classifier(X_batch, y_batch, 100)

    # Run the classifier on input data.  Path is to where the model is saved
    # If you don't have the real labels to run against, pass in "None" for y and set print_stats=False (default)
    clf = load_classifier(path)
    run_classifier(X_test, y_test, print_stats=True, clf=clf)



if __name__ == "__main__":
    main()