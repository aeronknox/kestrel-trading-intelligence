"""Multi-asset tests: equal capital split, common window, alignment, benchmark and API."""

import csv
import io
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.backtesting.engine import BacktestConfig, buy_and_hold_equity, run_backtest
from app.backtesting.portfolio import PortfolioError, run_portfolio
from app.strategies.definition import TEMPLATES, StrategyDefinition
from tests.conftest import make_frame

ALWAYS_IN = {
    "entry": {"conditions": [{"left": {"indicator": "close"}, "op": ">", "right": {"value": 0}}]},
    "exit": {"conditions": [{"left": {"indicator": "close"}, "op": "<", "right": {"value": 0}}]},
    "risk": {"position_size_pct": 100},
}
NO_COSTS = BacktestConfig(initial_capital=10_000, fee_bps=0, slippage_bps=0)


def series(n: int, drift: float, seed: int, start: datetime | None = None):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    return make_frame(list(closes), start=start)


def test_capital_is_split_and_sleeves_sum_to_the_portfolio() -> None:
    frames = {"AAA": series(300, 0.002, 1), "BBB": series(300, -0.001, 2)}
    out = run_portfolio(frames, ALWAYS_IN, NO_COSTS)
    assert out["capital_per_asset"] == 5_000
    sleeves = [run_backtest(df, StrategyDefinition.model_validate(ALWAYS_IN), BacktestConfig(5_000, 0, 0)) for df in frames.values()]
    assert out["metrics"]["final_equity"] == pytest.approx(sum(s.metrics["final_equity"] for s in sleeves))
    assert [a["symbol"] for a in out["per_asset"]] == ["AAA", "BBB"]
    assert out["per_asset"][0]["final_equity"] == pytest.approx(sleeves[0].metrics["final_equity"])
    # Equal-weight buy-and-hold benchmark with the same costs.
    bh = sum(
        buy_and_hold_equity(df["open"].to_numpy(float), df["close"].to_numpy(float), BacktestConfig(5_000, 0, 0))[-1]
        for df in frames.values()
    )
    assert out["metrics"]["benchmark"]["total_return_pct"] == pytest.approx((bh / 10_000 - 1) * 100)
    assert out["metrics"]["num_trades"] == 2


def test_assets_are_tested_over_their_common_window() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    late = t0 + timedelta(hours=100)  # BBB lists 100 hours later
    frames = {"AAA": series(400, 0.0, 3, t0), "BBB": series(300, 0.0, 4, late)}
    out = run_portfolio(frames, ALWAYS_IN, NO_COSTS)
    assert out["window"]["start"] == int(late.timestamp())
    assert [a["bars"] for a in out["per_asset"]] == [300, 300]


def test_missing_bars_hold_their_last_value() -> None:
    a, b = series(300, 0.001, 5), series(300, 0.001, 6)
    b = b.drop(index=[150, 151, 152]).reset_index(drop=True)  # an exchange outage on one asset
    out = run_portfolio({"AAA": a, "BBB": b}, ALWAYS_IN, NO_COSTS)
    curve = out["equity_curve"]
    assert all(np.isfinite(p["equity"]) and np.isfinite(p["benchmark"]) for p in curve)
    assert out["per_asset"][1]["bars"] == 297


def test_correlation_matrix_is_symmetric_with_unit_diagonal() -> None:
    base = series(300, 0.001, 7)
    twin = base.copy()
    twin[["open", "high", "low", "close"]] *= 2  # same moves, different price level
    out = run_portfolio({"AAA": base, "BBB": twin, "CCC": series(300, 0.0, 8)}, ALWAYS_IN, NO_COSTS)
    m = out["correlation"]["matrix"]
    assert all(m[i][i] == pytest.approx(1.0) for i in range(3))
    assert m[0][1] == pytest.approx(m[1][0]) and m[0][1] == pytest.approx(1.0, abs=1e-6)
    assert -1 <= out["correlation"]["average"] <= 1


@pytest.mark.parametrize(
    ("frames", "message"),
    [
        ({"AAA": series(300, 0, 1)}, "Choose 2 to 6"),
        ({f"A{i}": series(300, 0, i) for i in range(7)}, "Choose 2 to 6"),
        ({"AAA": series(300, 0, 1, datetime(2024, 1, 1, tzinfo=UTC)),
          "BBB": series(300, 0, 2, datetime(2024, 1, 1, tzinfo=UTC) + timedelta(hours=250))}, "overlapping history"),
    ],
)  # fmt: skip
def test_invalid_requests(frames, message) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(PortfolioError, match=message):
        run_portfolio(frames, ALWAYS_IN, NO_COSTS)


async def test_portfolio_api_and_csv(auth_client) -> None:  # type: ignore[no-untyped-def]
    d = TEMPLATES[0]["definition"]
    sid = (await auth_client.post("/api/v1/strategies", json={"name": "Multi", "config": {"symbol": "BTC-USD", "timeframe": "1h", **d}})).json()["id"]
    resp = await auth_client.post("/api/v1/research/portfolio", json={"strategy_id": sid, "symbols": ["BTC-USD", "eth-usd", "SOL-USD"], "bars": 800})
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["kind"] == "portfolio" and run["result"]["symbols"] == ["BTC-USD", "ETH-USD", "SOL-USD"]
    assert run["headline"].startswith("3 assets:") and len(run["result"]["per_asset"]) == 3
    listed = (await auth_client.get("/api/v1/research")).json()
    assert listed[0]["kind"] == "portfolio"

    text = (await auth_client.get(f"/api/v1/research/{run['id']}/results.csv")).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:2] == ["symbol", "bars"] and [r[0] for r in rows[1:]] == ["BTC-USD", "ETH-USD", "SOL-USD"]

    dup = await auth_client.post("/api/v1/research/portfolio", json={"strategy_id": sid, "symbols": ["BTC-USD", "btc-usd"]})
    assert dup.status_code == 422
    untracked = await auth_client.post("/api/v1/research/portfolio", json={"strategy_id": sid, "symbols": ["BTC-USD", "NOPE-USD"]})
    assert untracked.status_code == 404


async def test_portfolio_bounds_on_demand_downloads(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Each asset's missing history is fetched within a fixed budget; the rest is left to the backfill job."""
    from app.api.routes import research
    from app.market_data.service import MarketDataService

    budgets: list[int | None] = []
    real = MarketDataService.get_history

    async def spy(self, asset, timeframe, bars, *, fetch_budget=None):  # type: ignore[no-untyped-def]
        budgets.append(fetch_budget)
        return await real(self, asset, timeframe, bars, fetch_budget=fetch_budget)

    monkeypatch.setattr(MarketDataService, "get_history", spy)
    from httpx import ASGITransport, AsyncClient

    from tests.conftest import register

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await register(c)
        d = TEMPLATES[0]["definition"]
        sid = (await c.post("/api/v1/strategies", json={"name": "B", "config": {"symbol": "BTC-USD", "timeframe": "1h", **d}})).json()["id"]
        run = (await c.post("/api/v1/research/portfolio", json={"strategy_id": sid, "symbols": ["BTC-USD", "ETH-USD"], "bars": 20_000})).json()
    assert budgets == [research.PORTFOLIO_FETCH_BUDGET] * 2
    assert run["request"]["incomplete_history"] == []  # sample data is generated, never partial
