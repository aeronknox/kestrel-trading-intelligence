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


async def test_r_multiples_from_the_initial_stop(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    async def close(price: float) -> dict:
        await provider.set_price("SOL-USD", price)
        await trade(auth_client, "sell", 10)
        return (await journal(auth_client))["trips"][0]

    # 1. A stop-loss riding on the entry.
    await provider.set_price("SOL-USD", 100.0)
    resp = await auth_client.post(
        f"{API}/orders", json={"symbol": "SOL-USD", "side": "buy", "order_type": "market", "quantity": 10, "stop_loss": 95}
    )
    assert resp.status_code == 201, resp.text
    open_trip = (await journal(auth_client))["trips"][0]
    assert open_trip["initial_stop"] == 95 and open_trip["stop_source"] == "bracket" and open_trip["r_multiple"] is None
    bracket = await close(110)
    assert bracket["risk"] == pytest.approx((bracket["entry_price"] - 95) * 10)
    assert bracket["r_multiple"] == pytest.approx(bracket["pnl"] / bracket["risk"]) and bracket["r_multiple"] > 1.5

    # 2. Protection added afterwards: the first stop counts, not where it was moved to later.
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 10)
    assert (await auth_client.post(f"{API}/positions/SOL-USD/protect", json={"stop_loss": 90})).status_code == 201
    assert (await auth_client.post(f"{API}/positions/SOL-USD/protect", json={"stop_loss": 99})).status_code == 201
    protected = await close(95)
    assert protected["initial_stop"] == 90 and protected["stop_source"] == "stop order"
    assert -1 < protected["r_multiple"] < 0

    # 3. A trailing stop: its starting level, even after it has trailed up.
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 10)
    assert (await auth_client.post(f"{API}/positions/SOL-USD/protect", json={"trailing_stop_pct": 10})).status_code == 201
    await provider.set_price("SOL-USD", 130.0)
    await auth_client.get(f"{API}/portfolio")  # the stop follows to 117
    trailed = await close(125)
    assert trailed["initial_stop"] == pytest.approx(90) and trailed["r_multiple"] > 2

    # 4. No stop at all: no R, until the journal records where the plan was to get out.
    await provider.set_price("SOL-USD", 100.0)
    await trade(auth_client, "buy", 10)
    plain = await close(104)
    assert plain["initial_stop"] is None and plain["risk"] is None and plain["r_multiple"] is None
    await write(auth_client, plain["trade_id"], 422, planned_stop=101)  # above a long's entry
    saved = await write(auth_client, plain["trade_id"], setup="Breakout", planned_stop=98)
    assert saved["planned_stop"] == 98
    page = await journal(auth_client)
    plain = page["trips"][0]
    assert plain["stop_source"] == "journal" and plain["r_multiple"] == pytest.approx(plain["pnl"] / ((plain["entry_price"] - 98) * 10))

    # The journal's stop overrides the one found on the orders.
    await write(auth_client, bracket["trade_id"], planned_stop=90)
    page = await journal(auth_client)
    assert next(t for t in page["trips"] if t["trade_id"] == bracket["trade_id"])["stop_source"] == "journal"

    overall = page["overall"]
    rs = [t["r_multiple"] for t in page["trips"]]
    assert overall["trades"] == 4 and overall["r_trades"] == 4 and overall["avg_r"] == pytest.approx(sum(rs) / 4)
    assert {g["name"]: g for g in page["by_setup"]}["Breakout"]["r_trades"] == 1

    csv = (await auth_client.get(f"{API}/journal.csv")).text
    assert "initial_stop,risk,r_multiple" in csv.splitlines()[0]


async def test_short_trip_risk_is_above_the_entry(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    limits = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True}
    await auth_client.put(f"{API}/portfolio/risk-limits", json=limits)
    await trade(auth_client, "sell", 10)
    await provider.set_price("SOL-USD", 90.0)
    await trade(auth_client, "buy", 10)
    trip = (await journal(auth_client))["trips"][0]
    await write(auth_client, trip["trade_id"], 422, planned_stop=95)
    await write(auth_client, trip["trade_id"], planned_stop=105)
    trip = (await journal(auth_client))["trips"][0]
    assert trip["risk"] == pytest.approx((105 - trip["entry_price"]) * 10) and trip["r_multiple"] > 1


async def test_r_curve_adds_up_closed_trades_in_the_order_they_closed(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    assert (await journal(auth_client))["r_curve"] is None

    async def trip(exit_: float, stop: float | None = 90) -> None:
        await provider.set_price("SOL-USD", 100.0)
        body = {"symbol": "SOL-USD", "side": "buy", "order_type": "market", "quantity": 10}
        resp = await auth_client.post(f"{API}/orders", json=body | ({"stop_loss": stop} if stop else {}))
        assert resp.json()["status"] == "filled", resp.text
        await provider.set_price("SOL-USD", exit_)
        await trade(auth_client, "sell", 10)

    await trip(120)  # about +2R
    await trip(95)  # about -0.5R
    await trip(93)  # about -0.7R
    await trip(105, stop=None)  # no stop: not on the curve
    await trip(110)  # about +1R

    page = await journal(auth_client)
    curve = page["r_curve"]
    by_id = {t["trade_id"]: t for t in page["trips"]}
    rs = [p["r"] for p in curve["points"]]
    assert len(rs) == 4 and [p["r"] for p in curve["points"]] == [by_id[p["trade_id"]]["r_multiple"] for p in curve["points"]]
    assert rs[0] > 1.5 and rs[1] < 0 and rs[2] < 0 and rs[3] > 0.5
    cumulative = [sum(rs[: i + 1]) for i in range(4)]
    assert [p["cumulative_r"] for p in curve["points"]] == pytest.approx(cumulative)
    assert curve["total_r"] == pytest.approx(sum(rs))
    assert curve["max_drawdown_r"] == pytest.approx(-(rs[1] + rs[2]))  # the two losses in a row, from the first peak
    assert curve["longest_losing_streak"] == 2
    assert curve["points"][0]["closed_at"] <= curve["points"][-1]["closed_at"]
