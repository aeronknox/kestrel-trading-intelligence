"""Parameter sweeps and walk-forward analysis.

A sweep runs one strategy over a grid of parameter values on the same data and
reports every result, so you can see whether good performance is a broad plateau
or a single lucky cell.

Walk-forward analysis guards against overfitting by never scoring settings on the
data used to choose them. The history is cut into consecutive windows; in each
one the best grid settings are picked on an in-sample (IS) segment, then traded on
the following out-of-sample (OOS) segment. Only the OOS segments are stitched
into the reported equity curve:

    |--- IS 1 ---|- OOS 1 -|
              |--- IS 2 ---|- OOS 2 -|
                        |--- IS 3 ---|- OOS 3 -|

Every run sees only bars up to the end of its own segment (the frame is sliced),
and bars before a segment only warm up indicators.
"""

import copy
import itertools
import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import ValidationError

from app.backtesting.engine import BacktestConfig, BacktestOutput, buy_and_hold_equity, run_backtest
from app.backtesting.metrics import compute_metrics
from app.strategies.definition import INDICATOR_PARAMS, StrategyDefinition

Objective = Literal["sharpe_ratio", "total_return_pct", "return_over_drawdown"]

MAX_PARAMS = 2
MAX_VALUES_PER_PARAM = 12
MAX_COMBINATIONS = 100
MIN_OOS_BARS = 30

RISK_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "position_size_pct": (1, 100, False),
    "stop_loss_pct": (0.1, 90, False),
    "take_profit_pct": (0.1, 1000, False),
    "trailing_stop_pct": (0.1, 90, False),
    "max_bars_in_trade": (1, 10000, True),
}
INTEGER_PARAMS = {"period", "fast", "slow", "signal"}
SUMMARY_KEYS = ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "num_trades", "win_rate", "profit_factor")


class OptimizationError(ValueError):
    """Invalid sweep or walk-forward request (bad path, grid too large, too little data)."""


@dataclass
class ParamGrid:
    path: str
    values: list[float]


# ----------------------------------------------------------------- parameters
def tunable_parameters(definition: dict) -> list[dict]:
    """Every numeric setting in a strategy that a sweep can vary, with its bounds."""
    out: list[dict] = []
    defn = StrategyDefinition.model_validate(definition)
    for section in ("entry", "exit"):
        for i, cond in enumerate(getattr(defn, section).conditions):
            where = f"{section.capitalize()} #{i + 1} ({cond.label()})"
            for side in ("left", "right"):
                operand = getattr(cond, side)
                base = f"{section}.conditions.{i}.{side}"
                if operand.indicator is None:
                    out.append({"path": f"{base}.value", "label": f"{where}: threshold", "current": operand.value,
                                "min": None, "max": None, "integer": False})  # fmt: skip
                    continue
                for name, (_, lo, hi) in INDICATOR_PARAMS[operand.indicator].items():
                    out.append({"path": f"{base}.params.{name}", "label": f"{where}: {operand.indicator.upper()} {name}",
                                "current": operand.params[name], "min": lo, "max": hi, "integer": name in INTEGER_PARAMS})  # fmt: skip
    for name, (lo, hi, integer) in RISK_BOUNDS.items():
        out.append({"path": f"risk.{name}", "label": f"Risk: {name.replace('_', ' ')}",
                    "current": getattr(defn.risk, name), "min": lo, "max": hi, "integer": integer})  # fmt: skip
    return out


def apply_params(definition: dict, values: dict[str, float]) -> StrategyDefinition | None:
    """A copy of `definition` with each path set; None if the result is not a valid strategy."""
    d = copy.deepcopy(definition)
    for path, value in values.items():
        node: object = d
        keys = path.split(".")
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node.setdefault(key, {})  # type: ignore[index,union-attr]
        node[keys[-1]] = value  # type: ignore[index]
    try:
        return StrategyDefinition.model_validate(d)
    except ValidationError:
        return None  # e.g. MACD fast >= slow for this combination


def validate_grid(definition: dict, grid: list[ParamGrid]) -> None:
    if not 1 <= len(grid) <= MAX_PARAMS:
        raise OptimizationError(f"Choose 1 to {MAX_PARAMS} parameters")
    known = {p["path"]: p for p in tunable_parameters(definition)}
    if len({g.path for g in grid}) != len(grid):
        raise OptimizationError("Each parameter can only be swept once")
    total = 1
    for g in grid:
        spec = known.get(g.path)
        if spec is None:
            raise OptimizationError(f"Unknown parameter: {g.path}")
        if not 2 <= len(g.values) <= MAX_VALUES_PER_PARAM:
            raise OptimizationError(f"Give 2 to {MAX_VALUES_PER_PARAM} values for {spec['label']}")
        if len(set(g.values)) != len(g.values):
            raise OptimizationError(f"Duplicate values for {spec['label']}")
        for v in g.values:
            if not math.isfinite(v):
                raise OptimizationError("Values must be finite numbers")
            if spec["min"] is not None and not spec["min"] <= v <= spec["max"]:
                raise OptimizationError(f"{spec['label']} must be between {spec['min']:g} and {spec['max']:g}")
        total *= len(g.values)
    if total > MAX_COMBINATIONS:
        raise OptimizationError(f"{total} combinations; the limit is {MAX_COMBINATIONS}")


def _param_meta(definition: dict, grid: list[ParamGrid]) -> list[dict]:
    """Paths, labels and values, stored with results so they stay readable after the strategy is edited."""
    labels = {p["path"]: p["label"] for p in tunable_parameters(definition)}
    return [{"path": g.path, "label": labels[g.path], "values": g.values} for g in grid]


def _combinations(grid: list[ParamGrid]) -> list[tuple[float, ...]]:
    return list(itertools.product(*(g.values for g in grid)))


# ------------------------------------------------------------------- scoring
def score(metrics: dict, objective: Objective, min_trades: int) -> float | None:
    """Objective value, or None when a run has too few trades to judge."""
    if metrics["num_trades"] < min_trades:
        return None
    if objective == "sharpe_ratio":
        return metrics["sharpe_ratio"]
    if objective == "total_return_pct":
        return metrics["total_return_pct"]
    dd = abs(metrics["max_drawdown_pct"])
    return metrics["total_return_pct"] / max(dd, 1.0)


def _summary(metrics: dict) -> dict:
    return {k: metrics.get(k) for k in SUMMARY_KEYS}


def _best(scores: list[float | None]) -> int | None:
    ranked = [(s, i) for i, s in enumerate(scores) if s is not None]
    return max(ranked)[1] if ranked else None


# --------------------------------------------------------------------- sweep
def run_sweep(
    df: pd.DataFrame,
    definition: dict,
    grid: list[ParamGrid],
    config: BacktestConfig,
    *,
    objective: Objective = "sharpe_ratio",
    min_trades: int = 3,
) -> dict:
    validate_grid(definition, grid)
    cache: dict[str, pd.Series] = {}
    cells: list[dict] = []
    for combo in _combinations(grid):
        strategy = apply_params(definition, {g.path: v for g, v in zip(grid, combo, strict=True)})
        if strategy is None:
            cells.append({"values": list(combo), "valid": False, "metrics": None, "score": None})
            continue
        m = run_backtest(df, strategy, config, cache=cache).metrics
        cells.append({"values": list(combo), "valid": True, "metrics": _summary(m), "score": score(m, objective, min_trades)})

    baseline = run_backtest(df, StrategyDefinition.model_validate(definition), config, cache=cache).metrics
    best = _best([c["score"] for c in cells])
    valid = [c for c in cells if c["valid"]]
    return {
        "objective": objective,
        "min_trades": min_trades,
        "params": _param_meta(definition, grid),
        "cells": cells,
        "best_index": best,
        "baseline": _summary(baseline),
        "buy_hold_return_pct": baseline["benchmark"]["total_return_pct"],
        "robustness": {
            "valid_cells": len(valid),
            "profitable_share_pct": sum(c["metrics"]["total_return_pct"] > 0 for c in valid) / len(valid) * 100 if valid else None,
            "best_neighbors_mean_score": _neighbors_mean(cells, grid, best),
        },
    }


def _neighbors_mean(cells: list[dict], grid: list[ParamGrid], best: int | None) -> float | None:
    """Mean score of the cells adjacent to the best one: low values mean an isolated spike."""
    if best is None:
        return None
    shape = [len(g.values) for g in grid]
    best_pos = np.unravel_index(best, shape)
    scores = []
    for i, cell in enumerate(cells):
        pos = np.unravel_index(i, shape)
        if i != best and all(abs(a - b) <= 1 for a, b in zip(pos, best_pos, strict=True)) and cell["score"] is not None:
            scores.append(cell["score"])
    return float(np.mean(scores)) if scores else None


# -------------------------------------------------------------- walk-forward
def walk_forward_windows(n_bars: int, folds: int, is_ratio: float) -> list[tuple[int, int, int]]:
    """(is_start, oos_start, oos_end) per fold; IS segments are `is_ratio` times as long as OOS ones."""
    oos_len = int(n_bars // (is_ratio + folds))
    if oos_len < MIN_OOS_BARS:
        raise OptimizationError(
            f"{n_bars} bars is too few for {folds} folds at {is_ratio:g}:1; each test window needs {MIN_OOS_BARS}+ bars"
        )
    is_len = int(oos_len * is_ratio)
    return [(i * oos_len, i * oos_len + is_len, i * oos_len + is_len + oos_len) for i in range(folds)]


def run_walk_forward(
    df: pd.DataFrame,
    definition: dict,
    grid: list[ParamGrid],
    config: BacktestConfig,
    *,
    folds: int = 4,
    is_ratio: float = 3.0,
    objective: Objective = "sharpe_ratio",
    min_trades: int = 3,
) -> dict:
    validate_grid(definition, grid)
    df = df.reset_index(drop=True)
    windows = walk_forward_windows(len(df), folds, is_ratio)
    combos = _combinations(grid)
    strategies = [apply_params(definition, {g.path: v for g, v in zip(grid, c, strict=True)}) for c in combos]
    original = StrategyDefinition.model_validate(definition)
    caches: dict[int, dict[str, pd.Series]] = {}  # one indicator cache per frame length

    def run(strategy: StrategyDefinition, start: int, end: int, capital: float) -> BacktestOutput:
        frame = df.iloc[:end]  # never expose bars after this segment
        cfg = BacktestConfig(capital, config.fee_bps, config.slippage_bps, config.timeframe_seconds)
        return run_backtest(frame, strategy, cfg, start=start, cache=caches.setdefault(end, {}))

    fold_rows: list[dict] = []
    oos_parts: list[pd.Series] = []
    base_parts: list[pd.Series] = []
    oos_trades: list[dict] = []
    capital = base_capital = config.initial_capital
    for n, (is_start, oos_start, oos_end) in enumerate(windows):
        is_scores: list[float | None] = []
        is_metrics: list[dict | None] = []
        for strategy in strategies:
            if strategy is None:
                is_scores.append(None)
                is_metrics.append(None)
                continue
            m = run(strategy, is_start, oos_start, config.initial_capital).metrics
            is_scores.append(score(m, objective, min_trades))
            is_metrics.append(m)
        best = _best(is_scores)
        chosen = strategies[best] if best is not None else original  # nothing qualified: keep the original
        oos = run(chosen, oos_start, oos_end, capital)
        base = run(original, oos_start, oos_end, base_capital)
        capital, base_capital = float(oos.equity.iloc[-1]), float(base.equity.iloc[-1])
        oos_parts.append(oos.equity)
        base_parts.append(base.equity)
        oos_trades.extend(t.to_dict() for t in oos.trades)
        is_m = is_metrics[best] if best is not None else run(original, is_start, oos_start, config.initial_capital).metrics
        fold_rows.append(
            {
                "fold": n + 1,
                "in_sample": {"start": int(df["ts"].iloc[is_start].timestamp()), "end": int(df["ts"].iloc[oos_start - 1].timestamp()),
                              "bars": oos_start - is_start},  # fmt: skip
                "out_of_sample": {"start": int(df["ts"].iloc[oos_start].timestamp()), "end": int(df["ts"].iloc[oos_end - 1].timestamp()),
                                  "bars": oos_end - oos_start},  # fmt: skip
                "chosen": dict(zip((g.path for g in grid), combos[best], strict=True)) if best is not None else None,
                "is_score": is_scores[best] if best is not None else None,
                "is_metrics": _summary(is_m),
                "oos_metrics": _summary(oos.metrics),
                "oos_score": score(oos.metrics, objective, 0),
                "baseline_oos_return_pct": base.metrics["total_return_pct"],
            }
        )

    first, last = windows[0][1], windows[-1][2]
    o, c = df["open"].to_numpy(float), df["close"].to_numpy(float)
    oos_equity = pd.concat(oos_parts)
    base_equity = pd.concat(base_parts)
    bench_equity = pd.Series(buy_and_hold_equity(o[first:last], c[first:last], config), index=oos_equity.index)
    oos_metrics = compute_metrics(
        oos_equity,
        trades=oos_trades,
        initial_capital=config.initial_capital,
        timeframe_seconds=config.timeframe_seconds,
        benchmark_start=float(o[first]),
        benchmark_end=float(c[last - 1]),
        benchmark_equity=bench_equity,
    )
    base_return = (float(base_equity.iloc[-1]) / config.initial_capital - 1) * 100
    efficiency = _efficiency(fold_rows)
    return {
        "objective": objective,
        "min_trades": min_trades,
        "folds": folds,
        "is_ratio": is_ratio,
        "params": _param_meta(definition, grid),
        "fold_results": fold_rows,
        "oos_metrics": oos_metrics,
        "baseline_oos_return_pct": base_return,
        "efficiency": efficiency,
        "distinct_choices": len({tuple(sorted(f["chosen"].items())) for f in fold_rows if f["chosen"]}),
        "verdict": _verdict(fold_rows, oos_metrics, efficiency, base_return),
        "equity_curve": _curve(oos_equity, base_equity, bench_equity),
    }


def _efficiency(folds: list[dict]) -> float | None:
    """Walk-forward efficiency: mean OOS return per bar ÷ mean IS return per bar."""
    is_rate = np.mean([f["is_metrics"]["total_return_pct"] / f["in_sample"]["bars"] for f in folds])
    oos_rate = np.mean([f["oos_metrics"]["total_return_pct"] / f["out_of_sample"]["bars"] for f in folds])
    if is_rate <= 0:
        return None  # undefined when the tuned settings lost money even in-sample
    return float(oos_rate / is_rate)


def _verdict(folds: list[dict], oos: dict, efficiency: float | None, base_return: float) -> dict:
    """Rule-based reading of the result. Deterministic; no model is asked to interpret numbers."""
    notes: list[str] = []
    is_mean = float(np.mean([f["is_metrics"]["total_return_pct"] for f in folds]))
    if oos["num_trades"] < 5:
        level, headline = "inconclusive", "Too few out-of-sample trades to judge."
    elif is_mean > 0 and oos["total_return_pct"] <= 0:
        level, headline = "overfit", "Settings that won in-sample lost money on unseen data: likely overfit."
    elif efficiency is not None and efficiency >= 0.5:
        level, headline = "robust", "Out-of-sample results kept at least half of the in-sample performance."
    elif oos["total_return_pct"] > 0:
        level, headline = "weak", "Profitable out of sample, but far below what the in-sample results suggested."
    else:
        level, headline = "unprofitable", "The strategy lost money both in-sample and out of sample."
    bench = oos["benchmark"]["total_return_pct"]
    notes.append(
        f"Out of sample it returned {oos['total_return_pct']:+.2f}% versus {bench:+.2f}% for buy and hold"
        f" and {base_return:+.2f}% for the untuned strategy."
    )
    changed = len({tuple(sorted(f["chosen"].items())) for f in folds if f["chosen"]})
    if changed > 1:
        notes.append(f"The best settings changed between folds ({changed} different choices), so they are not stable.")
    skipped = sum(f["chosen"] is None for f in folds)
    if skipped:
        notes.append(f"In {skipped} fold(s) no setting reached the minimum trade count; the original settings were used.")
    return {"level": level, "headline": headline, "notes": notes}


def _curve(equity: pd.Series, baseline: pd.Series, benchmark: pd.Series, max_points: int = 500) -> list[dict]:
    step = max(1, math.ceil(len(equity) / max_points))
    idx = list(range(0, len(equity), step))
    if idx[-1] != len(equity) - 1:
        idx.append(len(equity) - 1)
    return [
        {"time": int(equity.index[i]), "equity": float(equity.iloc[i]), "baseline": float(baseline.iloc[i]),
         "benchmark": float(benchmark.iloc[i])}  # fmt: skip
        for i in idx
    ]
