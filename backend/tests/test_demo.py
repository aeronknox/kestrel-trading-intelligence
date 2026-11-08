"""Demo sandboxes: per-visitor accounts, seeded data, restrictions and expiry."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.config import get_settings
from app.database.session import get_sessionmaker
from app.models.strategy import Strategy
from app.models.user import User
from app.services import email as email_service
from app.services.demo import purge_expired_demo_users
from tests.conftest import register


@pytest.fixture
def demo_on(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "demo_mode", True)


async def test_demo_is_off_by_default(client) -> None:  # type: ignore[no-untyped-def]
    assert (await client.get("/api/v1/auth/config")).json() == {"demo_enabled": False}
    assert (await client.post("/api/v1/auth/demo")).status_code == 404


async def test_demo_creates_a_seeded_signed_in_sandbox(client, provider, demo_on) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 60_000.0)
    assert (await client.get("/api/v1/auth/config")).json() == {"demo_enabled": True}
    resp = await client.post("/api/v1/auth/demo")
    assert resp.status_code == 201
    user = resp.json()
    assert user["is_demo"] is True and user["email"].endswith("@demo.invalid")
    assert (await client.get("/api/v1/auth/me")).json()["id"] == user["id"]  # signed in

    strategies = (await client.get("/api/v1/strategies")).json()
    assert {s["name"] for s in strategies} == {"RSI mean reversion", "Moving-average crossover"}
    backtests = (await client.get("/api/v1/backtests")).json()
    assert len(backtests) == 1 and backtests[0]["status"] == "completed"
    positions = (await client.get("/api/v1/paper/portfolio")).json()["positions"]
    assert [p["asset"]["symbol"] for p in positions] == ["BTC-USD"]


async def test_each_visitor_gets_an_isolated_sandbox(client, demo_on) -> None:  # type: ignore[no-untyped-def]
    first = (await client.post("/api/v1/auth/demo")).json()
    sid = (await client.get("/api/v1/strategies")).json()[0]["id"]
    client.cookies.clear()
    second = (await client.post("/api/v1/auth/demo")).json()
    assert second["id"] != first["id"]
    assert (await client.get(f"/api/v1/strategies/{sid}")).status_code == 404  # can't see the other sandbox


async def test_demo_accounts_cannot_change_credentials_or_get_email(client, demo_on) -> None:  # type: ignore[no-untyped-def]
    user = (await client.post("/api/v1/auth/demo")).json()
    pw = await client.post("/api/v1/auth/change-password", json={"current_password": "x" * 12, "new_password": "brand-new-passw0rd"})
    assert pw.status_code == 403 and "demo" in pw.json()["error"]["message"]
    assert (await client.post("/api/v1/auth/verify-email/resend")).status_code == 403
    email_service.outbox.clear()
    # The reserved .invalid domain is rejected by email validation outright; nothing is ever sent.
    assert (await client.post("/api/v1/auth/forgot-password", json={"email": user["email"]})).status_code in (202, 422)
    assert list(email_service.outbox) == []
    sid = (await client.get("/api/v1/strategies")).json()[0]["id"]
    alert = (await client.put(f"/api/v1/alerts/strategy/{sid}", json={"notify_email": True})).json()
    assert alert["notify_email"] is False  # in-app only


async def test_expired_demo_accounts_are_purged_with_their_data(client, demo_on) -> None:  # type: ignore[no-untyped-def]
    await register(client, email="real@example.com")
    client.cookies.clear()
    demo = (await client.post("/api/v1/auth/demo")).json()
    client.cookies.clear()
    fresh = (await client.post("/api/v1/auth/demo")).json()
    async with get_sessionmaker()() as s:
        await s.execute(update(User).where(User.id == demo["id"]).values(created_at=datetime.now(UTC) - timedelta(hours=25)))
        await s.commit()

    assert await purge_expired_demo_users() == 1
    async with get_sessionmaker()() as s:
        remaining = set((await s.scalars(select(User.email))).all())
        assert demo["email"] not in remaining
        assert {"real@example.com", fresh["email"]} <= remaining  # real users and young demos stay
        orphans = await s.scalar(select(func.count()).select_from(Strategy).where(Strategy.user_id == demo["id"]))
        assert orphans == 0  # ON DELETE CASCADE removed the sandbox's data
    assert await purge_expired_demo_users() == 0


async def test_demo_capacity_is_capped_after_purging_expired(client, demo_on, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings(), "demo_max_accounts", 2)
    first = (await client.post("/api/v1/auth/demo")).json()
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/demo")).status_code == 201
    client.cookies.clear()
    full = await client.post("/api/v1/auth/demo")
    assert full.status_code == 429 and "capacity" in full.json()["error"]["message"]
    async with get_sessionmaker()() as s:  # one sandbox expires: its slot is reclaimed on the next request
        await s.execute(update(User).where(User.id == first["id"]).values(created_at=datetime.now(UTC) - timedelta(hours=25)))
        await s.commit()
    assert (await client.post("/api/v1/auth/demo")).status_code == 201


async def test_demo_users_get_no_paid_llm_calls_and_cannot_track_assets(client, demo_on, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.ai import assistant, llm

    calls = 0

    class Boom:
        class chat:
            class completions:
                @staticmethod
                async def create(**kwargs):  # type: ignore[no-untyped-def]
                    nonlocal calls
                    calls += 1
                    raise AssertionError("LLM must not be called for demo users")

    monkeypatch.setattr(llm, "get_client", lambda: Boom())
    monkeypatch.setattr(assistant, "get_client", lambda: Boom())
    await client.post("/api/v1/auth/demo")
    chat = (await client.post("/api/v1/assistant/chat", json={"message": "How is BTC doing?"})).json()
    assert calls == 0 and chat["message"]["meta"]["engine"] == "rule_based"
    analysis = await client.post("/api/v1/analysis", json={"symbol": "BTC-USD", "timeframe": "1h"})
    assert analysis.status_code in (200, 201) and calls == 0

    tracked = await client.post("/api/v1/market/assets", json={"symbol": "ATOM-USD"})
    assert tracked.status_code == 403 and "demo" in tracked.json()["error"]["message"]
    # Control: the same fake client *is* used for a real account, so the zero above is meaningful.
    client.cookies.clear()
    await register(client, email="paying@example.com")
    await client.post("/api/v1/assistant/chat", json={"message": "How is BTC doing?"})
    assert calls >= 1
