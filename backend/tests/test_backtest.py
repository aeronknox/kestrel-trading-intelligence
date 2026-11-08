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


def test_buy_and_hold_benchmark_without_costs() -> None:
    closes = [100, 100, 105, 110, 120, 95, 90, 130]
    df = make_frame(closes)
    out = run_backtest(df, price_cross_strategy(102, 100), NO_COSTS)
    m = out.metrics
    assert out.benchmark.iloc[-1] == pytest.approx(1000 * 130 / df["open"][0])
    assert m["benchmark"]["total_return_pct"] == pytest.approx(m["buy_hold_return_pct"])
    assert m["excess_return_pct"] == pytest.approx(m["total_return_pct"] - m["benchmark"]["total_return_pct"])
    assert m["benchmark"]["max_drawdown_pct"] == pytest.approx(max_drawdown_pct(out.benchmark))


def test_benchmark_pays_the_same_costs() -> None:
    df = make_frame([100, 100, 105, 110, 120, 95, 90, 130])
    out = run_backtest(df, price_cross_strategy(102, 100), BacktestConfig(initial_capital=1000, fee_bps=50, slippage_bps=50))
    expected = 1000 / (100 * 1.005 * 1.005) * 130 * 0.995 * 0.995
    assert out.benchmark.iloc[-1] == pytest.approx(expected)
    assert out.metrics["benchmark"]["total_return_pct"] < out.metrics["buy_hold_return_pct"]


def test_flat_strategy_has_zero_beta_and_full_benchmark_in_curve() -> None:
    from app.backtesting.engine import downsample_equity

    df = make_frame(list(np.linspace(100, 150, 50)))
    out = run_backtest(df, price_cross_strategy(10_000, 0), NO_COSTS)  # never enters
    assert out.trades == []
    assert out.metrics["beta"] == pytest.approx(0.0)
    assert out.metrics["correlation"] is None  # undefined for a constant equity curve
    points = downsample_equity(out.equity, max_points=10, benchmark=out.benchmark)
    assert points[-1]["benchmark"] == pytest.approx(out.benchmark.iloc[-1])
    assert all("benchmark" in p for p in points)


def test_fully_invested_strategy_tracks_benchmark() -> None:
    df = make_frame(list(100 + 10 * np.sin(np.linspace(0, 6, 80)) + np.linspace(0, 20, 80)))
    always_in = StrategyDefinition.model_validate(
        {
            "entry": {"conditions": [{"left": {"indicator": "close"}, "op": ">", "right": {"value": 0}}]},
            "exit": {"conditions": [{"left": {"indicator": "close"}, "op": "<", "right": {"value": 0}}]},
            "risk": {"position_size_pct": 100},
        }
    )
    m = run_backtest(df, always_in, NO_COSTS).metrics
    assert m["beta"] == pytest.approx(1.0, abs=0.05)
    assert m["correlation"] == pytest.approx(1.0, abs=0.05)


# ---------------------------------------------------------------- short side
def short_strategy(entry_below: float, exit_above: float, **risk) -> StrategyDefinition:  # type: ignore[no-untyped-def]
    return StrategyDefinition.model_validate(
        {
            "entry": {"conditions": [{"left": {"indicator": "close"}, "op": "crosses_below", "right": {"value": entry_below}}]},
            "exit": {"conditions": [{"left": {"indicator": "close"}, "op": "crosses_above", "right": {"value": exit_above}}]},
            "risk": {"position_size_pct": 100, "direction": "short", **risk},
        }
    )


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Explicit (open, high, low, close) bars, hourly."""
    start = pd.Timestamp("2024-01-01", tz="UTC")
    return pd.DataFrame(
        {
            "ts": [start + pd.Timedelta(hours=i) for i in range(len(rows))],
            "open": [r[0] for r in rows], "high": [r[1] for r in rows],
            "low": [r[2] for r in rows], "close": [r[3] for r in rows],
            "volume": [100.0] * len(rows),
        }
    )  # fmt: skip


def test_short_profits_when_price_falls() -> None:
    df = make_frame([100, 100, 95, 90, 80, 85, 90, 88])
    out = run_backtest(df, short_strategy(96, 82), NO_COSTS)
    assert len(out.trades) == 1
    t = out.trades[0]
    assert t.side == "short"
    # Signal on bar 2 (95 crosses below 96) -> sell at bar 3 open (95); exit signal on bar 5 (85) -> buy at bar 6 open (85).
    assert t.entry_price == pytest.approx(95) and t.exit_price == pytest.approx(85)
    assert t.pnl == pytest.approx(1000 / 95 * (95 - 85))
    # Marked to market while open: worth collateral + (entry - price) per unit.
    bar4 = int(pd.Timestamp(df["ts"][4]).timestamp())
    assert out.equity[bar4] == pytest.approx(1000 / 95 * (2 * 95 - 80))
    assert out.metrics["final_equity"] == pytest.approx(1000 + t.pnl)


def test_short_stop_loss_sits_above_entry_and_respects_gaps() -> None:
    rows = [(100, 101, 99, 100), (100, 101, 98, 98), (98, 99, 97, 98), (98, 102.5, 97, 101), (101, 101, 100, 100)]
    out = run_backtest(bars(rows), short_strategy(99, 1000, stop_loss_pct=4), NO_COSTS)
    t = out.trades[0]
    assert t.entry_price == pytest.approx(98)  # signal at bar 1 close, filled at bar 2 open
    assert t.exit_reason == "stop_loss" and t.exit_price == pytest.approx(98 * 1.04)  # high 102.5 touched 101.92
    gap = [(100, 101, 99, 100), (100, 101, 98, 98), (98, 99, 97, 98), (105, 106, 104, 105), (105, 105, 104, 104)]
    g = run_backtest(bars(gap), short_strategy(99, 1000, stop_loss_pct=4), NO_COSTS).trades[0]
    assert g.exit_reason == "stop_loss" and g.exit_price == pytest.approx(105)  # gapped through the stop: filled at the open


def test_short_take_profit_below_and_trailing_stop_follows_the_low() -> None:
    rows = [(100, 101, 99, 100), (100, 101, 98, 98), (98, 99, 97, 97), (97, 97, 87, 88), (88, 89, 87, 88)]
    tp = run_backtest(bars(rows), short_strategy(99, 1000, take_profit_pct=10), NO_COSTS).trades[0]
    assert tp.exit_reason == "take_profit" and tp.exit_price == pytest.approx(98 * 0.9)

    trail_rows = [(100, 101, 99, 100), (100, 101, 98, 98), (98, 98, 90, 91), (91, 92, 85, 86), (86, 92, 86, 91), (91, 91, 90, 90)]
    tr = run_backtest(bars(trail_rows), short_strategy(99, 1000, trailing_stop_pct=5), NO_COSTS).trades[0]
    # Low-water mark after bar 3 is 85, so the stop is 89.25; bar 4's high of 92 hits it.
    assert tr.exit_reason == "trailing_stop" and tr.exit_price == pytest.approx(85 * 1.05)


def test_short_is_liquidated_when_price_doubles() -> None:
    rows = [(100, 101, 99, 100), (100, 101, 98, 98), (98, 99, 97, 98), (98, 150, 97, 150), (150, 210, 150, 205), (205, 205, 50, 60), (60, 61, 40, 45)]
    out = run_backtest(bars(rows), short_strategy(99, 1000), NO_COSTS)
    t = out.trades[0]
    assert t.exit_reason == "margin_call" and t.exit_price == pytest.approx(196)  # twice the 98 entry
    assert t.pnl == pytest.approx(-1000)  # the whole posted collateral, no more
    assert out.metrics["final_equity"] == pytest.approx(0)
    assert len(out.trades) == 1  # nothing left to trade with afterwards


def test_short_costs_are_adverse_on_both_fills() -> None:
    df = make_frame([100, 100, 95, 90, 80, 85, 90, 88])
    t = run_backtest(df, short_strategy(96, 82), BacktestConfig(initial_capital=1000, fee_bps=50, slippage_bps=50)).trades[0]
    assert t.entry_price == pytest.approx(95 * 0.995)  # sold lower
    assert t.exit_price == pytest.approx(85 * 1.005)  # bought back higher
    q = t.quantity
    assert t.pnl == pytest.approx(q * (t.entry_price - t.exit_price) - t.entry_fee - t.exit_fee)


def test_direction_defaults_to_long_for_existing_strategies() -> None:
    s = price_cross_strategy(102, 100)
    assert s.risk.direction == "long"
    out = run_backtest(make_frame([100, 100, 105, 110, 120, 95, 90]), s, NO_COSTS)
    assert out.trades[0].side == "long"


async def test_short_strategy_through_the_api(auth_client) -> None:  # type: ignore[no-untyped-def]
    from app.strategies.definition import TEMPLATES

    d = TEMPLATES[0]["definition"]
    body = {"name": "Short RSI", "config": {"symbol": "BTC-USD", "timeframe": "1h", **d, "risk": {**d["risk"], "direction": "short"}}}
    sid = (await auth_client.post("/api/v1/strategies", json=body)).json()["id"]
    assert (await auth_client.get(f"/api/v1/strategies/{sid}")).json()["current_config"]["risk"]["direction"] == "short"
    bt = (await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 1500})).json()
    assert bt["status"] == "completed" and bt["metrics"]["direction"] == "short"
    assert all(t["side"] == "short" for t in bt["trades"])
    bad = {**body, "name": "Bad", "config": {**body["config"], "risk": {"direction": "sideways"}}}
    assert (await auth_client.post("/api/v1/strategies", json=bad)).status_code == 422
