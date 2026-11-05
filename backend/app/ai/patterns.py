"""Rule-based technical pattern detection over closed candles.

Each detector returns plain dictionaries so results are JSON-serializable and
can be stored verbatim with the analysis that produced them.
"""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class Pattern:
    name: str
    bias: str  # bullish | bearish | neutral
    strength: float  # 0..1
    description: str
    time: int | None = None  # unix seconds of the bar where it was detected

    def to_dict(self) -> dict:
        return asdict(self)


def _ts(df: pd.DataFrame, i: int) -> int:
    return int(pd.Timestamp(df["ts"].iloc[i]).timestamp())


def pivots(series: pd.Series, window: int = 5, kind: str = "high") -> list[int]:
    """Indices of confirmed local extrema. A pivot at i requires `window` bars on
    both sides, so the most recent `window` bars can never be pivots (no peeking)."""
    values = series.to_numpy()
    idx: list[int] = []
    for i in range(window, len(values) - window):
        seg = values[i - window : i + window + 1]
        if kind == "high" and values[i] == seg.max() and (seg == values[i]).sum() == 1:
            idx.append(i)
        if kind == "low" and values[i] == seg.min() and (seg == values[i]).sum() == 1:
            idx.append(i)
    return idx


def classify_trend(df: pd.DataFrame, lookback: int = 50) -> dict:
    close = df["close"]
    n = min(lookback, len(df))
    y = np.log(close.iloc[-n:].to_numpy())
    x = np.arange(n)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = float(((y - fitted) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1e-12
    r2 = max(0.0, 1 - ss_res / ss_tot)
    slope_pct = float(slope * 100)  # % per bar (log approx)
    last = df.iloc[-1]
    above_50 = bool(pd.notna(last.get("sma_50")) and last["close"] > last["sma_50"])
    above_200 = bool(pd.notna(last.get("sma_200")) and last["close"] > last["sma_200"])
    total_move_pct = float((np.exp(slope * n) - 1) * 100)
    if abs(total_move_pct) < 2 or r2 < 0.25:
        direction = "sideways"
    else:
        direction = "uptrend" if slope > 0 else "downtrend"
    return {
        "direction": direction,
        "slope_pct_per_bar": slope_pct,
        "regression_move_pct": total_move_pct,
        "r_squared": r2,
        "lookback_bars": n,
        "above_sma_50": above_50,
        "above_sma_200": above_200,
        "strength": float(min(1.0, r2 * min(1.0, abs(total_move_pct) / 10))),
    }


def support_resistance(df: pd.DataFrame, lookback: int = 300, max_levels: int = 3) -> dict:
    sub = df.iloc[-lookback:].reset_index(drop=True)
    price = float(sub["close"].iloc[-1])
    atr_val = sub["atr_14"].iloc[-1] if "atr_14" in sub and pd.notna(sub["atr_14"].iloc[-1]) else price * 0.01
    tol = float(atr_val) * 0.75
    points = [float(sub["high"].iloc[i]) for i in pivots(sub["high"], 4, "high")]
    points += [float(sub["low"].iloc[i]) for i in pivots(sub["low"], 4, "low")]
    points.sort()
    clusters: list[list[float]] = []
    for p in points:
        if clusters and abs(p - np.mean(clusters[-1])) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [{"price": float(np.mean(c)), "touches": len(c)} for c in clusters if len(c) >= 2]
    supports = sorted([lv for lv in levels if lv["price"] < price], key=lambda lv: -lv["price"])[:max_levels]
    resistances = sorted([lv for lv in levels if lv["price"] > price], key=lambda lv: lv["price"])[:max_levels]
    return {"supports": supports, "resistances": resistances}


def _cross(a: pd.Series, b: pd.Series, within: int) -> tuple[str, int] | None:
    diff = (a - b).to_numpy()
    for i in range(len(diff) - 1, max(len(diff) - within - 1, 0), -1):
        if np.isnan(diff[i]) or np.isnan(diff[i - 1]):
            continue
        if diff[i - 1] <= 0 < diff[i]:
            return "up", i
        if diff[i - 1] >= 0 > diff[i]:
            return "down", i
    return None


def detect_patterns(df: pd.DataFrame) -> list[Pattern]:
    out: list[Pattern] = []
    n = len(df)
    if n < 30:
        return out
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Moving-average crosses
    if df["sma_200"].notna().sum() > 2:
        c = _cross(df["sma_50"], df["sma_200"], within=10)
        if c:
            golden = c[0] == "up"
            out.append(
                Pattern(
                    "Golden cross" if golden else "Death cross",
                    "bullish" if golden else "bearish",
                    0.7,
                    f"SMA50 crossed {'above' if golden else 'below'} SMA200 {n - 1 - c[1]} bar(s) ago.",
                    _ts(df, c[1]),
                )
            )
    c = _cross(df["macd"], df["macd_signal"], within=3)
    if c:
        up = c[0] == "up"
        out.append(
            Pattern(
                f"MACD {'bullish' if up else 'bearish'} crossover",
                "bullish" if up else "bearish",
                0.45,
                f"MACD line crossed {'above' if up else 'below'} its signal line {n - 1 - c[1]} bar(s) ago.",
                _ts(df, c[1]),
            )
        )

    # RSI extremes
    r = last["rsi_14"]
    if pd.notna(r):
        if r >= 70:
            out.append(Pattern("RSI overbought", "bearish", min(1.0, (r - 70) / 20 + 0.3), f"RSI(14) is {r:.1f} (≥70).", _ts(df, n - 1)))
        elif r <= 30:
            out.append(Pattern("RSI oversold", "bullish", min(1.0, (30 - r) / 20 + 0.3), f"RSI(14) is {r:.1f} (≤30).", _ts(df, n - 1)))

    # RSI divergence between the last two confirmed pivots
    highs = pivots(df["close"], 5, "high")[-2:]
    lows = pivots(df["close"], 5, "low")[-2:]
    if len(highs) == 2 and n - 1 - highs[-1] <= 30:
        i, j = highs
        if df["close"].iloc[j] > df["close"].iloc[i] and df["rsi_14"].iloc[j] < df["rsi_14"].iloc[i] - 2:
            out.append(Pattern("Bearish RSI divergence", "bearish", 0.5, "Price made a higher high while RSI made a lower high.", _ts(df, j)))
    if len(lows) == 2 and n - 1 - lows[-1] <= 30:
        i, j = lows
        if df["close"].iloc[j] < df["close"].iloc[i] and df["rsi_14"].iloc[j] > df["rsi_14"].iloc[i] + 2:
            out.append(Pattern("Bullish RSI divergence", "bullish", 0.5, "Price made a lower low while RSI made a higher low.", _ts(df, j)))

    # Bollinger squeeze / breakout
    width = df["bb_width"].iloc[-120:].dropna()
    if len(width) > 40 and pd.notna(last["bb_width"]) and last["bb_width"] <= width.quantile(0.1):
        out.append(Pattern("Bollinger squeeze", "neutral", 0.4, "Band width is in the lowest 10% of the last 120 bars — volatility compression often precedes a larger move (direction unknown).", _ts(df, n - 1)))
    if pd.notna(last["bb_upper"]) and last["close"] > last["bb_upper"]:
        out.append(Pattern("Close above upper Bollinger Band", "bullish", 0.35, "Strong upside momentum, but also statistically stretched.", _ts(df, n - 1)))
    elif pd.notna(last["bb_lower"]) and last["close"] < last["bb_lower"]:
        out.append(Pattern("Close below lower Bollinger Band", "bearish", 0.35, "Strong downside momentum, but also statistically stretched.", _ts(df, n - 1)))

    # Candlestick patterns on the last closed bar
    body = abs(last["close"] - last["open"])
    rng = max(last["high"] - last["low"], 1e-12)
    upper_wick = last["high"] - max(last["close"], last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]
    prev_body = abs(prev["close"] - prev["open"])
    if prev["close"] < prev["open"] and last["close"] > last["open"] and last["close"] >= prev["open"] and last["open"] <= prev["close"] and body > prev_body:
        out.append(Pattern("Bullish engulfing", "bullish", 0.4, "The last candle's body fully engulfed the prior bearish candle.", _ts(df, n - 1)))
    elif prev["close"] > prev["open"] and last["close"] < last["open"] and last["open"] >= prev["close"] and last["close"] <= prev["open"] and body > prev_body:
        out.append(Pattern("Bearish engulfing", "bearish", 0.4, "The last candle's body fully engulfed the prior bullish candle.", _ts(df, n - 1)))
    if body / rng < 0.1:
        out.append(Pattern("Doji", "neutral", 0.2, "Open and close are nearly equal — indecision.", _ts(df, n - 1)))
    elif lower_wick > 2 * body and upper_wick < body and last["close"] < df["sma_20"].iloc[-1]:
        out.append(Pattern("Hammer", "bullish", 0.3, "Long lower wick after weakness suggests buyers absorbed selling.", _ts(df, n - 1)))
    elif upper_wick > 2 * body and lower_wick < body and last["close"] > df["sma_20"].iloc[-1]:
        out.append(Pattern("Shooting star", "bearish", 0.3, "Long upper wick after strength suggests sellers rejected higher prices.", _ts(df, n - 1)))

    # Double top / bottom (confirmed by a close beyond the neckline)
    hp = pivots(df["high"], 5, "high")[-2:]
    if len(hp) == 2 and n - 1 - hp[-1] <= 40:
        h1, h2 = df["high"].iloc[hp[0]], df["high"].iloc[hp[1]]
        trough = df["low"].iloc[hp[0] : hp[1] + 1].min()
        if abs(h1 - h2) / h1 < 0.015 and (min(h1, h2) - trough) / min(h1, h2) > 0.03 and last["close"] < trough:
            out.append(Pattern("Double top (confirmed)", "bearish", 0.6, f"Two peaks near {h2:,.2f} with a break below the {trough:,.2f} neckline.", _ts(df, hp[1])))
    lp = pivots(df["low"], 5, "low")[-2:]
    if len(lp) == 2 and n - 1 - lp[-1] <= 40:
        l1, l2 = df["low"].iloc[lp[0]], df["low"].iloc[lp[1]]
        peak = df["high"].iloc[lp[0] : lp[1] + 1].max()
        if abs(l1 - l2) / l1 < 0.015 and (peak - max(l1, l2)) / max(l1, l2) > 0.03 and last["close"] > peak:
            out.append(Pattern("Double bottom (confirmed)", "bullish", 0.6, f"Two troughs near {l2:,.2f} with a break above the {peak:,.2f} neckline.", _ts(df, lp[1])))

    # Volume spike
    vz = last.get("volume_z")
    if pd.notna(vz) and vz > 2:
        direction = "bullish" if last["close"] > last["open"] else "bearish"
        out.append(Pattern("Volume spike", direction, min(1.0, 0.2 + vz / 10), f"Volume is {vz:.1f} standard deviations above its 20-bar average.", _ts(df, n - 1)))

    return out
