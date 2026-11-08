"""Forward testing: strategies trading the paper portfolio on live closed candles."""

from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app.core.cache import get_cache
from app.database.session import get_sessionmaker
from app.market_data.providers.base import Candle, ProductInfo, Ticker
from app.market_data.providers.registry import register_provider
from app.market_data.providers.sample import SampleProvider
from app.models.alert import StrategyAlert
from app.models.paper import SimulatedOrder
from app.services.alerts import evaluate_alerts

H = 3600
API = "/api/v1"


def now_k() -> int:
    return int(datetime.now(UTC).timestamp() // H)


class ScriptMarket(SampleProvider):
    """Hourly candles whose close is `close(hours_ago)`; the live price is the newest close."""

    def __init__(self, close: Callable[[int], float]) -> None:
        self.close_at = close

    def _candle(self, k: int) -> Candle:  # type: ignore[override]
        ago = now_k() - k
        c, o = self.close_at(ago), self.close_at(ago + 1)
        return Candle(ts=datetime.fromtimestamp(k * H, tz=UTC), open=o, high=max(o, c) + 0.5, low=min(o, c) - 0.5, close=c, volume=10)

    async def get_candles(self, provider_symbol, timeframe, limit=300, end=None):  # type: ignore[no-untyped-def]
        return [self._candle(k) for k in range(now_k() - limit + 1, now_k() + 1)]

    async def get_ticker(self, provider_symbol):  # type: ignore[no-untyped-def]
        p = self.close_at(0)
        return Ticker(provider_symbol, p, p, p, p, 1.0, datetime.now(UTC))

    async def list_products(self) -> list[ProductInfo]:
        return []


async def use(close: Callable[[int], float]) -> None:
    register_provider(ScriptMarket(close))
    get_cache()._data.clear()  # type: ignore[attr-defined]


def cond(op: str, value: float) -> dict:
    return {"left": {"indicator": "close"}, "op": op, "right": {"value": value}}


async def strategy(client, entry: dict, exit_: dict, name: str = "Forward", **risk) -> int:  # type: ignore[no-untyped-def]
    body = {"name": name, "config": {"symbol": "BTC-USD", "timeframe": "1h",
            "entry": {"conditions": [entry]}, "exit": {"conditions": [exit_]},
            "risk": {"position_size_pct": 100, **risk}}}  # fmt: skip
    resp = await client.post(f"{API}/strategies", json=body)
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    assert (await client.put(f"{API}/alerts/strategy/{sid}", json={"auto_trade": True})).status_code == 200
    return sid


async def rewind(strategy_id: int, bars: int) -> None:
    async with get_sessionmaker()() as s:
        await s.execute(
            update(StrategyAlert)
            .where(StrategyAlert.strategy_id == strategy_id)
            .values(last_bar_at=datetime.fromtimestamp((now_k() - 1 - bars) * H, tz=UTC))
        )
        await s.commit()


async def strategy_orders(strategy_id: int) -> list[SimulatedOrder]:
    async with get_sessionmaker()() as s:
        return list((await s.scalars(select(SimulatedOrder).where(SimulatedOrder.strategy_id == strategy_id).order_by(SimulatedOrder.id))).all())


async def test_buys_on_entry_sized_within_limits_then_holds(auth_client) -> None:  # type: ignore[no-untyped-def]
    await use(lambda ago: 110.0 if ago <= 1 else 100.0)  # jumps above 105 on the newest closed bar
    sid = await strategy(auth_client, cond(">", 105), cond("<", 95))
    await evaluate_alerts()  # baseline
    await rewind(sid, 2)
    await evaluate_alerts()
    orders = await strategy_orders(sid)
    assert [(o.side.value, o.status.value) for o in orders] == [("buy", "filled")]
    pf = (await auth_client.get(f"{API}/paper/portfolio")).json()
    pos = pf["positions"][0]
    # position_size_pct=100 is capped by the portfolio's 25% position limit.
    assert pos["market_value"] / pf["equity"] * 100 == pytest.approx(25, abs=0.2)
    events = (await auth_client.get(f"{API}/alerts/events")).json()["events"]
    assert events[0]["kind"] == "entry" and events[0]["order_id"] == orders[0].id
    assert "Paper order bought on entry rules" in events[0]["message"]

    await rewind(sid, 1)  # the entry rule is still true, but the strategy already holds
    await evaluate_alerts()
    assert len(await strategy_orders(sid)) == 1


async def test_exit_sells_only_what_the_strategy_bought(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await use(lambda ago: 110.0 if ago <= 1 else 100.0)
    sid = await strategy(auth_client, cond(">", 105), cond("<", 95))
    manual = await auth_client.post(f"{API}/paper/orders", json={"symbol": "BTC-USD", "side": "buy", "order_type": "market", "quantity": 10})
    assert manual.json()["status"] == "filled"
    await evaluate_alerts()
    await rewind(sid, 2)
    await evaluate_alerts()
    bought = (await strategy_orders(sid))[0].quantity

    await use(lambda ago: 90.0 if ago <= 1 else 110.0)  # falls below 95: exit rules true
    await rewind(sid, 1)
    await evaluate_alerts()
    orders = await strategy_orders(sid)
    assert [o.side.value for o in orders] == ["buy", "sell"] and orders[1].quantity == pytest.approx(bought)
    pos = (await auth_client.get(f"{API}/paper/portfolio")).json()["positions"][0]
    assert pos["quantity"] == pytest.approx(10)  # the manual position is untouched

    summary = (await auth_client.get(f"{API}/alerts/strategy/{sid}/forward-test")).json()
    assert summary["num_trades"] == 1 and summary["open_position"] is None
    trip = summary["round_trips"][0]
    assert trip["pnl"] < 0 and trip["exit_price"] < trip["entry_price"]  # bought ~110, sold ~90
    assert "sold on exit rules" in trip["note"]


async def test_stop_loss_on_a_closed_bar(auth_client) -> None:  # type: ignore[no-untyped-def]
    await use(lambda ago: 110.0 if ago <= 1 else 100.0)
    sid = await strategy(auth_client, cond(">", 105), cond("<", 50), stop_loss_pct=5)
    await evaluate_alerts()
    await rewind(sid, 2)
    await evaluate_alerts()
    await use(lambda ago: 103.0 if ago <= 1 else 110.0)  # newest bar's low (102.5) is below the 5% stop (~104.5)
    await rewind(sid, 1)
    await evaluate_alerts()
    orders = await strategy_orders(sid)
    assert [o.side.value for o in orders] == ["buy", "sell"]
    events = (await auth_client.get(f"{API}/alerts/events")).json()["events"]
    assert any("sold on stop-loss" in e["message"] for e in events)


async def test_manual_close_leaves_the_strategy_flat_without_errors(auth_client) -> None:  # type: ignore[no-untyped-def]
    await use(lambda ago: 110.0 if ago <= 1 else 100.0)
    sid = await strategy(auth_client, cond(">", 105), cond("<", 95))
    await evaluate_alerts()
    await rewind(sid, 2)
    await evaluate_alerts()
    qty = (await strategy_orders(sid))[0].quantity
    sold = await auth_client.post(f"{API}/paper/orders", json={"symbol": "BTC-USD", "side": "sell", "order_type": "market", "quantity": qty})
    assert sold.json()["status"] == "filled"
    await use(lambda ago: 90.0 if ago <= 1 else 110.0)
    await rewind(sid, 1)
    await evaluate_alerts()
    alert = (await auth_client.get(f"{API}/alerts/strategy/{sid}")).json()
    assert alert["last_error"] is None
    assert len(await strategy_orders(sid)) == 1  # nothing left to sell, so no order


async def test_risk_rejection_is_reported_not_raised(auth_client) -> None:  # type: ignore[no-untyped-def]
    await use(lambda ago: 110.0 if ago <= 1 else 100.0)
    await auth_client.put(f"{API}/paper/portfolio/risk-limits", json={"max_position_pct": 25, "max_open_positions": 1, "daily_loss_limit_pct": 5})
    await auth_client.post(f"{API}/paper/orders", json={"symbol": "ETH-USD", "side": "buy", "order_type": "market", "quantity": 1})
    sid = await strategy(auth_client, cond(">", 105), cond("<", 95))
    await evaluate_alerts()
    await rewind(sid, 2)
    await evaluate_alerts()
    orders = await strategy_orders(sid)
    assert [o.status.value for o in orders] == ["rejected"]
    events = (await auth_client.get(f"{API}/alerts/events")).json()["events"]
    assert "Paper order rejected: Maximum of 1 open positions reached" in events[0]["message"]


async def test_short_strategy_forward_test_needs_and_uses_short_selling(auth_client) -> None:  # type: ignore[no-untyped-def]
    await use(lambda ago: 90.0 if ago <= 1 else 100.0)  # falls below 95 on the newest closed bar
    body = {"name": "Shorty", "config": {"symbol": "BTC-USD", "timeframe": "1h", "entry": {"conditions": [cond("<", 95)]},
            "exit": {"conditions": [cond(">", 105)]}, "risk": {"direction": "short", "position_size_pct": 10}}}  # fmt: skip
    sid = (await auth_client.post(f"{API}/strategies", json=body)).json()["id"]
    refused = await auth_client.put(f"{API}/alerts/strategy/{sid}", json={"auto_trade": True})
    assert refused.status_code == 422 and "enable short selling" in refused.json()["error"]["message"]

    await auth_client.put(f"{API}/paper/portfolio/risk-limits",
                          json={"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True})  # fmt: skip
    assert (await auth_client.put(f"{API}/alerts/strategy/{sid}", json={"auto_trade": True})).status_code == 200
    await evaluate_alerts()
    await rewind(sid, 2)
    await evaluate_alerts()
    pos = (await auth_client.get(f"{API}/paper/portfolio")).json()["positions"][0]
    assert pos["side"] == "short"

    await use(lambda ago: 110.0 if ago <= 1 else 90.0)  # rallies above 105: the exit rules cover the short
    await rewind(sid, 1)
    await evaluate_alerts()
    assert [o.side.value for o in await strategy_orders(sid)] == ["sell", "buy"]
    summary = (await auth_client.get(f"{API}/alerts/strategy/{sid}/forward-test")).json()
    trip = summary["round_trips"][0]
    assert trip["side"] == "short" and summary["open_position"] is None
    assert trip["pnl"] == pytest.approx(trip["quantity"] * (trip["entry_price"] - trip["exit_price"]), rel=0.01)  # ~fees apart
    assert trip["pnl"] < 0  # shorted near 90, covered near 110
    assert "covered on exit rules" in trip["note"]
