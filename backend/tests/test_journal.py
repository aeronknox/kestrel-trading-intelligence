"""Trading journal: round trips from fills, journal entries, and stats by setup and emotion."""

import pytest

API = "/api/v1/paper"


async def trade(client, side: str, quantity: float, symbol: str = "SOL-USD") -> dict:  # type: ignore[no-untyped-def]
    resp = await client.post(f"{API}/orders", json={"symbol": symbol, "side": side, "order_type": "market", "quantity": quantity})
    assert resp.status_code == 201 and resp.json()["status"] == "filled", resp.text
    return resp.json()


async def journal(client) -> dict:  # type: ignore[no-untyped-def]
    resp = await client.get(f"{API}/journal")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def write(client, trade_id: int, expect: int = 200, **body) -> dict:  # type: ignore[no-untyped-def]
    resp = await client.put(f"{API}/journal/{trade_id}", json=body)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def test_fills_group_into_round_trips(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 10)
    await provider.set_price("SOL-USD", 110.0)
    await trade(auth_client, "buy", 5)  # scale in
    await provider.set_price("SOL-USD", 120.0)
    await trade(auth_client, "sell", 8)  # partial exit: the trip stays open
    assert (await journal(auth_client))["trips"][0]["closed_at"] is None
    await trade(auth_client, "sell", 7)
    await trade(auth_client, "buy", 2)  # a new trip

    trips = (await journal(auth_client))["trips"]
    assert len(trips) == 2
    newest, first = trips
    assert newest["closed_at"] is None and newest["pnl"] is None and newest["quantity"] == pytest.approx(2)
    assert first["side"] == "long" and first["fills"] == 4 and first["quantity"] == pytest.approx(15)
    assert first["entry_price"] == pytest.approx((10 * 100 + 5 * 110) / 15 * 1.0005)
    assert first["exit_price"] == pytest.approx(120 * (1 - 0.0005))
    realized = (await auth_client.get(f"{API}/portfolio")).json()["realized_pnl"]
    assert first["pnl"] == pytest.approx(realized)  # the trip's P&L is exactly what it realized, fees included
    assert first["pnl_pct"] == pytest.approx(first["pnl"] / (15 * first["entry_price"]) * 100)


async def test_short_round_trip(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    limits = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True}
    await auth_client.put(f"{API}/portfolio/risk-limits", json=limits)
    await trade(auth_client, "sell", 10)
    await provider.set_price("SOL-USD", 90.0)
    await trade(auth_client, "buy", 10)
    (trip,) = (await journal(auth_client))["trips"]
    assert trip["side"] == "short" and trip["pnl"] > 0 and trip["holding_seconds"] is not None


async def test_entries_and_stats_by_setup_and_emotion(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    async def round_trip(entry: float, exit_: float) -> None:
        await provider.set_price("SOL-USD", entry)
        await trade(auth_client, "buy", 10)
        await provider.set_price("SOL-USD", exit_)
        await trade(auth_client, "sell", 10)

    await round_trip(100, 110)  # win
    await round_trip(100, 95)  # loss
    await round_trip(100, 104)  # win
    await round_trip(100, 90)  # loss, left unreviewed
    win1, loss1, win2, _ = sorted((await journal(auth_client))["trips"], key=lambda t: t["trade_id"])

    saved = await write(
        auth_client, win1["trade_id"], setup="  Breakout ", emotion="calm", rating=5, notes="Waited for the close."
    )
    assert saved["setup"] == "Breakout"
    await write(auth_client, loss1["trade_id"], setup="breakout", emotion="fomo", rating=2, lesson="Chased the move.")
    await write(auth_client, win2["trade_id"], setup="RSI bounce", emotion="calm", rating=4)

    page = await journal(auth_client)
    assert page["needs_review"] == 1 and page["setups"] == ["Breakout", "RSI bounce"]
    by_setup = {g["name"]: g for g in page["by_setup"]}
    breakout = by_setup["Breakout"]  # "breakout" reused the existing spelling
    assert breakout["trades"] == 2 and breakout["win_rate"] == 50 and breakout["avg_rating"] == 3.5
    assert breakout["avg_pnl"] == pytest.approx(breakout["total_pnl"] / 2)
    assert by_setup[None]["trades"] == 1 and page["by_setup"][-1]["name"] is None  # unreviewed last
    by_emotion = {g["name"]: g for g in page["by_emotion"]}
    assert by_emotion["calm"]["win_rate"] == 100 and by_emotion["fomo"]["win_rate"] == 0

    # Editing replaces the entry; deleting returns the trip to "needs review".
    await write(auth_client, loss1["trade_id"], setup="Breakout", emotion="impatient")
    assert (await auth_client.delete(f"{API}/journal/{loss1['trade_id']}")).status_code == 204
    assert (await journal(auth_client))["needs_review"] == 2


async def test_entries_are_validated_and_private(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    from tests.conftest import register

    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 10)
    sell = await trade(auth_client, "sell", 10)
    trip_id = (await journal(auth_client))["trips"][0]["trade_id"]
    closing_fill = next(t["id"] for t in (await auth_client.get(f"{API}/trades")).json() if t["order_id"] == sell["id"])
    await write(auth_client, closing_fill, 404, setup="x")  # only a trip's opening fill takes an entry
    await write(auth_client, trip_id, 422, emotion="euphoric")
    await write(auth_client, trip_id, 422, rating=6)
    await write(auth_client, trip_id, setup="Mine")

    auth_client.cookies.clear()
    await register(auth_client, email="other@example.com")
    await write(auth_client, trip_id, 404, setup="Not yours")
    assert (await auth_client.delete(f"{API}/journal/{trip_id}")).status_code == 404


async def test_reset_clears_the_journal_and_csv_neutralizes_formulas(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 10)
    await trade(auth_client, "sell", 10)
    trip_id = (await journal(auth_client))["trips"][0]["trade_id"]
    await write(auth_client, trip_id, setup="Breakout", notes='=HYPERLINK("http://evil.example","click")')

    csv = (await auth_client.get(f"{API}/journal.csv")).text
    assert "'=HYPERLINK" in csv and ",Breakout," in csv

    await auth_client.post(f"{API}/portfolio/reset")
    page = await journal(auth_client)
    assert page["trips"] == [] and page["setups"] == []
