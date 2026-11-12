"""Notifications for simulated paper orders that fill or fail in the background, and their webhooks."""

import json

import httpx
import pytest

from app.services import webhooks
from app.services.notifications import deliver_pending_webhooks
from tests.test_webhooks import PUBLIC_IP, Receiver, fake_dns

API = "/api/v1"


async def buy(client, **body):  # type: ignore[no-untyped-def]
    payload = {"symbol": "SOL-USD", "side": "buy", "order_type": "market", "quantity": 10} | body
    resp = await client.post(f"{API}/paper/orders", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def feed(client) -> dict:  # type: ignore[no-untyped-def]
    await client.get(f"{API}/paper/portfolio")  # runs order matching, as the background job does
    return (await client.get(f"{API}/notifications")).json()


async def test_a_stop_loss_firing_is_notified_but_instant_orders_are_not(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await buy(auth_client)
    assert (await feed(auth_client))["notifications"] == []  # the user just saw this fill on screen
    await auth_client.post(f"{API}/paper/positions/SOL-USD/protect", json={"stop_loss": 90, "take_profit": 120})

    await provider.set_price("SOL-USD", 89.0)
    page = await feed(auth_client)
    assert page["unread"] == 1
    n = page["notifications"][0]
    assert (n["kind"], n["title"], n["symbol"]) == ("order_filled", "Stop-loss filled · SOL-USD", "SOL-USD")
    assert "sold 10 SOL-USD at 88.96" in n["message"] and "other order of its pair was cancelled" in n["message"]
    assert "Simulated paper trading" in n["message"]

    read = (await auth_client.post(f"{API}/notifications/read", json={})).json()
    assert read["unread"] == 0 and read["notifications"][0]["read_at"]


async def test_fill_time_rejection_is_notified(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await buy(auth_client, order_type="limit", quantity=200, limit_price=95)
    await buy(auth_client, quantity=100)  # filling the resting order would now breach the 25% limit
    await provider.set_price("SOL-USD", 94.0)
    n = (await feed(auth_client))["notifications"][0]
    assert (n["kind"], n["title"]) == ("order_rejected", "Limit buy rejected · SOL-USD")
    assert "limit is 25%" in n["message"]


async def test_margin_call_is_notified(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    limits = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 90, "allow_short": True}
    await auth_client.put(f"{API}/paper/portfolio/risk-limits", json=limits)
    await buy(auth_client, side="sell", quantity=10)
    await provider.set_price("SOL-USD", 201.0)
    n = (await feed(auth_client))["notifications"][0]
    assert (n["kind"], n["title"]) == ("margin_call", "Margin call · SOL-USD")
    assert "bought back" in n["message"]


async def test_order_notifications_go_to_the_webhook_only_when_switched_on(auth_client, provider, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    receiver = Receiver()
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(receiver))
    fake_dns(monkeypatch, PUBLIC_IP)
    hook = (await auth_client.put(f"{API}/users/me/webhook", json={"url": "https://example.com/kestrel"})).json()
    assert hook["orders"] is False
    await provider.set_price("SOL-USD", 100.0)
    await buy(auth_client)

    await buy(auth_client, side="sell", order_type="stop", stop_price=95, quantity=5)
    await provider.set_price("SOL-USD", 94.0)
    await feed(auth_client)
    assert await deliver_pending_webhooks() == 0  # off by default: in-app only

    assert (await auth_client.patch(f"{API}/users/me/webhook", json={"orders": True})).json()["orders"] is True
    await buy(auth_client, side="sell", order_type="stop", stop_price=90, quantity=5)
    await provider.set_price("SOL-USD", 89.0)
    await feed(auth_client)
    assert await deliver_pending_webhooks() == 1
    assert await deliver_pending_webhooks() == 0  # delivered once, not again

    req = receiver.requests[-1]
    payload = json.loads(req.content)
    assert payload["type"] == "paper_order" and payload["kind"] == "order_filled" and payload["symbol"] == "SOL-USD"
    assert payload["title"] == "Stop sell filled · SOL-USD"
    assert req.headers["x-kestrel-signature"] == webhooks.sign(hook["secret"], req.headers["x-kestrel-timestamp"], req.content)
    assert (await auth_client.get(f"{API}/users/me/webhook")).json()["last_status"] == "HTTP 204"


async def test_notifications_are_private(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import register

    await provider.set_price("SOL-USD", 100.0)
    await buy(auth_client)
    await buy(auth_client, side="sell", order_type="stop", stop_price=95)
    await provider.set_price("SOL-USD", 94.0)
    mine = await feed(auth_client)
    assert mine["unread"] == 1
    my_ids = [n["id"] for n in mine["notifications"]]

    auth_client.cookies.clear()  # switch to a second account
    await register(auth_client, email="other@example.com")
    assert (await auth_client.get(f"{API}/notifications")).json() == {"notifications": [], "unread": 0}
    await auth_client.post(f"{API}/notifications/read", json={"ids": my_ids})  # can't mark someone else's read

    auth_client.cookies.clear()
    login = await auth_client.post(f"{API}/auth/login", json={"email": "user@example.com", "password": "s3cure-passw0rd"})
    assert login.status_code == 200
    assert (await auth_client.get(f"{API}/notifications")).json()["unread"] == 1


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(webhooks, "transport", httpx.MockTransport(Receiver()))
