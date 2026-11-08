"""Multi-asset test: one strategy on several assets, capital split equally.

Each asset ("sleeve") gets initial_capital / N and is backtested independently with
the strategy's exact rules, over the time range every asset has data for. Sleeve
equity curves are aligned on the union of their bar times (a sleeve missing a bar,
e.g. during an exchange outage, holds its last value) and summed. The benchmark is
an equal-weight buy-and-hold of the same assets with the same costs.
"""

import itertools
import math

import numpy as np
import pandas as pd

from app.backtesting.engine import BacktestConfig, buy_and_hold_equity, run_backtest
from app.backtesting.metrics import compute_metrics
from app.strategies.definition import StrategyDefinition

MIN_ASSETS = 2
MAX_ASSETS = 6
MIN_COMMON_BARS = 100
SUMMARY_KEYS = ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "num_trades", "win_rate", "profit_factor")


class PortfolioError(ValueError):
    """Invalid multi-asset request (too few assets, no overlapping history)."""


def _aligned(series: list[pd.Series], index: pd.Index, initial: list[float]) -> pd.DataFrame:
    frame = pd.concat(series, axis=1).reindex(index)
    frame = frame.ffill()
    for col, start in zip(frame.columns, initial, strict=True):
        frame[col] = frame[col].fillna(start)  # before a sleeve's first bar it is still all cash
    return frame


def run_portfolio(frames: dict[str, pd.DataFrame], definition: dict, config: BacktestConfig) -> dict:
    if not MIN_ASSETS <= len(frames) <= MAX_ASSETS:
        raise PortfolioError(f"Choose {MIN_ASSETS} to {MAX_ASSETS} assets")
    strategy = StrategyDefinition.model_validate(definition)

    # Common window: from the latest first bar to the earliest last bar.
    start = max(df["ts"].iloc[0] for df in frames.values())
    end = min(df["ts"].iloc[-1] for df in frames.values())
    windowed = {s: df[(df["ts"] >= start) & (df["ts"] <= end)].reset_index(drop=True) for s, df in frames.items()}
    short = [s for s, df in windowed.items() if len(df) < MIN_COMMON_BARS]
    if short:
        raise PortfolioError(
            f"Not enough overlapping history ({', '.join(short)} has fewer than {MIN_COMMON_BARS} bars in the shared window)"
        )

    sleeve_capital = config.initial_capital / len(windowed)
    sleeve_config = BacktestConfig(sleeve_capital, config.fee_bps, config.slippage_bps, config.timeframe_seconds)
    equities: list[pd.Series] = []
    benches: list[pd.Series] = []
    per_asset: list[dict] = []
    all_trades: list[dict] = []
    for symbol, df in windowed.items():
        out = run_backtest(df, strategy, sleeve_config)
        equities.append(out.equity.rename(symbol))
        bh = buy_and_hold_equity(df["open"].to_numpy(float), df["close"].to_numpy(float), sleeve_config)
        benches.append(pd.Series(bh, index=out.equity.index, name=symbol))
        m = out.metrics
        per_asset.append(
            {
                "symbol": symbol,
                "bars": len(df),
                **{k: m.get(k) for k in SUMMARY_KEYS},
                "buy_hold_return_pct": m["benchmark"]["total_return_pct"],
                "final_equity": m["final_equity"],
            }
        )
        all_trades.extend({**t.to_dict(), "symbol": symbol} for t in out.trades)

    index = pd.Index(sorted(set().union(*(e.index for e in equities))))
    sleeves = _aligned(equities, index, [sleeve_capital] * len(equities))
    bench_sleeves = _aligned(benches, index, [sleeve_capital] * len(benches))
    combined = sleeves.sum(axis=1)
    benchmark = bench_sleeves.sum(axis=1)
    all_trades.sort(key=lambda t: t["entry_time"])

    metrics = compute_metrics(
        combined,
        trades=all_trades,
        initial_capital=config.initial_capital,
        timeframe_seconds=config.timeframe_seconds,
        benchmark_start=float(benchmark.iloc[0]),
        benchmark_end=float(benchmark.iloc[-1]),
        benchmark_equity=benchmark,
    )
    # Exposure from trade counts would double-count overlapping sleeves; report the average per sleeve.
    metrics["exposure_pct"] = float(np.mean([_exposure(t, a["bars"]) for a, t in _trades_by_asset(per_asset, all_trades)]))

    # Correlation of the assets' own price moves (the buy-and-hold sleeves). Strategy sleeves
    # sit in cash much of the time; their mostly-zero returns would understate how much the
    # assets move together and overstate diversification.
    returns = bench_sleeves.pct_change().dropna()
    symbols = list(windowed)
    corr = returns.corr() if len(returns) > 2 else pd.DataFrame(np.nan, index=symbols, columns=symbols)
    pairs = [corr.loc[a, b] for a, b in itertools.combinations(symbols, 2)]
    finite_pairs = [float(p) for p in pairs if math.isfinite(p)]
    return {
        "symbols": symbols,
        "window": {"start": int(pd.Timestamp(start).timestamp()), "end": int(pd.Timestamp(end).timestamp())},
        "capital_per_asset": sleeve_capital,
        "per_asset": per_asset,
        "metrics": metrics,
        "correlation": {
            "symbols": symbols,
            "matrix": [[_finite(corr.loc[a, b]) for b in symbols] for a in symbols],
            "average": float(np.mean(finite_pairs)) if finite_pairs else None,
        },
        "equity_curve": _curve(combined, benchmark),
        "trades": all_trades[-2000:],  # most recent; the CSV export is per asset
    }


def _trades_by_asset(per_asset: list[dict], trades: list[dict]) -> list[tuple[dict, list[dict]]]:
    return [(a, [t for t in trades if t["symbol"] == a["symbol"]]) for a in per_asset]


def _exposure(trades: list[dict], bars: int) -> float:
    return min(100.0, sum(t["bars_held"] + 1 for t in trades) / bars * 100) if bars else 0.0


def _finite(x: float) -> float | None:
    return float(x) if math.isfinite(x) else None


def _curve(equity: pd.Series, benchmark: pd.Series, max_points: int = 500) -> list[dict]:
    step = max(1, math.ceil(len(equity) / max_points))
    idx = list(range(0, len(equity), step))
    if idx[-1] != len(equity) - 1:
        idx.append(len(equity) - 1)
    peak = equity.cummax()
    dd = (equity / peak - 1) * 100
    return [
        {
            "time": int(equity.index[i]),
            "equity": float(equity.iloc[i]),
            "drawdown_pct": float(dd.iloc[i]),
            "benchmark": float(benchmark.iloc[i]),
        }
        for i in idx
    ]
