"""Price alerts: notify once the market price reaches a level. Research notifications only."""

import json

import httpx

from app.services import webhooks
from app.services.notifications import deliver_pending_webhooks
from app.services.price_alerts import check_price_alerts
from tests.test_webhooks import PUBLIC_IP, Receiver, fake_dns

API = "/api/v1"


async def create(client, expect: int = 201, **body):  # type: ignore[no-untyped-def]
    resp = await client.post(f"{API}/price-alerts", json={"symbol": "SOL-USD", "target": 120} | body)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def notifications(client) -> list[dict]:  # type: ignore[no-untyped-def]
    return (await client.get(f"{API}/notifications")).json()["notifications"]


async def test_alerts_fire_once_when_the_price_reaches_the_level(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    up = await create(auth_client, target=120, note="  Breakout   level ")
    down = await create(auth_client, target=90)
    assert (up["condition"], up["created_price"], up["note"]) == ("above", 100.0, "Breakout level")
    assert down["condition"] == "below" and up["triggered_at"] is None

    assert await check_price_alerts() == 0
    await provider.set_price("SOL-USD", 119.99)
    assert await check_price_alerts() == 0
    await provider.set_price("SOL-USD", 121.5)
    assert await check_price_alerts() == 1
    assert await check_price_alerts() == 0  # fires once

    (n,) = await notifications(auth_client)
    assert (n["kind"], n["title"], n["symbol"]) == ("price_alert", "Price alert · SOL-USD at or above 120.00", "SOL-USD")
    assert "traded at 121.50" in n["message"] and "set when it was 100.00" in n["message"] and "Breakout level" in n["message"]
    assert "no order was placed" in n["message"]

    alerts = (await auth_client.get(f"{API}/price-alerts")).json()
    assert [a["id"] for a in alerts] == [down["id"], up["id"]]  # active first, then fired
    assert alerts[1]["triggered_price"] == 121.5 and alerts[1]["triggered_at"] is not None

    await provider.set_price("SOL-USD", 89.0)
    assert await check_price_alerts() == 1
    assert len(await notifications(auth_client)) == 2


async def test_alerts_are_validated_limited_and_private(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import register

    await provider.set_price("SOL-USD", 100.0)
    await create(auth_client, 422, target=100)  # already there
    await create(auth_client, 422, target=0)
    await create(auth_client, 404, symbol="NOPE-USD")
    mine = await create(auth_client, target=150)
    assert len((await auth_client.get(f"{API}/price-alerts", params={"symbol": "SOL-USD"})).json()) == 1
    assert (await auth_client.get(f"{API}/price-alerts", params={"symbol": "BTC-USD"})).json() == []

    for i in range(49):
        await create(auth_client, target=200 + i)
    await create(auth_client, 422, target=500)  # 50 active at most

    auth_client.cookies.clear()
    await register(auth_client, email="other@example.com")
    assert (await auth_client.get(f"{API}/price-alerts")).json() == []
    assert (await auth_client.delete(f"{API}/price-alerts/{mine['id']}")).status_code == 404
    await create(auth_client, target=150)  # the limit is per user


async def test_deleting_an_alert_stops_it(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    alert = await create(auth_client, target=110)
    assert (await auth_client.delete(f"{API}/price-alerts/{alert['id']}")).status_code == 204
    await provider.set_price("SOL-USD", 111.0)
    assert await check_price_alerts() == 0
    assert await notifications(auth_client) == []


async def test_price_alerts_go_to_the_webhook_when_asked(auth_client, provider, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    receiver = Receiver()
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(receiver))
    fake_dns(monkeypatch, PUBLIC_IP)
    hook = (await auth_client.put(f"{API}/users/me/webhook", json={"url": "https://example.com/kestrel"})).json()
    assert hook["orders"] is False  # order events off: price alerts opt in on their own

    await provider.set_price("SOL-USD", 100.0)
    await create(auth_client, target=110)  # in-app only
    await create(auth_client, target=105, notify_webhook=True)
    await provider.set_price("SOL-USD", 112.0)
    assert await check_price_alerts() == 2
    assert await deliver_pending_webhooks() == 1

    req = receiver.requests[-1]
    payload = json.loads(req.content)
    assert payload["type"] == "price_alert" and payload["kind"] == "price_alert" and payload["symbol"] == "SOL-USD"
    assert payload["title"] == "Price alert · SOL-USD at or above 105.00"
    assert req.headers["x-kestrel-signature"] == webhooks.sign(hook["secret"], req.headers["x-kestrel-timestamp"], req.content)
