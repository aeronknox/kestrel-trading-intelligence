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
