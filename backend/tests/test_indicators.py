import numpy as np
import pandas as pd
import pytest

from app.indicators import technical as ta
from tests.conftest import make_frame


def test_sma_matches_manual() -> None:
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = ta.sma(s, 3)
    assert out.isna().sum() == 2
    assert out.iloc[-1] == pytest.approx(4.0)


def test_ema_warmup_and_value() -> None:
    s = pd.Series([10.0] * 30)
    out = ta.ema(s, 10)
    assert out.iloc[:9].isna().all()
    assert out.iloc[-1] == pytest.approx(10.0)


def test_rsi_extremes() -> None:
    up = pd.Series(np.arange(1, 50, dtype=float))
    down = pd.Series(np.arange(50, 1, -1, dtype=float))
    flat = pd.Series([5.0] * 40)
    assert ta.rsi(up).iloc[-1] == pytest.approx(100.0)
    assert ta.rsi(down).iloc[-1] == pytest.approx(0.0)
    assert ta.rsi(flat).iloc[-1] == pytest.approx(50.0)


def test_rsi_bounded_on_random_walk() -> None:
    rng = np.random.default_rng(0)
    s = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500))))
    r = ta.rsi(s).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_bollinger_contains_middle() -> None:
    rng = np.random.default_rng(1)
    s = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
    bb = ta.bollinger(s).dropna()
    assert (bb["upper"] >= bb["middle"]).all() and (bb["middle"] >= bb["lower"]).all()


def test_macd_hist_is_difference() -> None:
    rng = np.random.default_rng(2)
    s = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
    m = ta.macd(s).dropna()
    np.testing.assert_allclose(m["hist"], m["macd"] - m["signal"])


def test_indicators_are_causal() -> None:
    """Values up to bar t must not change when future bars are appended."""
    rng = np.random.default_rng(3)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))))
    full = ta.add_standard_indicators(make_frame(closes))
    truncated = ta.add_standard_indicators(make_frame(closes[:300]))
    cols = [c for c in truncated.columns if c not in ("ts",)]
    pd.testing.assert_frame_equal(full.iloc[:300][cols].reset_index(drop=True), truncated[cols], check_exact=False, rtol=1e-9)


# Reference: Wilder RSI(14) worked example published by StockCharts ("RSI" ChartSchool).
RSI_CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
              46.28, 46.00, 46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45, 45.78, 45.35, 44.03, 44.18,
              44.22, 44.57, 43.42, 42.66, 43.13]  # fmt: skip
RSI_EXPECTED = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
                41.87, 45.46, 37.30, 33.08, 37.77]  # fmt: skip


def test_rsi_matches_wilder_reference() -> None:
    out = ta.rsi(pd.Series(RSI_CLOSES)).tolist()
    assert all(np.isnan(v) for v in out[:14])
    # The published worksheet rounds intermediate averages, hence the small tolerance.
    np.testing.assert_allclose(out[14:], RSI_EXPECTED, atol=0.1)


def _wilder_rsi_loop(closes: np.ndarray, n: int = 14) -> np.ndarray:
    """Straight transcription of Wilder (1978), used as an independent oracle."""
    d = np.diff(closes)
    g, losses = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = g[:n].mean(), losses[:n].mean()
    out = [np.nan] * n + [100 - 100 / (1 + ag / al)]
    for i in range(n, len(d)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + losses[i]) / n
        out.append(100 - 100 / (1 + ag / al))
    return np.array(out)


def test_rsi_exactly_matches_independent_wilder_implementation() -> None:
    rng = np.random.default_rng(42)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    np.testing.assert_allclose(ta.rsi(pd.Series(closes)).to_numpy(), _wilder_rsi_loop(closes), rtol=1e-10, equal_nan=True)


def test_ema_is_sma_seeded() -> None:
    s = pd.Series([22.27, 22.19, 22.08, 22.17, 22.18, 22.13, 22.23, 22.43, 22.24, 22.29, 22.15, 22.39, 22.38])
    out = ta.ema(s, 10)
    assert out.iloc[:9].isna().all()
    assert out.iloc[9] == pytest.approx(s.iloc[:10].mean())
    k = 2 / 11
    assert out.iloc[10] == pytest.approx(s.iloc[10] * k + out.iloc[9] * (1 - k))
    # StockCharts EMA(10) example values for these closes
    np.testing.assert_allclose(out.iloc[9:].to_numpy(), [22.22, 22.21, 22.24, 22.27], atol=0.01)


def test_macd_signal_waits_for_full_warmup() -> None:
    s = pd.Series(np.linspace(100, 130, 60))
    m = ta.macd(s)
    assert m["macd"].first_valid_index() == 25  # slow EMA(26) seed
    assert m["signal"].first_valid_index() == 25 + 8  # then EMA(9) of the MACD line


def test_columns_to_points_skips_warmup_and_uses_unix_seconds() -> None:
    df = pd.DataFrame(
        {"ts": pd.to_datetime([0, 3600, 7200], unit="s", utc=True), "a": [np.nan, 1.5, np.inf], "b": [1, 2, 3]}
    )
    out = ta.columns_to_points(df, ["a", "b"])
    assert out["a"] == [{"time": 3600, "value": 1.5}]  # NaN warm-up and inf are dropped
    assert out["b"] == [{"time": 0, "value": 1.0}, {"time": 3600, "value": 2.0}, {"time": 7200, "value": 3.0}]
    assert all(type(p["time"]) is int and type(p["value"]) is float for p in out["b"])  # plain JSON types
    assert ta.series_to_points(df, "a") == out["a"]
