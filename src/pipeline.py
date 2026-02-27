import pandas as pd
import numpy as np

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

    feature_df = pd.DataFrame(feature_rows)

    if labels is not None:
        feature_df["Label"] = labels[:len(feature_df)]

    return feature_df

def pipeline(csv, fs, window_size, overlap, label):
    """
    Pipeline for preprocessing.  Named somewhat poorly.  I'm tired.
    """

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
        csv_df = pipeline(val, fs, window_size, overlap, key)
        df_batch = pd.concat([df_batch, csv_df])

    feature_cols = df_batch.columns[:-1]
    label_col = df_batch.columns[-1]

    if standardize:
        scaler = StandardScaler()


        X = df_batch[feature_cols]
        Y = df_batch[label_col]

        X_scaled = scaler.fit_transform(X)
        final_df = pd.DataFrame(X_scaled, columns=feature_cols, index=df_batch.index)
        final_df[label_col] = Y
        return X, Y

    return df_batch[feature_cols], df_batch[label_col]

def train_classifier(X, y):
    """
    Train the random forest classifier and save the classifier.
    """
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=.2, random_state=42)

    clf = RandomForestClassifier(n_estimators=100, random_state=42)
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
        "arm_down": "../data/Cosmic_Horror/arm down_20260226_201414.csv",
        "arm_up": "../data/Cosmic_Horror/arm up side palm down_20260226_201448.csv",
        "fist_down_out": "../data/Cosmic_Horror/fist-down-out_20260226_201320.csv",
        "fist_down_up": "../data/Cosmic_Horror/fist-down-up_20260226_201341.csv",
        "palm_down_out": "../data/Cosmic_Horror/palm-down-out_20260226_201210.csv",
        "palm_down_up": "../data/Cosmic_Horror/palm-down-up_20260226_201238.csv",
        "palm_up_out": "../data/Cosmic_Horror/palm-up-out_20260226_200912.csv",
        "peace_out": "../data/Cosmic_Horror/peace out_20260226_201518.csv"
    }

    # Feed in the CSVs for training
    X_batch, y_batch = batch_pipeline(csv_dict, 250, 250, 0.5, True)

    # Train based on CSV data, get out the test X and Y data from the test train split as well as the path the model was saved to
    X_test, y_test, path = train_classifier(X_batch, y_batch)

    # Run the classifier on input data.  Path is to where the model is saved
    # If you don't have the real labels to run against, pass in "None" for y and set print_stats=False (default)
    clf = load_classifier(path)
    run_classifier(X_test, y_test, print_stats=True, clf=clf)



if __name__ == "__main__":
    main()