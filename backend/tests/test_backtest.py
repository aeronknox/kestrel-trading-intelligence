import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import BacktestConfig, run_backtest
from app.backtesting.metrics import max_drawdown_pct
from app.strategies.definition import StrategyDefinition
from tests.conftest import make_frame


def price_cross_strategy(level: float, exit_level: float, **risk) -> StrategyDefinition:  # type: ignore[no-untyped-def]
    return StrategyDefinition.model_validate(
        {
            "entry": {"conditions": [{"left": {"indicator": "close"}, "op": "crosses_above", "right": {"value": level}}]},
            "exit": {"conditions": [{"left": {"indicator": "close"}, "op": "crosses_below", "right": {"value": exit_level}}]},
            "risk": {"position_size_pct": 100, **risk},
        }
    )


NO_COSTS = BacktestConfig(initial_capital=1000, fee_bps=0, slippage_bps=0)


def test_entry_fills_at_next_bar_open() -> None:
    closes = [100, 100, 105, 110, 120, 95, 90]
    df = make_frame(closes)
    out = run_backtest(df, price_cross_strategy(102, 100), NO_COSTS)
    assert len(out.trades) == 1
    t = out.trades[0]
    # Signal on bar 2 (close 105 crosses 102) -> fill at bar 3 open (= bar 2 close = 105).
    assert t.entry_time == int(pd.Timestamp(df["ts"][3]).timestamp())
    assert t.entry_price == pytest.approx(df["open"][3])
    # Exit signal on bar 5 (95 < 100) -> fill at bar 6 open (95).
    assert t.exit_price == pytest.approx(df["open"][6])
    assert t.exit_reason == "signal"
    assert t.pnl == pytest.approx(1000 / 105 * 95 - 1000)


def test_fees_and_slippage_reduce_returns() -> None:
    closes = [100, 100, 105, 110, 120, 95, 90]
    df = make_frame(closes)
    free = run_backtest(df, price_cross_strategy(102, 100), NO_COSTS)
    costly = run_backtest(df, price_cross_strategy(102, 100), BacktestConfig(initial_capital=1000, fee_bps=50, slippage_bps=50))
    assert costly.metrics["final_equity"] < free.metrics["final_equity"]
    t = costly.trades[0]
    assert t.entry_price == pytest.approx(df["open"][3] * 1.005)
    assert t.entry_fee > 0 and t.exit_fee > 0


def test_no_lookahead_future_bars_do_not_change_past_trades() -> None:
    rng = np.random.default_rng(7)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 600))))
    strat = StrategyDefinition.model_validate(
        {
            "entry": {"conditions": [{"left": {"indicator": "ema", "params": {"period": 10}}, "op": "crosses_above", "right": {"indicator": "ema", "params": {"period": 30}}}]},
            "exit": {"conditions": [{"left": {"indicator": "ema", "params": {"period": 10}}, "op": "crosses_below", "right": {"indicator": "ema", "params": {"period": 30}}}]},
        }
    )
    full = run_backtest(make_frame(closes), strat, NO_COSTS)
    # Same history, but bars after 400 replaced by a crash. Trades closed before bar 399 must be identical.
    altered = closes[:400] + [c * 0.5 for c in closes[400:]]
    alt = run_backtest(make_frame(altered), strat, NO_COSTS)
    cutoff = int(pd.Timestamp(make_frame(closes)["ts"][398]).timestamp())
    a = [t.to_dict() for t in full.trades if t.exit_time and t.exit_time <= cutoff]
    b = [t.to_dict() for t in alt.trades if t.exit_time and t.exit_time <= cutoff]
    assert a and a == b


def test_stop_loss_is_conservative_when_bar_gaps() -> None:
    # Enter at 100, then a bar opens at 80 (gap through a 5% stop at 95): fill must be at the open, not the stop.
    closes = [90, 90, 100, 100, 100, 80, 80]
    df = make_frame(closes)
    df.loc[5, "open"] = 80.0
    df.loc[5, "high"] = 81.0
    df.loc[5, "low"] = 79.0
    out = run_backtest(df, price_cross_strategy(95, 10, stop_loss_pct=5), NO_COSTS)
    t = out.trades[0]
    assert t.exit_reason == "stop_loss"
    assert t.exit_price == pytest.approx(80.0)


def test_stop_checked_before_take_profit_in_same_bar() -> None:
    closes = [90, 90, 100, 100, 100, 100]
    df = make_frame(closes)
    df.loc[4, "high"] = 120.0  # touches +10% target
    df.loc[4, "low"] = 90.0  # and -5% stop
    out = run_backtest(df, price_cross_strategy(95, 10, stop_loss_pct=5, take_profit_pct=10), NO_COSTS)
    assert out.trades[0].exit_reason == "stop_loss"


def test_open_position_closed_at_end_of_data() -> None:
    df = make_frame([90, 90, 100, 110, 120])
    out = run_backtest(df, price_cross_strategy(95, 10), NO_COSTS)
    assert out.trades[-1].exit_reason == "end_of_data"
    assert out.metrics["final_equity"] == pytest.approx(out.equity.iloc[-1])


def test_metrics_consistency() -> None:
    rng = np.random.default_rng(11)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 800))))
    strat = StrategyDefinition.model_validate(
        {
            "entry": {"conditions": [{"left": {"indicator": "rsi"}, "op": "crosses_above", "right": {"value": 35}}]},
            "exit": {"conditions": [{"left": {"indicator": "rsi"}, "op": ">", "right": {"value": 65}}]},
            "risk": {"stop_loss_pct": 5},
        }
    )
    out = run_backtest(make_frame(closes), strat, BacktestConfig(initial_capital=10_000))
    m = out.metrics
    assert m["num_trades"] == len(out.trades) > 0
    assert m["final_equity"] == pytest.approx(10_000 + sum(t.pnl for t in out.trades), rel=1e-9)
    assert m["max_drawdown_pct"] <= 0
    assert 0 <= m["win_rate"] <= 100
    if m["profit_factor"] is not None:
        assert m["profit_factor"] == pytest.approx(m["gross_profit"] / m["gross_loss"])


def test_max_drawdown_known_series() -> None:
    assert max_drawdown_pct(pd.Series([100, 120, 90, 130, 65.0])) == pytest.approx(-50.0)


def test_strategy_validation() -> None:
    with pytest.raises(ValueError):
        StrategyDefinition.model_validate({"entry": {"conditions": []}, "exit": {"conditions": []}})
    with pytest.raises(ValueError):  # no exit at all
        StrategyDefinition.model_validate(
            {"entry": {"conditions": [{"left": {"indicator": "close"}, "op": ">", "right": {"value": 1}}]}, "exit": {"conditions": []}}
        )
    with pytest.raises(ValueError):  # bad param range
        StrategyDefinition.model_validate(
            {
                "entry": {"conditions": [{"left": {"indicator": "sma", "params": {"period": 1}}, "op": ">", "right": {"value": 1}}]},
                "exit": {"conditions": []},
                "risk": {"stop_loss_pct": 5},
            }
        )
