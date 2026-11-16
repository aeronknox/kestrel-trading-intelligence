"""Journal stats by weekday and time of day the trade was opened, in the user's timezone."""

from datetime import UTC, datetime

from sqlalchemy import select, update

from app.database.session import get_sessionmaker
from app.models.paper import SimulatedTrade
from tests.test_journal import API, trade


async def set_times(*times: datetime) -> None:
    """Give the fills, oldest first, these execution times."""
    async with get_sessionmaker()() as s:
        ids = (await s.scalars(select(SimulatedTrade.id).order_by(SimulatedTrade.id))).all()
        assert len(ids) == len(times)
        for i, when in zip(ids, times, strict=True):
            await s.execute(update(SimulatedTrade).where(SimulatedTrade.id == i).values(executed_at=when))
        await s.commit()


async def test_by_weekday_and_time_of_day(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 1)
    await provider.set_price("SOL-USD", 110.0)
    await trade(auth_client, "sell", 1)  # a win
    await trade(auth_client, "buy", 1)
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "sell", 1)  # a loss
    await set_times(
        datetime(2026, 11, 9, 2, tzinfo=UTC), datetime(2026, 11, 9, 3, tzinfo=UTC),  # opened Monday 02:00 UTC
        datetime(2026, 11, 11, 14, tzinfo=UTC), datetime(2026, 11, 11, 15, tzinfo=UTC),  # opened Wednesday 14:00 UTC
    )  # fmt: skip

    utc = (await auth_client.get(f"{API}/journal")).json()
    assert utc["timezone"] == "UTC"
    assert [(g["name"], g["trades"], g["win_rate"]) for g in utc["by_weekday"]] == [("Monday", 1, 100), ("Wednesday", 1, 0)]
    assert [g["name"] for g in utc["by_time_of_day"]] == ["00:00–04:00", "12:00–16:00"]

    # In New York the first trade was opened on Sunday evening: weekdays still come Monday first.
    ny = (await auth_client.get(f"{API}/journal", params={"tz": "America/New_York"})).json()
    assert [g["name"] for g in ny["by_weekday"]] == ["Wednesday", "Sunday"]
    assert [g["name"] for g in ny["by_time_of_day"]] == ["08:00–12:00", "20:00–00:00"]
    assert sum(g["total_pnl"] for g in ny["by_weekday"]) == ny["overall"]["total_pnl"]

    bad = await auth_client.get(f"{API}/journal", params={"tz": "Nowhere/Land"})
    assert bad.status_code == 422 and "Unknown timezone" in bad.text


async def test_open_trips_are_not_counted(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 1)
    page = (await auth_client.get(f"{API}/journal")).json()
    assert page["by_weekday"] == [] and page["by_time_of_day"] == []
