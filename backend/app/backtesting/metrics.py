"""Performance metrics for equity curves and trade lists."""

import math

import numpy as np
import pandas as pd

SECONDS_PER_YEAR = 365 * 24 * 3600  # crypto trades 24/7


def _finite(x: float | None) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return float(x)


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    return float(((equity / peak) - 1).min() * 100)


def sharpe_ratio(returns: pd.Series, periods_per_year: float) -> float | None:
    """Annualized Sharpe (risk-free rate assumed 0)."""
    if len(returns) < 2:
        return None
    std = returns.std(ddof=1)
    if not std or not math.isfinite(std):
        return None
    return _finite(returns.mean() / std * math.sqrt(periods_per_year))


def sortino_ratio(returns: pd.Series, periods_per_year: float) -> float | None:
    if len(returns) < 2:
        return None
    downside = returns.clip(upper=0)
    dd = math.sqrt((downside**2).mean())
    if not dd:
        return None
    return _finite(returns.mean() / dd * math.sqrt(periods_per_year))


def compute_metrics(
    equity: pd.Series,
    *,
    trades: list[dict],
    initial_capital: float,
    timeframe_seconds: int,
    benchmark_start: float,
    benchmark_end: float,
    benchmark_equity: pd.Series | None = None,
) -> dict:
    final = float(equity.iloc[-1])
    returns = equity.pct_change().dropna()
    periods_per_year = SECONDS_PER_YEAR / timeframe_seconds
    years = len(equity) * timeframe_seconds / SECONDS_PER_YEAR

    pnls = np.array([t["pnl"] for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    total_return = (final / initial_capital - 1) * 100
    bars_in_market = sum(t["bars_held"] + 1 for t in trades)

    metrics = {
        "initial_capital": initial_capital,
        "final_equity": final,
        "total_return_pct": total_return,
        "buy_hold_return_pct": (benchmark_end / benchmark_start - 1) * 100 if benchmark_start else 0.0,
        "cagr_pct": _finite(((final / initial_capital) ** (1 / years) - 1) * 100) if years > 0 and final > 0 else None,
        "max_drawdown_pct": max_drawdown_pct(equity),
        "sharpe_ratio": sharpe_ratio(returns, periods_per_year),
        "sortino_ratio": sortino_ratio(returns, periods_per_year),
        "volatility_annual_pct": _finite(returns.std(ddof=1) * math.sqrt(periods_per_year) * 100) if len(returns) > 1 else None,
        "num_trades": len(trades),
        "win_rate": float(len(wins) / len(trades) * 100) if trades else None,
        "profit_factor": _finite(profit_factor) if profit_factor is not None else None,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "avg_trade_return_pct": float(np.mean([t["return_pct"] for t in trades])) if trades else None,
        "best_trade_pct": float(max(t["return_pct"] for t in trades)) if trades else None,
        "worst_trade_pct": float(min(t["return_pct"] for t in trades)) if trades else None,
        "avg_bars_held": float(np.mean([t["bars_held"] for t in trades])) if trades else None,
        "exposure_pct": min(100.0, bars_in_market / len(equity) * 100) if len(equity) else 0.0,
        "total_fees": float(sum(t["entry_fee"] + t["exit_fee"] for t in trades)),
        "bars": len(equity),
        "period_years": years,
    }
    if benchmark_equity is not None:
        metrics.update(benchmark_metrics(returns, benchmark_equity, total_return, initial_capital, periods_per_year))
    return metrics


def benchmark_metrics(
    returns: pd.Series, benchmark: pd.Series, total_return: float, initial_capital: float, periods_per_year: float
) -> dict:
    """Buy-and-hold comparison: the benchmark's own risk/return, plus the strategy's excess return and beta."""
    bench_returns = benchmark.pct_change().dropna()
    bench_total = (float(benchmark.iloc[-1]) / initial_capital - 1) * 100
    beta = correlation = None
    if len(returns) > 2:
        var = bench_returns.var(ddof=1)
        if var and math.isfinite(var):
            beta = _finite(returns.cov(bench_returns, ddof=1) / var)
        if returns.std(ddof=1) and bench_returns.std(ddof=1):
            correlation = _finite(returns.corr(bench_returns))
    return {
        "benchmark": {
            "name": "buy_and_hold",
            "total_return_pct": bench_total,
            "max_drawdown_pct": max_drawdown_pct(benchmark),
            "sharpe_ratio": sharpe_ratio(bench_returns, periods_per_year),
            "volatility_annual_pct": _finite(bench_returns.std(ddof=1) * math.sqrt(periods_per_year) * 100)
            if len(bench_returns) > 1
            else None,
        },
        "excess_return_pct": total_return - bench_total,
        "beta": beta,
        "correlation": correlation,
    }
