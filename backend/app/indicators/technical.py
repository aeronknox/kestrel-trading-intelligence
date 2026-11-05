"""Technical indicators.

Every indicator here is *causal*: the value at bar t uses only bars <= t. That
property is what lets the backtester evaluate rules without look-ahead bias, and
it is asserted in the test-suite.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from app.market_data.providers.base import Candle


def candles_to_frame(candles: Sequence[Candle]) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "ts": [c.ts for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        }
    )
    return df.reset_index(drop=True)


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # No losses in window -> RSI 100; flat -> 50
    out = out.where(~(avg_loss == 0) | (avg_gain == 0), 100.0)
    out = out.where(~((avg_loss == 0) & (avg_gain == 0)), 50.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line})


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid
    pct_b = (close - lower) / (upper - lower)
    return pd.DataFrame({"middle": mid, "upper": upper, "lower": lower, "width": width, "pct_b": pct_b})


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def volume_zscore(volume: pd.Series, period: int = 20) -> pd.Series:
    mean = volume.rolling(period, min_periods=period).mean()
    std = volume.rolling(period, min_periods=period).std(ddof=0)
    z = (volume - mean) / std.replace(0.0, np.nan)
    # No dispersion in the window -> volume is exactly average.
    return z.where(~((std == 0) & mean.notna()), 0.0)


def add_standard_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with the platform's standard indicator columns."""
    out = df.copy()
    close = out["close"]
    out["sma_20"] = sma(close, 20)
    out["sma_50"] = sma(close, 50)
    out["sma_200"] = sma(close, 200)
    out["ema_12"] = ema(close, 12)
    out["ema_26"] = ema(close, 26)
    out["rsi_14"] = rsi(close, 14)
    m = macd(close)
    out["macd"], out["macd_signal"], out["macd_hist"] = m["macd"], m["signal"], m["hist"]
    bb = bollinger(close)
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = bb["upper"], bb["middle"], bb["lower"]
    out["bb_width"], out["bb_pct_b"] = bb["width"], bb["pct_b"]
    out["atr_14"] = atr(out, 14)
    out["volume_sma_20"] = sma(out["volume"], 20)
    out["volume_z"] = volume_zscore(out["volume"], 20)
    out["obv"] = obv(out)
    return out


def _clean(value: float) -> float | None:
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return None
    return float(value)


def series_to_points(df: pd.DataFrame, column: str) -> list[dict]:
    """Serialize a column to [{time, value}] skipping warm-up NaNs (chart friendly)."""
    points = []
    for ts, value in zip(df["ts"], df[column], strict=True):
        v = _clean(value)
        if v is not None:
            points.append({"time": int(pd.Timestamp(ts).timestamp()), "value": v})
    return points


def latest_snapshot(df: pd.DataFrame) -> dict[str, float | None]:
    """Latest value of each standard indicator column."""
    row = df.iloc[-1]
    cols = [
        "close", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "rsi_14", "macd", "macd_signal",
        "macd_hist", "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_pct_b", "atr_14",
        "volume", "volume_sma_20", "volume_z",
    ]  # fmt: skip
    return {c: _clean(row[c]) for c in cols if c in df.columns}
