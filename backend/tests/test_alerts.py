"""Strategy alerts: edge-triggered firing on closed bars, catch-up limits, email and ownership."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from app.database.session import get_sessionmaker
from app.market_data.providers.base import Candle, ProductInfo, ProviderError
from app.market_data.providers.registry import register_provider
from app.market_data.providers.sample import SampleProvider
from app.models.alert import StrategyAlert
from app.services import email as email_service
from app.services.alerts import evaluate_alerts
from tests.conftest import register

H = 3600


def _now_k() -> int:
    return int(datetime.now(UTC).timestamp() // H)


class StepMarket(SampleProvider):
    """Hourly closes of 100, jumping to `after` from `step_hours_ago` hours ago onward.

    The newest candle is still forming, so with step_hours_ago=1 the jump happens on the
    newest *closed* bar.
    """

    def __init__(self, step_hours_ago: int = 1, after: float = 110.0) -> None:
        self.step_k = _now_k() - step_hours_ago
        self.after = after

    async def get_candles(self, provider_symbol, timeframe, limit=300, end=None):  # type: ignore[no-untyped-def]
        now_k = _now_k()
        out = []
        for k in range(now_k - limit + 1, now_k + 1):
            c = self.after if k >= self.step_k else 100.0
            o = self.after if k - 1 >= self.step_k else 100.0
            out.append(Candle(ts=datetime.fromtimestamp(k * H, tz=UTC), open=o, high=max(o, c) + 1, low=min(o, c) - 1, close=c, volume=10))
        return out

    async def get_ticker(self, provider_symbol):  # type: ignore[no-untyped-def]
        raise ProviderError("not needed")

    async def list_products(self) -> list[ProductInfo]:
        return []


def cond(op: str, value: float) -> dict:
    return {"left": {"indicator": "close"}, "op": op, "right": {"value": value}}


async def make_strategy(client, entry: dict, exit_: dict | None = None, name: str = "Alert test") -> int:  # type: ignore[no-untyped-def]
    body = {
        "name": name,
        "config": {
            "symbol": "BTC-USD",
            "timeframe": "1h",
            "entry": {"logic": "all", "conditions": [entry]},
            "exit": {"logic": "any", "conditions": [exit_ or cond("crosses_below", 50)]},
            "risk": {"position_size_pct": 100},
        },
    }
    resp = await client.post("/api/v1/strategies", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def rewind(strategy_id: int, hours: int) -> None:
    """Pretend the previous check happened `hours` closed bars ago."""
    async with get_sessionmaker()() as s:
        await s.execute(
            update(StrategyAlert)
            .where(StrategyAlert.strategy_id == strategy_id)
            .values(last_bar_at=datetime.fromtimestamp((_now_k() - 1 - hours) * H, tz=UTC))
        )
        await s.commit()


def use_market(m: StepMarket) -> StepMarket:
    """Install `m` as the app's provider and drop candles cached from the previous one."""
    from app.core.cache import get_cache

    register_provider(m)  # replaces the "sample" provider used by the app
    get_cache()._data.clear()  # type: ignore[attr-defined]
    return m


@pytest.fixture
def market() -> StepMarket:
    return use_market(StepMarket())


async def test_alert_fires_once_when_rule_becomes_true(auth_client, market) -> None:  # type: ignore[no-untyped-def]
    sid = await make_strategy(auth_client, cond("crosses_above", 105))
    alert = (await auth_client.put(f"/api/v1/alerts/strategy/{sid}", json={"on_entry": True, "on_exit": True})).json()
    assert alert["enabled"] and alert["symbol"] == "BTC-USD" and alert["last_bar_at"] is None

    assert await evaluate_alerts() == 0  # first check only records where to start; history never fires
    await rewind(sid, 2)
    assert await evaluate_alerts() == 1
    assert await evaluate_alerts() == 0  # same bar never fires twice

    page = (await auth_client.get("/api/v1/alerts/events")).json()
    assert page["unread"] == 1 and "No order was placed" in page["disclaimer"]
    ev = page["events"][0]
    assert ev["kind"] == "entry" and ev["close_price"] == 110.0 and ev["symbol"] == "BTC-USD"
    assert ev["bar_at"].startswith(datetime.fromtimestamp((_now_k() - 1) * H, tz=UTC).strftime("%Y-%m-%dT%H"))
    assert "CLOSE crosses above 105" in ev["message"]

    after = (await auth_client.post("/api/v1/alerts/events/read", json={})).json()
    assert after["unread"] == 0 and after["events"][0]["read_at"] is not None


async def test_level_conditions_fire_on_transition_only(auth_client, market) -> None:  # type: ignore[no-untyped-def]
    always = await make_strategy(auth_client, cond(">", 50), name="Always true")
    becomes = await make_strategy(auth_client, cond(">", 105), name="Becomes true")
    for sid in (always, becomes):
        await auth_client.put(f"/api/v1/alerts/strategy/{sid}", json={})
    await evaluate_alerts()
    for sid in (always, becomes):
        await rewind(sid, 3)
    assert await evaluate_alerts() == 1  # "close > 50" held all along; "close > 105" just became true
    events = (await auth_client.get("/api/v1/alerts/events")).json()["events"]
    assert [e["strategy_id"] for e in events] == [becomes]


async def test_disabled_kinds_and_catch_up_limit(auth_client) -> None:  # type: ignore[no-untyped-def]
    use_market(StepMarket(step_hours_ago=6))  # the jump happened 6 bars ago
    sid = await make_strategy(auth_client, cond("crosses_above", 105), cond("crosses_above", 105))
    await auth_client.put(f"/api/v1/alerts/strategy/{sid}", json={"on_exit": False})
    await evaluate_alerts()
    await rewind(sid, 10)  # long downtime: only the last 3 bars are caught up, so the old jump is skipped
    assert await evaluate_alerts() == 0
    await rewind(sid, 6)
    assert await evaluate_alerts() == 0  # still outside the 3-bar catch-up window

    use_market(StepMarket(step_hours_ago=2))
    await rewind(sid, 3)
    assert await evaluate_alerts() == 1  # within the window; exit rules match too but on_exit is off
    kinds = [e["kind"] for e in (await auth_client.get("/api/v1/alerts/events")).json()["events"]]
    assert kinds == ["entry"]


async def test_email_only_to_verified_addresses(client, market) -> None:  # type: ignore[no-untyped-def]
    from tests.test_email import last_token

    await register(client, email="trader@example.com")
    verify_token = last_token("trader@example.com")
    sid = await make_strategy(client, cond("crosses_above", 105))
    await client.put(f"/api/v1/alerts/strategy/{sid}", json={"notify_email": True})
    await evaluate_alerts()
    email_service.outbox.clear()
    await rewind(sid, 2)
    assert await evaluate_alerts() == 1
    assert list(email_service.outbox) == []  # unverified: in-app only

    assert (await client.post("/api/v1/auth/verify-email", json={"token": verify_token})).status_code == 200
    email_service.outbox.clear()
    async with get_sessionmaker()() as s:  # forget the recorded event so the same bar can fire again
        from sqlalchemy import delete

        from app.models.alert import AlertEvent

        await s.execute(delete(AlertEvent))
        await s.commit()
    await rewind(sid, 2)
    assert await evaluate_alerts() == 1
    msg = email_service.outbox[-1]
    assert msg.to == "trader@example.com" and msg.subject.startswith("Entry signal: Alert test")
    assert "No order was placed" in msg.text
    assert (await client.get("/api/v1/alerts/events")).json()["events"][0]["emailed_at"] is not None


async def test_disabled_and_archived_are_not_checked_and_reenable_restarts(auth_client, market) -> None:  # type: ignore[no-untyped-def]
    off = await make_strategy(auth_client, cond("crosses_above", 105), name="Off")
    archived = await make_strategy(auth_client, cond("crosses_above", 105), name="Archived")
    await auth_client.put(f"/api/v1/alerts/strategy/{off}", json={"enabled": False})
    await auth_client.put(f"/api/v1/alerts/strategy/{archived}", json={})
    await auth_client.patch(f"/api/v1/strategies/{archived}", json={"is_archived": True})
    await evaluate_alerts()
    listed = {a["strategy_id"]: a for a in (await auth_client.get("/api/v1/alerts")).json()}
    assert listed[off]["last_checked_at"] is None and listed[archived]["last_checked_at"] is None

    await auth_client.put(f"/api/v1/alerts/strategy/{off}", json={"enabled": True})
    await evaluate_alerts()
    a = (await auth_client.get(f"/api/v1/alerts/strategy/{off}")).json()
    assert a["last_checked_at"] is not None and a["last_bar_at"] is not None  # baseline only
    assert (await auth_client.get("/api/v1/alerts/events")).json()["events"] == []


async def test_alerts_are_private(auth_client, client) -> None:  # type: ignore[no-untyped-def]
    sid = await make_strategy(auth_client, cond("crosses_above", 105))
    await auth_client.put(f"/api/v1/alerts/strategy/{sid}", json={})
    await auth_client.post("/api/v1/auth/logout")
    await register(client, email="other@example.com")
    assert (await client.get(f"/api/v1/alerts/strategy/{sid}")).status_code == 404
    assert (await client.put(f"/api/v1/alerts/strategy/{sid}", json={})).status_code == 404
    assert (await client.delete(f"/api/v1/alerts/strategy/{sid}")).status_code == 404
    assert (await client.get("/api/v1/alerts")).json() == []


async def test_delete_alert(auth_client, market) -> None:  # type: ignore[no-untyped-def]
    sid = await make_strategy(auth_client, cond("crosses_above", 105))
    assert (await auth_client.get(f"/api/v1/alerts/strategy/{sid}")).json() is None
    await auth_client.put(f"/api/v1/alerts/strategy/{sid}", json={})
    assert (await auth_client.delete(f"/api/v1/alerts/strategy/{sid}")).status_code == 204
    assert (await auth_client.delete(f"/api/v1/alerts/strategy/{sid}")).status_code == 404

