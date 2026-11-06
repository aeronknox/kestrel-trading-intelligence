"""Parameter sweeps and walk-forward analysis."""

import itertools

import numpy as np
import pytest

from app.backtesting.engine import BacktestConfig, run_backtest
from app.backtesting.optimization import (
    OptimizationError,
    ParamGrid,
    apply_params,
    run_sweep,
    run_walk_forward,
    tunable_parameters,
    validate_grid,
    walk_forward_windows,
)
from app.strategies.definition import TEMPLATES, StrategyDefinition
from tests.conftest import make_frame

RSI = next(t for t in TEMPLATES if t["key"] == "rsi_mean_reversion")["definition"]
MACD = next(t for t in TEMPLATES if t["key"] == "macd_momentum")["definition"]
CONFIG = BacktestConfig(initial_capital=10_000, fee_bps=10, slippage_bps=5)
THRESHOLD = "entry.conditions.0.right.value"
STOP = "risk.stop_loss_pct"


def wavy_frame(n: int = 900, seed: int = 7):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    closes = 100 + 15 * np.sin(t / 25) + np.cumsum(rng.normal(0, 0.8, n))
    return make_frame(list(np.maximum(closes, 5)))


def test_tunable_parameters_cover_thresholds_indicator_params_and_risk() -> None:
    params = {p["path"]: p for p in tunable_parameters(RSI)}
    assert params[THRESHOLD]["current"] == 30
    assert params["entry.conditions.0.left.params.period"] == {
        "path": "entry.conditions.0.left.params.period", "label": "Entry #1 (RSI(14) crosses above 30): RSI period",
        "current": 14, "min": 2, "max": 100, "integer": True,
    }  # fmt: skip
    assert params[STOP]["current"] == 5
    assert "exit.conditions.0.right.value" in params


def test_apply_params_returns_none_for_invalid_combinations() -> None:
    assert apply_params(MACD, {"entry.conditions.0.left.params.fast": 30}) is None  # fast >= slow (26)
    s = apply_params(RSI, {THRESHOLD: 25, STOP: 2})
    assert s is not None and s.entry.conditions[0].right.value == 25 and s.risk.stop_loss_pct == 2
    assert RSI["entry"]["conditions"][0]["right"]["value"] == 30  # the original is not mutated


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        ([ParamGrid("entry.conditions.9.right.value", [1, 2])], "Unknown parameter"),
        ([ParamGrid(STOP, [1.0])], "Give 2 to"),
        ([ParamGrid(STOP, [1, 1])], "Duplicate"),
        ([ParamGrid(STOP, [0.0, 2])], "between"),
        ([ParamGrid(THRESHOLD, list(range(10, 21))), ParamGrid(STOP, list(range(1, 11)))], "the limit is 100"),
        ([ParamGrid(STOP, [1, 2]), ParamGrid(STOP, [3, 4])], "only be swept once"),
    ],
)
def test_validate_grid_rejects_bad_requests(grid, message) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(OptimizationError, match=message):
        validate_grid(RSI, grid)


def test_backtest_start_offset_only_warms_up_before_start() -> None:
    df = wavy_frame(400)
    strategy = StrategyDefinition.model_validate(RSI)
    full = run_backtest(df, strategy, CONFIG)
    late = run_backtest(df, strategy, CONFIG, start=250)
    assert len(late.equity) == 150 and late.equity.iloc[0] == pytest.approx(CONFIG.initial_capital, rel=0.01)
    first_ts = int(df["ts"][250].timestamp())
    assert all(t.entry_time > first_ts for t in late.trades)  # signals at bar 250 fill at 251 at the earliest
    assert late.bars == 150 and full.bars == 400


def test_sweep_reports_every_cell_and_picks_the_best_score() -> None:
    df = wavy_frame()
    grid = [ParamGrid(THRESHOLD, [25, 30, 35]), ParamGrid(STOP, [2, 5])]
    out = run_sweep(df, RSI, grid, CONFIG, objective="total_return_pct", min_trades=0)
    assert [c["values"] for c in out["cells"]] == [[25, 2], [25, 5], [30, 2], [30, 5], [35, 2], [35, 5]]
    scores = [c["score"] for c in out["cells"]]
    assert out["best_index"] == int(np.argmax(scores))
    # Each cell is exactly an ordinary backtest with those settings.
    direct = run_backtest(df, apply_params(RSI, {THRESHOLD: 35, STOP: 5}), CONFIG).metrics  # type: ignore[arg-type]
    assert out["cells"][5]["metrics"]["total_return_pct"] == pytest.approx(direct["total_return_pct"])
    baseline = run_backtest(df, StrategyDefinition.model_validate(RSI), CONFIG).metrics
    assert out["baseline"]["total_return_pct"] == pytest.approx(baseline["total_return_pct"])


def test_sweep_marks_invalid_combinations_and_enforces_min_trades() -> None:
    df = wavy_frame()
    grid = [ParamGrid("entry.conditions.0.left.params.fast", [8, 30])]
    out = run_sweep(df, MACD, grid, CONFIG, min_trades=10_000)
    assert out["cells"][1]["valid"] is False and out["cells"][1]["metrics"] is None
    assert out["cells"][0]["valid"] is True and out["cells"][0]["score"] is None  # too few trades
    assert out["best_index"] is None


def test_walk_forward_windows_are_contiguous_and_proportional() -> None:
    windows = walk_forward_windows(1000, folds=4, is_ratio=3)
    oos_len = 1000 // 7
    assert windows[0] == (0, 3 * oos_len, 4 * oos_len)
    for (_, _, end), (_, nxt_start, _) in itertools.pairwise(windows):
        assert end == nxt_start  # test windows tile the period with no gaps or overlap
    with pytest.raises(OptimizationError, match="too few"):
        walk_forward_windows(200, folds=8, is_ratio=6)


def test_walk_forward_has_no_lookahead() -> None:
    """Changing bars after a fold's test window must not change that fold's choice or result."""
    df = wavy_frame()
    grid = [ParamGrid(THRESHOLD, [25, 30, 35]), ParamGrid(STOP, [2, 5])]
    base = run_walk_forward(df, RSI, grid, CONFIG, folds=3, is_ratio=2, min_trades=0)
    cut = walk_forward_windows(len(df), 3, 2)[1][2]  # end of fold 2's test window
    tampered = df.copy()
    rng = np.random.default_rng(99)
    tampered.loc[cut:, ["open", "high", "low", "close"]] *= rng.uniform(0.5, 1.5, (len(df) - cut, 1))
    tampered["high"] = tampered[["open", "high", "close"]].max(axis=1)
    tampered["low"] = tampered[["open", "low", "close"]].min(axis=1)
    other = run_walk_forward(tampered, RSI, grid, CONFIG, folds=3, is_ratio=2, min_trades=0)
    for a, b in zip(base["fold_results"][:2], other["fold_results"][:2], strict=True):
        assert a["chosen"] == b["chosen"]
        assert a["oos_metrics"] == b["oos_metrics"]


def test_walk_forward_stitches_test_windows_and_chains_capital() -> None:
    df = wavy_frame()
    grid = [ParamGrid(THRESHOLD, [25, 35])]
    out = run_walk_forward(df, RSI, grid, CONFIG, folds=3, is_ratio=2, min_trades=0)
    windows = walk_forward_windows(len(df), 3, 2)
    assert [f["out_of_sample"]["bars"] for f in out["fold_results"]] == [e - s for _, s, e in windows]
    assert out["oos_metrics"]["bars"] == windows[-1][2] - windows[0][1]
    # Compounding the folds' returns reproduces the stitched result.
    growth = np.prod([1 + f["oos_metrics"]["total_return_pct"] / 100 for f in out["fold_results"]])
    assert out["oos_metrics"]["total_return_pct"] == pytest.approx((growth - 1) * 100)
    assert out["verdict"]["level"] in {"robust", "weak", "overfit", "unprofitable", "inconclusive"}
    assert {"equity", "baseline", "benchmark"} <= set(out["equity_curve"][0])


# ------------------------------------------------------------------------ API
async def _strategy(client, symbol: str = "BTC-USD") -> int:  # type: ignore[no-untyped-def]
    body = {"name": "RSI test", "config": {"symbol": symbol, "timeframe": "1h", **RSI}}
    resp = await client.post("/api/v1/strategies", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_research_api_sweep_and_walk_forward_lifecycle(auth_client) -> None:  # type: ignore[no-untyped-def]
    sid = await _strategy(auth_client)
    params = (await auth_client.get("/api/v1/research/parameters", params={"strategy_id": sid})).json()
    assert THRESHOLD in {p["path"] for p in params}

    grid = [{"path": THRESHOLD, "values": [25, 30, 35]}, {"path": STOP, "values": [2, 5]}]
    sweep = await auth_client.post("/api/v1/research/sweeps", json={"strategy_id": sid, "bars": 800, "params": grid, "min_trades": 0})
    assert sweep.status_code == 201, sweep.text
    s = sweep.json()
    assert s["kind"] == "sweep" and len(s["result"]["cells"]) == 6 and "HYPOTHETICAL" in s["disclaimer"]
    assert "sample" in s["data_source"]

    wf = await auth_client.post(
        "/api/v1/research/walk-forward", json={"strategy_id": sid, "bars": 800, "params": grid[:1], "folds": 3, "is_ratio": 2}
    )
    assert wf.status_code == 201, wf.text
    w = wf.json()
    assert len(w["result"]["fold_results"]) == 3 and w["headline"] == w["result"]["verdict"]["headline"]

    listed = (await auth_client.get("/api/v1/research", params={"strategy_id": sid})).json()
    assert [r["id"] for r in listed] == [w["id"], s["id"]]
    assert (await auth_client.get(f"/api/v1/research/{s['id']}")).json()["result"] == s["result"]
    assert (await auth_client.delete(f"/api/v1/research/{s['id']}")).status_code == 204
    assert (await auth_client.get(f"/api/v1/research/{s['id']}")).status_code == 404


async def test_research_api_validation_and_ownership(auth_client, client) -> None:  # type: ignore[no-untyped-def]
    sid = await _strategy(auth_client)
    bad = await auth_client.post(
        "/api/v1/research/sweeps", json={"strategy_id": sid, "params": [{"path": "risk.nope", "values": [1, 2]}]}
    )
    assert bad.status_code == 422 and "Unknown parameter" in bad.json()["error"]["message"]
    too_small = await auth_client.post(
        "/api/v1/research/walk-forward",
        json={"strategy_id": sid, "bars": 200, "params": [{"path": STOP, "values": [2, 5]}], "folds": 8, "is_ratio": 6},
    )
    assert too_small.status_code == 422 and "too few" in too_small.json()["error"]["message"]

    run = (await auth_client.post("/api/v1/research/sweeps", json={"strategy_id": sid, "bars": 300, "params": [{"path": STOP, "values": [2, 5]}]})).json()
    await auth_client.post("/api/v1/auth/logout")
    from tests.conftest import register

    await register(client, email="other@example.com")
    assert (await client.get(f"/api/v1/research/{run['id']}")).status_code == 404
    assert (await client.get("/api/v1/research/parameters", params={"strategy_id": sid})).status_code == 404
    assert (await client.get("/api/v1/research")).json() == []
