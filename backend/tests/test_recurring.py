"""Recurring paper buys (dollar-cost averaging): simulated market buys on a schedule."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.database.session import get_sessionmaker
from app.models.recurring import RecurringBuy
from app.services.recurring import run_due_recurring_buys
from tests.conftest import register

API = "/api/v1/paper/recurring-buys"


async def create(client, expect: int = 201, **body):  # type: ignore[no-untyped-def]
    resp = await client.post(API, json={"symbol": "BTC-USD", "amount_usd": 500, "interval_days": 7} | body)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def plans(client) -> list[dict]:  # type: ignore[no-untyped-def]
    return (await client.get(API)).json()


async def set_next_run(plan_id: int, when: datetime) -> None:
    async with get_sessionmaker()() as s:
        await s.execute(update(RecurringBuy).where(RecurringBuy.id == plan_id).values(next_run_at=when))
        await s.commit()


async def test_a_due_plan_buys_its_amount_and_reschedules(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    plan = await create(auth_client)
    assert plan["active"] and plan["runs"] == 0 and plan["average_price"] is None

    assert await run_due_recurring_buys() == 1
    assert await run_due_recurring_buys() == 0  # once per date
    (p,) = await plans(auth_client)
    assert p["runs"] == 1 and p["last_status"] == "filled" and p["last_message"].startswith("Bought ")
    assert p["invested_usd"] == pytest.approx(500, abs=0.01)  # the amount, slippage and fee included
    assert p["average_price"] == pytest.approx(500 / p["quantity_bought"])
    next_run = datetime.fromisoformat(p["next_run_at"])
    assert timedelta(days=6, hours=23) < next_run - datetime.now(UTC) <= timedelta(days=7)

    pf = (await auth_client.get("/api/v1/paper/portfolio")).json()
    assert pf["positions"][0]["asset"]["symbol"] == "BTC-USD"
    assert pf["positions"][0]["quantity"] == pytest.approx(p["quantity_bought"])
    note = (await auth_client.get("/api/v1/notifications")).json()["notifications"][0]
    assert note["title"] == "Recurring buy filled · BTC-USD"

    # The next date: it buys again at the new price, and the average moves.
    await provider.set_price("BTC-USD", 40_000.0)
    await set_next_run(p["id"], datetime.now(UTC) - timedelta(seconds=1))
    assert await run_due_recurring_buys() == 1
    (p2,) = await plans(auth_client)
    assert p2["runs"] == 2 and p2["invested_usd"] == pytest.approx(1000, abs=0.02)
    assert 40_000 < p2["average_price"] < 50_000


async def test_missed_dates_are_not_replayed(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    plan = await create(auth_client, interval_days=1)
    await set_next_run(plan["id"], datetime.now(UTC) - timedelta(days=10, hours=3))
    assert await run_due_recurring_buys() == 1
    (p,) = await plans(auth_client)
    assert p["runs"] == 1
    assert timedelta(0) < datetime.fromisoformat(p["next_run_at"]) - datetime.now(UTC) <= timedelta(days=1)


async def test_rejected_by_risk_limits_and_not_started_yet(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    later = await create(auth_client, start_now=False)
    assert await run_due_recurring_buys() == 0
    assert (await plans(auth_client))[0]["last_run_at"] is None
    await auth_client.delete(f"{API}/{later['id']}")

    too_big = await create(auth_client, amount_usd=60_000)  # over the 25% position limit of a $100k account
    assert await run_due_recurring_buys() == 0
    (p,) = await plans(auth_client)
    assert p["last_status"] == "rejected" and "limit is 25%" in p["last_message"] and p["runs"] == 0
    assert datetime.fromisoformat(p["next_run_at"]) > datetime.now(UTC)  # tries again on its next date
    assert p["id"] == too_big["id"]


async def test_pause_resume_delete_and_limits(app, auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    plan = await create(auth_client)
    paused = (await auth_client.patch(f"{API}/{plan['id']}", json={"active": False})).json()
    assert paused["active"] is False
    assert await run_due_recurring_buys() == 0  # paused plans don't run
    resumed = (await auth_client.patch(f"{API}/{plan['id']}", json={"active": True})).json()
    assert resumed["active"] and datetime.fromisoformat(resumed["next_run_at"]) > datetime.now(UTC) + timedelta(days=6)

    await create(auth_client, 422, interval_days=3)
    await create(auth_client, 422, amount_usd=0.5)
    for _ in range(9):
        await create(auth_client)
    full = await create(auth_client, 422)
    assert "up to 10 active recurring buys" in full["error"]["message"]

    # Someone else can't see or touch them.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await register(other, email="other@example.com")
        assert (await other.get(API)).json() == []
        assert (await other.delete(f"{API}/{plan['id']}")).status_code == 404
    assert (await auth_client.delete(f"{API}/{plan['id']}")).status_code == 204
    assert len(await plans(auth_client)) == 9
