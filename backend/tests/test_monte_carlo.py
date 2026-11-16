"""Monte Carlo resampling of a backtest's own trades."""

import pytest

from app.backtesting.monte_carlo import monte_carlo, trade_fractions
from tests.conftest import register
from tests.test_export import _strategy

PNLS = [100.0, -50.0, 200.0, -150.0, 80.0, -20.0, 60.0]


def test_the_real_order_reproduces_the_backtest() -> None:
    mc = monte_carlo(1000, PNLS, runs=500, seed=1)
    assert mc.actual_return_pct == pytest.approx(sum(PNLS) / 1000 * 100)  # compounding the fractions gives back the P&L
    # Equity 1000 → 1100 → 1050 → 1250 → 1100: the worst fall is 150 from 1250.
    assert mc.actual_max_drawdown_pct == pytest.approx(150 / 1250 * 100)
    assert trade_fractions(1000, [100, -110])[1] == pytest.approx(-0.1)


def test_percentiles_are_ordered_and_seeded() -> None:
    a, b = monte_carlo(1000, PNLS, runs=800, seed=7), monte_carlo(1000, PNLS, runs=800, seed=7)
    assert a == b  # same backtest, same answer
    for d in (a.return_pct, a.max_drawdown_pct):
        values = [d[p] for p in (5, 25, 50, 75, 95)]
        assert values == sorted(values)
    assert 0 <= a.loss_probability_pct <= 100 and 0 <= a.drawdown_worse_than_actual_pct <= 100
    assert a.max_drawdown_pct[5] >= 0


def test_all_winners_never_lose_or_draw_down() -> None:
    mc = monte_carlo(1000, [10.0] * 6, runs=200)
    assert mc.loss_probability_pct == 0 and mc.max_drawdown_pct[95] == 0
    assert 0 < mc.return_pct[5] <= mc.return_pct[95]
    # Equal 1% trades (each $ win a bit bigger as equity grows): every run compounds to the same result.
    same = monte_carlo(1000, [1000 * 1.01**i * 0.01 for i in range(6)], runs=200)
    assert same.return_pct[5] == pytest.approx(same.return_pct[95]) == pytest.approx((1.01**6 - 1) * 100)


def test_too_few_trades() -> None:
    with pytest.raises(ValueError, match="at least 5 closed trades"):
        monte_carlo(1000, [1.0, 2.0])


async def test_endpoint_on_a_real_backtest(auth_client, client) -> None:  # type: ignore[no-untyped-def]
    sid = await _strategy(auth_client, "RSI")
    bt = (await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 1500})).json()
    closed = [t for t in bt["trades"] if t["exit_time"] is not None]
    resp = await auth_client.get(f"/api/v1/backtests/{bt['id']}/monte-carlo", params={"runs": 300})
    assert len(closed) >= 5  # the sample data gives this strategy enough trades to resample
    assert resp.status_code == 200, resp.text
    mc = resp.json()
    assert mc["runs"] == 300 and mc["trades"] == len(closed)
    assert set(mc["return_pct"]) == {"5", "25", "50", "75", "95"}
    assert "drawn at random with replacement" in mc["method"]
    # Someone else's backtest is not found; too many runs is refused.
    await register(client, email="other@example.com")
    assert (await client.get(f"/api/v1/backtests/{bt['id']}/monte-carlo")).status_code == 404
    assert (await auth_client.get(f"/api/v1/backtests/{bt['id']}/monte-carlo", params={"runs": 99999})).status_code == 422
