"""Evaluates a RuleSet into a boolean Series aligned to the candle frame.

The value at bar t depends only on data up to bar t (all indicators are causal),
so the backtester can act on it at the *next* bar's open without look-ahead.
"""

import numpy as np
import pandas as pd

from app.indicators import technical as ta
from app.strategies.definition import Condition, Operand, RuleSet


def operand_series(df: pd.DataFrame, operand: Operand, cache: dict[str, pd.Series]) -> pd.Series:
    if operand.indicator is None:
        return pd.Series(float(operand.value), index=df.index)
    key = operand.label()
    if key in cache:
        return cache[key]
    p = {k: v for k, v in operand.params.items()}
    name = operand.indicator
    close = df["close"]
    if name in ("close", "open", "high", "low", "volume"):
        s = df[name].astype(float)
    elif name == "sma":
        s = ta.sma(close, int(p["period"]))
    elif name == "ema":
        s = ta.ema(close, int(p["period"]))
    elif name == "rsi":
        s = ta.rsi(close, int(p["period"]))
    elif name == "macd":
        s = ta.macd(close, int(p["fast"]), int(p["slow"]), int(p["signal"]))[operand.field]
    elif name == "bollinger":
        s = ta.bollinger(close, int(p["period"]), p["std"])[operand.field]
    elif name == "atr":
        s = ta.atr(df, int(p["period"]))
    elif name == "volume_sma":
        s = ta.sma(df["volume"], int(p["period"]))
    elif name == "roc":
        s = close.pct_change(int(p["period"])) * 100
    else:  # pragma: no cover - guarded by the Literal type
        raise ValueError(f"Unsupported indicator {name}")
    cache[key] = s
    return s


def condition_series(df: pd.DataFrame, cond: Condition, cache: dict[str, pd.Series]) -> pd.Series:
    a = operand_series(df, cond.left, cache)
    b = operand_series(df, cond.right, cache)
    valid = a.notna() & b.notna()
    if cond.op == ">":
        out = a > b
    elif cond.op == "<":
        out = a < b
    elif cond.op == ">=":
        out = a >= b
    elif cond.op == "<=":
        out = a <= b
    else:
        prev_valid = valid & a.shift(1).notna() & b.shift(1).notna()
        if cond.op == "crosses_above":
            out = (a > b) & (a.shift(1) <= b.shift(1)) & prev_valid
        else:
            out = (a < b) & (a.shift(1) >= b.shift(1)) & prev_valid
    return (out & valid).fillna(False).astype(bool)


def evaluate_rules(df: pd.DataFrame, rules: RuleSet, cache: dict[str, pd.Series] | None = None) -> pd.Series:
    cache = cache if cache is not None else {}
    if not rules.conditions:
        return pd.Series(False, index=df.index)
    stacked = np.column_stack([condition_series(df, c, cache).to_numpy() for c in rules.conditions])
    result = stacked.all(axis=1) if rules.logic == "all" else stacked.any(axis=1)
    return pd.Series(result, index=df.index)


def max_warmup(rules: list[RuleSet]) -> int:
    """Rough number of bars before every referenced indicator is defined."""
    longest = 1
    for rs in rules:
        for c in rs.conditions:
            for o in (c.left, c.right):
                if o.indicator == "macd":
                    longest = max(longest, int(o.params["slow"] + o.params["signal"]))
                elif o.params:
                    longest = max(longest, int(max(o.params.values())))
    return longest + 1
