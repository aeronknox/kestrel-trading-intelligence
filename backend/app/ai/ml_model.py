"""Direction-probability model (scikit-learn), evaluated walk-forward.

Leakage controls:
  * Features at bar t use only data up to and including t (causal indicators).
  * The label is the sign of the return from t to t+horizon, so the final
    `horizon` rows have no label and are never used for training.
  * Cross-validation is a forward-chaining TimeSeriesSplit with a `gap` equal to
    the horizon, so a training label never overlaps a test window.
  * Reported accuracy is purely out-of-sample and is compared to the naive
    majority-class baseline. When the model shows no skill, the signal engine
    gives it zero weight.

The output is a *statistical estimate*, never a guarantee.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = [
    "ret_1", "ret_3", "ret_6", "ret_12", "rsi_14", "macd_hist_n", "bb_pct_b", "bb_width",
    "volume_z", "dist_sma_20", "dist_sma_50", "atr_n",
]  # fmt: skip

FEATURE_LABELS = {
    "ret_1": "1-bar return",
    "ret_3": "3-bar return",
    "ret_6": "6-bar return",
    "ret_12": "12-bar return",
    "rsi_14": "RSI(14)",
    "macd_hist_n": "MACD histogram",
    "bb_pct_b": "Bollinger %B",
    "bb_width": "Bollinger width",
    "volume_z": "Volume z-score",
    "dist_sma_20": "Distance from SMA20",
    "dist_sma_50": "Distance from SMA50",
    "atr_n": "ATR / price",
}

MIN_TRAIN_ROWS = 150


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    close = df["close"]
    feats = pd.DataFrame(index=df.index)
    for k in (1, 3, 6, 12):
        feats[f"ret_{k}"] = close.pct_change(k)
    feats["rsi_14"] = df["rsi_14"]
    feats["macd_hist_n"] = df["macd_hist"] / close
    feats["bb_pct_b"] = df["bb_pct_b"]
    feats["bb_width"] = df["bb_width"]
    feats["volume_z"] = df["volume_z"]
    feats["dist_sma_20"] = close / df["sma_20"] - 1
    feats["dist_sma_50"] = close / df["sma_50"] - 1
    feats["atr_n"] = df["atr_14"] / close
    return feats.replace([np.inf, -np.inf], np.nan)


def build_labels(df: pd.DataFrame, horizon: int) -> pd.Series:
    future = df["close"].shift(-horizon)
    label = (future > df["close"]).astype(float)
    label[future.isna()] = np.nan
    return label


def _model():  # type: ignore[no-untyped-def]
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=500))


def predict_direction(df: pd.DataFrame, horizon: int = 3, n_splits: int = 5) -> dict:
    feats = build_features(df)
    labels = build_labels(df, horizon)
    data = feats.assign(y=labels)
    train = data.dropna()
    latest = feats.iloc[[-1]]

    base: dict = {
        "model": "logistic_regression",
        "horizon_bars": horizon,
        "label": "Statistical estimate — not a guarantee of future price movement.",
    }
    if len(train) < MIN_TRAIN_ROWS or latest.isna().any(axis=1).iloc[0]:
        return base | {"available": False, "reason": f"Insufficient history (need ≥{MIN_TRAIN_ROWS} labeled bars)."}
    if train["y"].nunique() < 2:
        return base | {"available": False, "reason": "Labels have a single class in the training window."}

    X, y = train[FEATURES].to_numpy(), train["y"].to_numpy().astype(int)
    splitter = TimeSeriesSplit(n_splits=n_splits, gap=horizon)
    correct = total = 0
    baseline_correct = 0
    for train_idx, test_idx in splitter.split(X):
        if len(np.unique(y[train_idx])) < 2:
            continue
        model = _model().fit(X[train_idx], y[train_idx])
        pred = model.predict(X[test_idx])
        correct += int((pred == y[test_idx]).sum())
        majority = int(y[train_idx].mean() >= 0.5)
        baseline_correct += int((y[test_idx] == majority).sum())
        total += len(test_idx)
    if total == 0:
        return base | {"available": False, "reason": "Walk-forward validation could not be run."}

    accuracy = correct / total
    baseline = baseline_correct / total
    final = _model().fit(X, y)
    prob_up = float(final.predict_proba(latest[FEATURES].to_numpy())[0][1])

    # Per-feature contribution to the log-odds for the latest bar (explainability).
    scaler, clf = final.named_steps["standardscaler"], final.named_steps["logisticregression"]
    z = scaler.transform(latest[FEATURES].to_numpy())[0]
    ranked = sorted(
        ((f, float(c * v)) for f, c, v in zip(FEATURES, clf.coef_[0], z, strict=True)),
        key=lambda fc: -abs(fc[1]),
    )
    contributions = [{"feature": FEATURE_LABELS[f], "contribution": c} for f, c in ranked[:5]]

    return base | {
        "available": True,
        "prob_up": prob_up,
        "oos_accuracy": accuracy,
        "baseline_accuracy": baseline,
        "skill": accuracy - baseline,
        "n_train": len(train),
        "n_test": int(total),
        "top_features": contributions,
    }
