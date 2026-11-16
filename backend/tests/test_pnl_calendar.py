"""Realized P&L per day, grouped in the user's timezone: only from simulated closing fills."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from app.database.session import get_sessionmaker
from app.models.paper import SimulatedTrade
from tests.test_stop_orders import API, order


async def close_at(when: datetime) -> None:
    """Move the latest closing fill to `when`."""
    async with get_sessionmaker()() as s:
        latest = (await s.execute(SimulatedTrade.__table__.select().where(SimulatedTrade.is_closing.is_(True))
                                  .order_by(SimulatedTrade.id.desc()).limit(1))).first()  # fmt: skip
        assert latest is not None
        await s.execute(update(SimulatedTrade).where(SimulatedTrade.id == latest.id).values(executed_at=when))
        await s.commit()


async def round_trip(client, provider, exit_price: float, when: datetime) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(client, quantity=1)
    await provider.set_price("SOL-USD", exit_price)
    await order(client, side="sell", quantity=1)
    await close_at(when)


async def test_days_are_grouped_in_the_requested_timezone(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    # 03:00 UTC on the 10th is still the 9th in New York; 15:00 UTC is the 10th in both.
    await round_trip(auth_client, provider, 110, datetime(2026, 11, 10, 3, tzinfo=UTC))
    await round_trip(auth_client, provider, 95, datetime(2026, 11, 10, 15, tzinfo=UTC))
    await round_trip(auth_client, provider, 104, datetime(2026, 11, 12, 15, tzinfo=UTC))

    utc = (await auth_client.get(f"{API}/pnl-calendar")).json()
    assert utc["timezone"] == "UTC"
    assert [(d["date"], d["trades"], d["wins"], d["losses"]) for d in utc["days"]] == [("2026-11-10", 2, 1, 1), ("2026-11-12", 1, 1, 0)]

    ny = (await auth_client.get(f"{API}/pnl-calendar", params={"tz": "America/New_York"})).json()
    by_date = {d["date"]: d for d in ny["days"]}
    assert list(by_date) == ["2026-11-09", "2026-11-10", "2026-11-12"]
    assert by_date["2026-11-09"]["realized_pnl"] > 9 and by_date["2026-11-10"]["realized_pnl"] < -5
    assert (ny["green_days"], ny["red_days"]) == (2, 1)
    assert ny["best_day"]["date"] == "2026-11-09" and ny["worst_day"]["date"] == "2026-11-10"
    # The days add up to the portfolio's realized P&L.
    realized = (await auth_client.get(f"{API}/portfolio")).json()["realized_pnl"]
    assert sum(d["realized_pnl"] for d in ny["days"]) == pytest.approx(realized)


async def test_empty_and_unknown_timezone(auth_client) -> None:  # type: ignore[no-untyped-def]
    empty = (await auth_client.get(f"{API}/pnl-calendar", params={"tz": "Asia/Tokyo"})).json()
    assert empty == {"timezone": "Asia/Tokyo", "days": [], "green_days": 0, "red_days": 0, "best_day": None, "worst_day": None}
    for bad in ("Mars/Olympus", "../etc/passwd"):
        resp = await auth_client.get(f"{API}/pnl-calendar", params={"tz": bad})
        assert resp.status_code == 422 and "Unknown timezone" in resp.text


async def test_only_winning_days_have_no_worst_day(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await round_trip(auth_client, provider, 120, datetime(2026, 11, 1, 12, tzinfo=UTC))
    cal = (await auth_client.get(f"{API}/pnl-calendar")).json()
    assert cal["best_day"]["date"] == "2026-11-01" and cal["worst_day"] is None
