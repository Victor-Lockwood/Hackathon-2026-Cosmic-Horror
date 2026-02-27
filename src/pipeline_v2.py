import os
import pickle

import pandas as pd
import numpy as np

from scipy.signal import butter, filtfilt, iirnotch

from sklearn.svm import SVC
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.neighbors import KNeighborsClassifier
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.pipeline import Pipeline

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


# =====================================================================
# Filters  (unchanged from pipeline.py)
# =====================================================================

def bandpass_filter(signal, fs, low=20, high=450, order=4):
    """Apply a bandpass filter."""
    nyq = 0.5 * fs
    if high >= nyq:
        high = nyq * 0.95
    b, a = butter(order, [low/nyq, high/nyq], btype='band')
    return filtfilt(b, a, signal)


def notch_filter(signal, fs, freq=60, Q=30):
    """Apply a notch filter to remove 60 Hz power-line noise."""
    nyq = 0.5 * fs
    b, a = iirnotch(freq/nyq, Q)
    return filtfilt(b, a, signal)


# =====================================================================
# Preprocessing  (unchanged from pipeline.py)
# =====================================================================

def preprocess_emg_df(df, fs, apply_notch=False):
    """
    df: pandas DataFrame with columns: timestamp, Ch1, Ch2, ...
    fs: sampling rate (Hz)
    apply_notch: whether to apply 60 Hz notch
    Returns: DataFrame with filtered channels (timestamp preserved)
    """
    df_filtered = df.copy()
    channels = df.columns[1:]
    for ch in channels:
        sig = df[ch].values
        sig = bandpass_filter(sig, fs)
        if apply_notch:
            sig = notch_filter(sig, fs)
        df_filtered[ch] = sig
    return df_filtered


def extract_features_window(window, channel_names):
    """Extract time-domain features from a single window."""
    features = {}
    for i, ch in enumerate(channel_names):
        sig = window[:, i]
        features[f"RMS_{ch}"] = np.sqrt(np.mean(sig**2))
        features[f"MAV_{ch}"] = np.mean(np.abs(sig))
        features[f"Var_{ch}"] = np.var(sig)
        features[f"WL_{ch}"]  = np.sum(np.abs(np.diff(sig)))
        features[f"ZC_{ch}"]  = np.sum(np.diff(np.sign(sig)) != 0)
    return features


def create_feature_df(df, fs, window_ms=250, overlap=0.5, labels=None):
    """
    Sliding-window feature extraction.
    df: filtered DataFrame (timestamp + channels)
    fs: sampling rate
    Returns: feature DataFrame, optionally with Label column
    """
    channels = df.columns[1:]
    data = df[channels].values
    window_size = int(fs * window_ms / 1000)
    step = int(window_size * (1 - overlap))

    feature_rows = []
    for start in range(0, len(data) - window_size, step):
        window = data[start:start + window_size, :]
        feature_rows.append(extract_features_window(window, channels))

    feature_df = pd.DataFrame(feature_rows)

    if labels is not None:
        feature_df["Label"] = labels[:len(feature_df)]

    return feature_df


def pipeline(csv, fs, window_size, overlap, label):
    """Single CSV → labeled feature DataFrame."""
    df = pd.read_csv(csv, skiprows=8)
    df = preprocess_emg_df(df, 250, True)
    feature_df = create_feature_df(df, fs, window_size, overlap)
    feature_df['label'] = label
    return feature_df


def batch_pipeline(csv_dictionary: dict, fs, window_size, overlap, standardize=False):
    """
    Preprocess a batch of labeled CSVs into X, y.

    Fix over pipeline.py: standardize=True now correctly returns scaled X
    (original returned unscaled X by mistake).
    """
    df_batch = pd.DataFrame()
    for key, val in csv_dictionary.items():
        csv_df = pipeline(val, fs, window_size, overlap, key)
        df_batch = pd.concat([df_batch, csv_df])

    df_batch = df_batch.reset_index(drop=True)
    feature_cols = df_batch.columns[:-1]
    label_col    = df_batch.columns[-1]

    X = df_batch[feature_cols]
    y = df_batch[label_col]

    if standardize:
        scaler = StandardScaler()
        X = pd.DataFrame(scaler.fit_transform(X), columns=feature_cols)

    return X, y


# =====================================================================
# Shared utilities
# =====================================================================

def _ensure_models_dir():
    os.makedirs('../models', exist_ok=True)


def _save_clf(clf, filename):
    _ensure_models_dir()
    path = f'../models/{filename}'
    with open(path, 'wb') as f:
        pickle.dump(clf, f)
    print(f"  Saved → {path}")
    return path


def load_classifier(path):
    with open(path, 'rb') as f:
        return pickle.load(f)


def run_classifier(X, y, classifier_path="", print_stats=True, clf=None):
    """
    Run any saved classifier on X.
    Pass y=None and print_stats=False when true labels are unknown.
    """
    if clf is None:
        if not classifier_path:
            print("No path or classifier provided.")
            return
        clf = load_classifier(classifier_path)

    y_pred = clf.predict(X)

    if print_stats:
        if y is None:
            print("No labels to compare against.")
        else:
            print(classification_report(y, y_pred))

    return y_pred


# =====================================================================
# XGBoost wrapper
# Pairs XGBClassifier with a LabelEncoder so predict() returns the
# original string labels — same interface as every other classifier.
# =====================================================================

class _XGBWrapper:
    def __init__(self):
        self.le = LabelEncoder()
        self.clf = XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.8,
            eval_metric='mlogloss',
            random_state=42,
        )

    def fit(self, X, y):
        self.clf.fit(X, self.le.fit_transform(y))
        return self

    def predict(self, X):
        return self.le.inverse_transform(self.clf.predict(X))

    def predict_proba(self, X):
        return self.clf.predict_proba(X)


# =====================================================================
# Model trainers
# Every trainer returns (X_test, y_test, path) — same as pipeline.py.
# random_state=42 + same input data means all models see the same split.
# =====================================================================

def train_random_forest(X, y):
    """
    Random Forest classifier — ported directly from pipeline.py.
    n_estimators = floor(sqrt(n_features)), matching the original logic.
    """
    import math
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    n_estimators = math.floor(math.sqrt(X_train.shape[1]))
    clf = RandomForestClassifier(n_estimators=n_estimators, random_state=42)
    clf.fit(X_train, y_train)
    path = _save_clf(clf, 'classifier_rf.pkl')
    return X_test, y_test, path


def train_svm(X, y):
    """
    SVM with RBF kernel.
    StandardScaler is baked into the Pipeline — no pre-scaling needed.
    Literature gold standard for EMG gesture classification.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    clf = Pipeline([
        ('scaler', StandardScaler()),
        ('svm', SVC(kernel='rbf', C=10, gamma='scale',
                    decision_function_shape='ovr', probability=True)),
    ])
    clf.fit(X_train, y_train)
    path = _save_clf(clf, 'classifier_svm.pkl')
    return X_test, y_test, path


def train_lda(X, y):
    """
    Linear Discriminant Analysis.
    Fastest trainer; gold standard for real-time prosthetic EMG control.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    clf = LinearDiscriminantAnalysis(solver='svd')
    clf.fit(X_train, y_train)
    path = _save_clf(clf, 'classifier_lda.pkl')
    return X_test, y_test, path


def train_xgb(X, y):
    """
    XGBoost gradient-boosted classifier.
    Requires: pip install xgboost
    Typically outperforms Random Forest on tabular feature data.
    """
    if not HAS_XGB:
        print("  XGBoost not installed — skipping. Run: pip install xgboost")
        return None, None, None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    clf = _XGBWrapper()
    clf.fit(X_train, y_train)
    path = _save_clf(clf, 'classifier_xgb.pkl')
    return X_test, y_test, path


def train_knn(X, y, k=5):
    """
    k-Nearest Neighbors with Euclidean distance.
    StandardScaler is baked into the Pipeline.
    Simple but effective on small, well-featured biosignal datasets.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    clf = Pipeline([
        ('scaler', StandardScaler()),
        ('knn', KNeighborsClassifier(n_neighbors=k, metric='euclidean')),
    ])
    clf.fit(X_train, y_train)
    path = _save_clf(clf, 'classifier_knn.pkl')
    return X_test, y_test, path


def train_voting_ensemble(X, y):
    """
    Soft-voting ensemble of SVM + LDA + KNN.
    Each sub-model votes via predicted class probabilities.
    """
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    svm = Pipeline([
        ('scaler', StandardScaler()),
        ('svm', SVC(kernel='rbf', C=10, gamma='scale',
                    decision_function_shape='ovr', probability=True)),
    ])
    lda = LinearDiscriminantAnalysis(solver='svd')
    knn = Pipeline([
        ('scaler', StandardScaler()),
        ('knn', KNeighborsClassifier(n_neighbors=5, metric='euclidean')),
    ])

    clf = VotingClassifier(
        estimators=[('svm', svm), ('lda', lda), ('knn', knn)],
        voting='soft',
    )
    clf.fit(X_train, y_train)
    path = _save_clf(clf, 'classifier_ensemble.pkl')
    return X_test, y_test, path


# =====================================================================
# Comparison runner
# =====================================================================

def compare_all_models(X, y):
    """
    Train all five models on the same data and print a side-by-side report.
    All trainers use random_state=42 so they share the same 80/20 split.
    """
    models = {
        'Random Forest':      train_random_forest,
        'SVM (RBF kernel)':   train_svm,
        'LDA':                train_lda,
        'XGBoost':            train_xgb,
        'KNN (k=5)':          train_knn,
        'Voting Ensemble':    train_voting_ensemble,
    }

    sep = "=" * 60
    for name, trainer in models.items():
        print(f"\n{sep}")
        print(f"  {name}")
        print(sep)
        X_test, y_test, path = trainer(X, y)
        if path is None:
            continue
        clf = load_classifier(path)
        run_classifier(X_test, y_test, clf=clf, print_stats=True)


# =====================================================================
# main
# =====================================================================

def main():
    csv_dict = {
        "arm_down":      "../data/Cosmic_Horror/arm down_20260226_201414.csv",
        "arm_up":        "../data/Cosmic_Horror/arm up side palm down_20260226_201448.csv",
        "fist_down_out": "../data/Cosmic_Horror/fist-down-out_20260226_201320.csv",
        "fist_down_up":  "../data/Cosmic_Horror/fist-down-up_20260226_201341.csv",
        "palm_down_out": "../data/Cosmic_Horror/palm-down-out_20260226_201210.csv",
        "palm_down_up":  "../data/Cosmic_Horror/palm-down-up_20260226_201238.csv",
        "palm_up_out":   "../data/Cosmic_Horror/palm-up-out_20260226_200912.csv",
        "peace_out":     "../data/Cosmic_Horror/peace out_20260226_201518.csv",
    }

    # standardize=False: SVM, KNN, and the ensemble bake their own scalers.
    # LDA and XGBoost are scale-insensitive anyway.
    X, y = batch_pipeline(csv_dict, 250, 250, 0.5, standardize=False)

    compare_all_models(X, y)


if __name__ == "__main__":
    main()
