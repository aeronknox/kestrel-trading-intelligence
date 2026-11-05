import numpy as np
import pytest

from app.ai.analysis_engine import compute_analysis
from app.ai.ml_model import build_features, build_labels, predict_direction
from app.ai.signals import MAX_CONFIDENCE, Component, combine
from app.core.exceptions import ValidationFailedError
from app.indicators.technical import add_standard_indicators
from tests.conftest import make_frame


def _random_walk(n: int = 700, seed: int = 0, drift: float = 0.0) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n))))


def test_labels_never_use_unavailable_future() -> None:
    df = add_standard_indicators(make_frame(_random_walk(300)))
    labels = build_labels(df, horizon=3)
    assert labels.iloc[-3:].isna().all()
    assert labels.iloc[:-3].notna().all()


def test_features_are_causal() -> None:
    closes = _random_walk(400, seed=5)
    full = build_features(add_standard_indicators(make_frame(closes)))
    part = build_features(add_standard_indicators(make_frame(closes[:250])))
    np.testing.assert_allclose(full.iloc[:250].to_numpy(), part.to_numpy(), rtol=1e-9, equal_nan=True)


def test_ml_reports_out_of_sample_metrics() -> None:
    df = add_standard_indicators(make_frame(_random_walk(700, seed=1)))
    ml = predict_direction(df)
    assert ml["available"]
    assert 0 <= ml["prob_up"] <= 1
    assert ml["n_test"] > 0 and ml["n_train"] > ml["n_test"] * 0.5
    # A pure random walk should not show a large edge out-of-sample.
    assert abs(ml["skill"]) < 0.1
    assert "estimate" in ml["label"].lower()


def test_ml_insufficient_history() -> None:
    df = add_standard_indicators(make_frame(_random_walk(100)))
    assert predict_direction(df)["available"] is False


def test_combine_thresholds_and_confidence_cap() -> None:
    bullish = [Component("a", 1.0, 0.5, ""), Component("b", 1.0, 0.5, "")]
    action, score, conf = combine(bullish)
    assert action == "buy" and score == pytest.approx(1.0) and conf <= MAX_CONFIDENCE
    action, _, _ = combine([Component("a", -0.9, 1.0, "")])
    assert action == "sell"
    action, _, conf = combine([Component("a", 0.1, 1.0, ""), Component("b", -0.1, 1.0, "")])
    assert action == "hold"
    assert combine([Component("a", 1.0, 0.0, "")]) == ("hold", 0.0, 0.0)  # zero-weight ML is ignored


def test_compute_analysis_end_to_end_uptrend() -> None:
    result = compute_analysis(make_frame(_random_walk(600, seed=3, drift=0.003)))
    assert result["trend"]["direction"] == "uptrend"
    assert result["signal"]["action"] in {"buy", "hold", "sell"}
    assert any(r["title"] == "Not financial advice" for r in result["risks"])
    names = {c["name"] for c in result["signal"]["components"]}
    assert {"Trend", "RSI", "MACD momentum"} <= names


def test_compute_analysis_requires_history() -> None:
    with pytest.raises(ValidationFailedError):
        compute_analysis(make_frame(_random_walk(30)))


def test_sample_data_is_flagged_as_risk() -> None:
    result = compute_analysis(make_frame(_random_walk(300)), is_sample=True)
    assert any(r["title"] == "Sample data" for r in result["risks"])
