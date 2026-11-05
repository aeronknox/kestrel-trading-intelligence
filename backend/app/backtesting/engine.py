"""Event-driven, long-only backtesting engine.

Execution model (chosen to avoid look-ahead bias):
  * Rules are evaluated on bar t's *close*. Resulting orders fill at bar t+1's *open*.
  * Stop-loss / take-profit / trailing stops are checked intrabar against bar
    high/low. If the bar gaps through a level, the fill is at the open. If both
    the stop and the target are touched in the same bar, the stop is assumed to
    fill first (conservative — intrabar order is unknown).
  * The trailing-stop reference uses the high-water mark up to the *previous*
    bar, so a bar's own high can't retroactively tighten its stop.
  * Every fill pays `fee_bps` on notional and suffers `slippage_bps` adverse price.
  * Any position still open on the final bar is closed at its close and tagged.

Results are HYPOTHETICAL — they describe how rules would have behaved on past
data and are not a record of actual trading.
"""

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.metrics import compute_metrics
from app.strategies.definition import StrategyDefinition
from app.strategies.evaluator import evaluate_rules, max_warmup


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    timeframe_seconds: int = 3600


@dataclass
class Trade:
    entry_time: int
    entry_price: float
    quantity: float
    entry_fee: float
    exit_time: int | None = None
    exit_price: float | None = None
    exit_fee: float = 0.0
    exit_reason: str = ""
    pnl: float = 0.0
    return_pct: float = 0.0
    bars_held: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestOutput:
    trades: list[Trade]
    equity: pd.Series  # indexed by unix time
    metrics: dict
    warmup_bars: int
    bars: int
    signals: dict = field(default_factory=dict)


def _ts(value: object) -> int:
    return int(pd.Timestamp(value).timestamp())


def run_backtest(df: pd.DataFrame, strategy: StrategyDefinition, config: BacktestConfig) -> BacktestOutput:
    if len(df) < 2:
        raise ValueError("Backtest needs at least 2 bars")
    df = df.reset_index(drop=True)
    cache: dict[str, pd.Series] = {}
    entry_sig = evaluate_rules(df, strategy.entry, cache).to_numpy()
    exit_sig = evaluate_rules(df, strategy.exit, cache).to_numpy()
    risk = strategy.risk

    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    times = [_ts(t) for t in df["ts"]]

    fee = config.fee_bps / 10_000
    slip = config.slippage_bps / 10_000
    cash = config.initial_capital
    qty = 0.0
    trade: Trade | None = None
    entry_bar = 0
    hwm = 0.0
    pending: str | None = None  # "enter" | "exit:<reason>"
    trades: list[Trade] = []
    equity = np.empty(len(df))

    def close_position(i: int, raw_price: float, reason: str) -> None:
        nonlocal cash, qty, trade
        assert trade is not None
        price = raw_price * (1 - slip)
        proceeds = qty * price
        exit_fee = proceeds * fee
        cash += proceeds - exit_fee
        trade.exit_time, trade.exit_price, trade.exit_fee, trade.exit_reason = times[i], price, exit_fee, reason
        cost = trade.quantity * trade.entry_price + trade.entry_fee
        trade.pnl = proceeds - exit_fee - cost
        trade.return_pct = trade.pnl / cost * 100 if cost else 0.0
        trade.bars_held = i - entry_bar
        trades.append(trade)
        qty, trade = 0.0, None

    for i in range(len(df)):
        # 1) Fill orders generated at the previous close, at this bar's open.
        if pending == "enter" and trade is None:
            price = o[i] * (1 + slip)
            budget = cash * risk.position_size_pct / 100
            q = budget / (price * (1 + fee))
            if q > 0 and math.isfinite(q):
                entry_fee = q * price * fee
                cash -= q * price + entry_fee
                qty = q
                trade = Trade(entry_time=times[i], entry_price=price, quantity=q, entry_fee=entry_fee)
                entry_bar = i
                hwm = o[i]
        elif pending and pending.startswith("exit") and trade is not None:
            close_position(i, o[i], pending.split(":", 1)[1])
        pending = None

        # 2) Intrabar protective exits.
        if trade is not None:
            ref = trade.entry_price / (1 + slip)  # pre-slippage reference price
            fixed = ref * (1 - risk.stop_loss_pct / 100) if risk.stop_loss_pct else None
            trail = hwm * (1 - risk.trailing_stop_pct / 100) if risk.trailing_stop_pct else None
            candidates = [(p, r) for p, r in ((fixed, "stop_loss"), (trail, "trailing_stop")) if p is not None]
            stop, stop_reason = max(candidates) if candidates else (None, "")
            target = ref * (1 + risk.take_profit_pct / 100) if risk.take_profit_pct else None
            if stop is not None and lo[i] <= stop:
                close_position(i, min(o[i], stop), stop_reason)
            elif target is not None and h[i] >= target:
                close_position(i, max(o[i], target), "take_profit")
            else:
                hwm = max(hwm, h[i])

        # 3) Evaluate rules on this bar's close -> orders for the next bar.
        if i < len(df) - 1:
            if trade is None and entry_sig[i]:
                pending = "enter"
            elif trade is not None:
                if exit_sig[i]:
                    pending = "exit:signal"
                elif risk.max_bars_in_trade and i - entry_bar + 1 >= risk.max_bars_in_trade:
                    pending = "exit:time_limit"

        equity[i] = cash + qty * c[i]

    if trade is not None:
        close_position(len(df) - 1, c[-1], "end_of_data")
        equity[-1] = cash

    equity_series = pd.Series(equity, index=times)
    metrics = compute_metrics(
        equity_series,
        trades=[t.to_dict() for t in trades],
        initial_capital=config.initial_capital,
        timeframe_seconds=config.timeframe_seconds,
        benchmark_start=float(o[0]),
        benchmark_end=float(c[-1]),
    )
    return BacktestOutput(
        trades=trades,
        equity=equity_series,
        metrics=metrics,
        warmup_bars=max_warmup([strategy.entry, strategy.exit]),
        bars=len(df),
        signals={"entries": int(entry_sig.sum()), "exits": int(exit_sig.sum())},
    )


def downsample_equity(equity: pd.Series, max_points: int = 500) -> list[dict]:
    step = max(1, math.ceil(len(equity) / max_points))
    idx = list(range(0, len(equity), step))
    if idx[-1] != len(equity) - 1:
        idx.append(len(equity) - 1)
    peak = equity.cummax()
    dd = (equity / peak - 1) * 100
    return [
        {"time": int(equity.index[i]), "equity": float(equity.iloc[i]), "drawdown_pct": float(dd.iloc[i])}
        for i in idx
    ]
