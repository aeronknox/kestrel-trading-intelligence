"""Monte Carlo resampling of a finished backtest's own trades: how much did the order of wins and losses
(luck) shape its return and drawdown?

Each trade's P&L is turned into a fraction of the equity it was taken with (replaying the trades in their
real order from the initial capital). Each run then draws that many trades at random, with replacement,
and compounds them. Nothing new is invented: every run is made of the backtest's real trade results.
Drawdowns are measured from trade to trade (closed-trade equity), so dips while a trade was open aren't
included. The random generator is seeded, so the same backtest always gives the same answer.
"""

from dataclasses import dataclass

import numpy as np

MIN_TRADES = 5
PERCENTILES = (5, 25, 50, 75, 95)


@dataclass
class MonteCarlo:
    runs: int
    trades: int
    actual_return_pct: float
    actual_max_drawdown_pct: float
    return_pct: dict[int, float]  # percentile -> final return %
    max_drawdown_pct: dict[int, float]  # percentile -> worst drawdown % (positive numbers; higher is worse)
    loss_probability_pct: float  # share of runs that end below the initial capital
    drawdown_worse_than_actual_pct: float  # share of runs with a deeper drawdown than the real order had


def trade_fractions(initial_capital: float, pnls: list[float]) -> np.ndarray:
    """Each trade's P&L as a fraction of the equity just before it, in the order they happened."""
    equity = initial_capital
    out = []
    for pnl in pnls:
        out.append(pnl / equity if equity > 0 else 0.0)
        equity += pnl
    return np.array(out, dtype=float)


def _paths(fractions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Final return % and max drawdown % for each row of per-trade fractions (closed-trade equity)."""
    growth = np.cumprod(1.0 + fractions, axis=-1)
    with_start = np.concatenate([np.ones((*growth.shape[:-1], 1)), growth], axis=-1)
    peaks = np.maximum.accumulate(with_start, axis=-1)
    drawdown = (1.0 - with_start / peaks).max(axis=-1) * 100
    return (with_start[..., -1] - 1.0) * 100, drawdown


def monte_carlo(initial_capital: float, pnls: list[float], runs: int = 1000, seed: int = 0) -> MonteCarlo:
    if len(pnls) < MIN_TRADES:
        raise ValueError(f"Needs at least {MIN_TRADES} closed trades; this backtest has {len(pnls)}")
    fractions = trade_fractions(initial_capital, pnls)
    fractions = np.clip(fractions, -1.0, None)  # a trade can't lose more than everything
    actual_ret, actual_dd = _paths(fractions)
    rng = np.random.default_rng(seed)
    sample = fractions[rng.integers(0, len(fractions), size=(runs, len(fractions)))]
    rets, dds = _paths(sample)
    return MonteCarlo(
        runs=runs,
        trades=len(pnls),
        actual_return_pct=float(actual_ret),
        actual_max_drawdown_pct=float(actual_dd),
        return_pct={p: float(np.percentile(rets, p)) for p in PERCENTILES},
        max_drawdown_pct={p: float(np.percentile(dds, p)) for p in PERCENTILES},
        loss_probability_pct=float((rets < 0).mean() * 100),
        drawdown_worse_than_actual_pct=float((dds > actual_dd + 1e-9).mean() * 100),
    )
