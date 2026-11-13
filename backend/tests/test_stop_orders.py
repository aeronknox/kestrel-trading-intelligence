"""Paper trading stop orders, reduce-only orders and one-cancels-other position protection."""

import pytest

API = "/api/v1/paper"


async def order(client, expect: int = 201, **body):  # type: ignore[no-untyped-def]
    payload = {"symbol": "SOL-USD", "side": "buy", "order_type": "market", "quantity": 10} | body
    resp = await client.post(f"{API}/orders", json=payload)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def orders(client) -> dict[int, dict]:  # type: ignore[no-untyped-def]
    await client.get(f"{API}/portfolio")  # runs order matching, as the background job does
    return {o["id"]: o for o in (await client.get(f"{API}/orders")).json()}


async def protect(client, expect: int = 201, symbol: str = "SOL-USD", **body):  # type: ignore[no-untyped-def]
    resp = await client.post(f"{API}/positions/{symbol}/protect", json=body)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def test_sell_stop_rests_then_fills_at_market_past_a_gap(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    stop = await order(auth_client, side="sell", order_type="stop", stop_price=95)
    assert stop["status"] == "open" and stop["stop_price"] == 95 and stop["limit_price"] is None

    await provider.set_price("SOL-USD", 97.0)  # above the stop: nothing happens
    assert (await orders(auth_client))[stop["id"]]["status"] == "open"

    await provider.set_price("SOL-USD", 90.0)  # gapped through 95: fills at the market, not at the stop
    filled = (await orders(auth_client))[stop["id"]]
    assert filled["status"] == "filled"
    assert filled["filled_price"] == pytest.approx(90 * (1 - 0.0005))
    assert (await auth_client.get(f"{API}/portfolio")).json()["positions"] == []


async def test_stops_that_would_trigger_at_once_are_refused(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    resp = await order(auth_client, expect=422, side="sell", order_type="stop", stop_price=101)
    assert "would trigger at once" in resp["error"]["message"]
    await order(auth_client, expect=422, side="buy", order_type="stop", stop_price=99)
    await order(auth_client, expect=422, order_type="stop")  # no stop price


async def test_buy_stop_reserves_cash_and_opens_on_a_breakout(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    before = (await auth_client.get(f"{API}/portfolio")).json()["available_cash"]
    stop = await order(auth_client, order_type="stop", stop_price=110)
    reserved = (await auth_client.get(f"{API}/portfolio")).json()
    # Worst case at the stop plus slippage and fees is held back while it rests.
    assert before - reserved["available_cash"] == pytest.approx(10 * 110 * 1.0005 * 1.001)

    await provider.set_price("SOL-USD", 111.0)
    assert (await orders(auth_client))[stop["id"]]["status"] == "filled"
    pos = (await auth_client.get(f"{API}/portfolio")).json()["positions"][0]
    assert pos["quantity"] == pytest.approx(10)


async def test_protection_is_one_cancels_other_take_profit_side(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl, tp = await protect(auth_client, stop_loss=90, take_profit=120)
    assert (sl["order_type"], sl["side"], sl["note"], sl["reduce_only"]) == ("stop", "sell", "Stop-loss", True)
    assert (tp["order_type"], tp["limit_price"], tp["note"]) == ("limit", 120, "Take-profit")
    assert sl["oco_group"] == tp["oco_group"] and sl["oco_group"]

    await provider.set_price("SOL-USD", 121.0)
    after = await orders(auth_client)
    assert after[tp["id"]]["status"] == "filled"
    assert after[sl["id"]]["status"] == "cancelled" and "other order of its pair filled" in after[sl["id"]]["note"]
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"] == [] and pf["realized_pnl"] > 0


async def test_protection_stop_loss_side(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl, tp = await protect(auth_client, stop_loss=90, take_profit=120)
    await provider.set_price("SOL-USD", 89.0)
    after = await orders(auth_client)
    assert after[sl["id"]]["status"] == "filled" and after[tp["id"]]["status"] == "cancelled"
    assert (await auth_client.get(f"{API}/portfolio")).json()["realized_pnl"] < 0


async def test_protection_never_blocks_closing_and_follows_the_position(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl, tp = await protect(auth_client, stop_loss=90, take_profit=120)

    # Selling part of the position isn't blocked by the protective orders; they shrink to what's left.
    assert (await order(auth_client, side="sell", quantity=4))["status"] == "filled"
    shrunk = await orders(auth_client)
    assert shrunk[sl["id"]]["quantity"] == pytest.approx(6) and shrunk[tp["id"]]["quantity"] == pytest.approx(6)

    # Closing the rest cancels them, so a leftover stop can never open a new (short) position.
    assert (await order(auth_client, side="sell", quantity=6))["status"] == "filled"
    closed = await orders(auth_client)
    for oid in (sl["id"], tp["id"]):
        assert closed[oid]["status"] == "cancelled" and "position it protected is closed" in closed[oid]["note"]


async def test_new_protection_replaces_the_old(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    first = await protect(auth_client, stop_loss=90)
    second = await protect(auth_client, stop_loss=95, take_profit=130)
    now = await orders(auth_client)
    assert now[first[0]["id"]]["status"] == "cancelled" and now[first[0]["id"]]["note"] == "Replaced by new protection"
    assert all(now[o["id"]]["status"] == "open" for o in second)


async def test_protection_is_validated(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    assert "No open SOL-USD position" in (await protect(auth_client, 422, stop_loss=90))["error"]["message"]
    await order(auth_client)
    assert "below the current price" in (await protect(auth_client, 422, stop_loss=105))["error"]["message"]
    assert "above the current price" in (await protect(auth_client, 422, take_profit=95))["error"]["message"]
    assert "Set a stop-loss, a take-profit" in (await protect(auth_client, 422))["error"]["message"]


async def test_short_protection_buys_to_cover(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    limits = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True}
    await auth_client.put(f"{API}/portfolio/risk-limits", json=limits)
    await order(auth_client, side="sell")  # short 10
    assert "above the current price" in (await protect(auth_client, 422, stop_loss=95))["error"]["message"]
    sl, _tp = await protect(auth_client, stop_loss=110, take_profit=80)
    assert sl["side"] == "buy"
    await provider.set_price("SOL-USD", 112.0)
    assert (await orders(auth_client))[sl["id"]]["status"] == "filled"
    assert (await auth_client.get(f"{API}/portfolio")).json()["positions"] == []


async def test_reduce_only_orders_need_a_position_to_reduce(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    rejected = await order(auth_client, side="sell", order_type="limit", limit_price=120, reduce_only=True)
    assert rejected["status"] == "rejected" and "Reduce-only" in rejected["reject_reason"]


async def test_protection_is_all_or_nothing(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client, quantity=0.5)  # $50 position
    # A $0.05 stop-loss is under the minimum order size: the whole request fails and nothing is left behind.
    resp = await protect(auth_client, 422, stop_loss=0.1, take_profit=120)
    assert "Stop-loss rejected" in resp["error"]["message"]
    assert [o for o in (await orders(auth_client)).values() if o["status"] == "open"] == []


async def test_trailing_stop_ratchets_up_never_down_then_fires(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    trail = await order(auth_client, side="sell", order_type="trailing_stop", trail_pct=5)
    assert trail["status"] == "open" and trail["stop_price"] == pytest.approx(95) and trail["trail_anchor"] == 100

    await provider.set_price("SOL-USD", 110.0)  # new high: the stop follows to 5% below it
    moved = (await orders(auth_client))[trail["id"]]
    assert moved["trail_anchor"] == 110 and moved["stop_price"] == pytest.approx(104.5)

    await provider.set_price("SOL-USD", 106.0)  # a dip above the stop leaves it where it is
    held = (await orders(auth_client))[trail["id"]]
    assert held["status"] == "open" and held["stop_price"] == pytest.approx(104.5)

    await provider.set_price("SOL-USD", 104.0)
    fired = (await orders(auth_client))[trail["id"]]
    assert fired["status"] == "filled" and fired["filled_price"] == pytest.approx(104 * (1 - 0.0005))
    assert (await auth_client.get(f"{API}/portfolio")).json()["realized_pnl"] > 0  # locked in part of the rise


async def test_trailing_stop_on_a_short_follows_the_low(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    limits = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True}
    await auth_client.put(f"{API}/portfolio/risk-limits", json=limits)
    await order(auth_client, side="sell")  # short 10
    (sl,) = await protect(auth_client, trailing_stop_pct=5)
    assert (sl["side"], sl["order_type"], sl["note"]) == ("buy", "trailing_stop", "Trailing stop")
    assert sl["stop_price"] == pytest.approx(105)

    await provider.set_price("SOL-USD", 90.0)
    assert (await orders(auth_client))[sl["id"]]["stop_price"] == pytest.approx(94.5)
    await provider.set_price("SOL-USD", 95.0)
    assert (await orders(auth_client))[sl["id"]]["status"] == "filled"
    assert (await auth_client.get(f"{API}/portfolio")).json()["positions"] == []


async def test_trailing_stop_validation(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    await order(auth_client, expect=422, side="sell", order_type="trailing_stop")  # no trail
    await order(auth_client, expect=422, side="sell", order_type="trailing_stop", trail_pct=60)
    both = await protect(auth_client, 422, stop_loss=90, trailing_stop_pct=5)
    assert "not both" in both["error"]["message"]
    paired = await protect(auth_client, trailing_stop_pct=8, take_profit=130)
    assert sorted(o["note"] for o in paired) == ["Take-profit", "Trailing stop"]
    assert paired[0]["oco_group"] == paired[1]["oco_group"]


async def test_market_entry_with_stop_loss_and_take_profit(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    entry = await order(auth_client, stop_loss=95, take_profit=110)
    assert entry["status"] == "filled" and entry["bracket_stop_loss"] == 95
    protective = [o for o in (await orders(auth_client)).values() if o["status"] == "open"]
    assert sorted((o["note"], o["stop_price"] or o["limit_price"]) for o in protective) == [
        ("Stop-loss", 95),
        ("Take-profit", 110),
    ]
    assert all(o["quantity"] == pytest.approx(10) and o["reduce_only"] for o in protective)


async def test_entry_bracket_is_all_or_nothing(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    wrong_side = await order(auth_client, expect=422, stop_loss=105)
    assert "below the entry price" in wrong_side["error"]["message"]
    # Valid sides, but a stop-loss under the minimum order size: the entry is rolled back with it.
    tiny = await order(auth_client, expect=422, quantity=0.5, stop_loss=0.1)
    assert "Stop-loss rejected" in tiny["error"]["message"]
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"] == [] and (await auth_client.get(f"{API}/orders")).json() == []


async def test_resting_limit_entry_gets_its_protection_when_it_fills(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    entry = await order(auth_client, order_type="limit", limit_price=95, stop_loss=90, take_profit=105)
    assert entry["status"] == "open"
    assert [o for o in (await orders(auth_client)).values() if o["reduce_only"]] == []  # nothing until it fills
    await provider.set_price("SOL-USD", 94.0)
    now = await orders(auth_client)
    assert now[entry["id"]]["status"] == "filled"
    assert sorted(o["note"] for o in now.values() if o["reduce_only"] and o["status"] == "open") == ["Stop-loss", "Take-profit"]


async def test_short_entry_bracket_and_bracket_rules(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    limits = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True}
    await auth_client.put(f"{API}/portfolio/risk-limits", json=limits)
    short = await order(auth_client, side="sell", stop_loss=106, take_profit=90)
    assert short["status"] == "filled"
    sl = next(o for o in (await orders(auth_client)).values() if o["note"] == "Stop-loss")
    assert sl["side"] == "buy" and sl["stop_price"] == 106
    # Covering reduces the position: it can't carry a bracket of its own.
    cover = await order(auth_client, expect=422, side="buy", quantity=5, stop_loss=90)
    assert "open or add to a position" in cover["error"]["message"]
    await order(auth_client, expect=422, side="sell", order_type="stop", stop_price=90, stop_loss=110)  # market/limit only


async def test_limit_entry_whose_stop_was_gapped_past_still_fills_and_says_so(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    entry = await order(auth_client, order_type="limit", limit_price=95, stop_loss=92)
    await provider.set_price("SOL-USD", 91.0)  # fills the 95 limit, but 91 is already below the 92 stop
    filled = (await orders(auth_client))[entry["id"]]
    assert filled["status"] == "filled" and "was not attached" in filled["note"]
    note = (await auth_client.get("/api/v1/notifications")).json()["notifications"][0]
    assert "was not attached" in note["message"]


async def limits(client, **body) -> dict:  # type: ignore[no-untyped-def]
    payload = {"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True} | body
    resp = await client.put(f"{API}/portfolio/risk-limits", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_trade_plan_requires_a_stop_loss_on_new_positions(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    assert (await limits(auth_client, require_stop_loss=True))["risk_limits"]["require_stop_loss"] is True

    rejected = await order(auth_client)
    assert rejected["status"] == "rejected" and "need a stop-loss" in rejected["reject_reason"]
    stop_entry = await order(auth_client, order_type="stop", stop_price=120)
    assert stop_entry["status"] == "rejected" and "market or limit order" in stop_entry["reject_reason"]
    short = await order(auth_client, side="sell")
    assert short["status"] == "rejected"

    assert (await order(auth_client, stop_loss=90))["status"] == "filled"
    # Reducing never needs a stop: partial sells, protective orders and closing all work.
    assert (await order(auth_client, side="sell", quantity=2))["status"] == "filled"
    assert all(o["status"] == "open" for o in await protect(auth_client, stop_loss=85, take_profit=130))
    assert (await order(auth_client, side="sell", quantity=8))["status"] == "filled"


async def test_trade_plan_caps_the_risk_of_each_trade(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    portfolio = await limits(auth_client, max_risk_per_trade_pct=1)
    assert portfolio["risk_limits"]["max_risk_per_trade_pct"] == 1
    no_stop = await order(auth_client)
    assert no_stop["status"] == "rejected" and "1% risk-per-trade limit" in no_stop["reject_reason"]

    # The loss if the stop fills, as the order ticket estimates it: slippage on both fills, fees both ways.
    slip, fee = 0.0005, 0.001
    entry, stop_fill = 100 * (1 + slip), 90 * (1 - slip)
    per_unit = entry - stop_fill + (entry + stop_fill) * fee
    allowed = portfolio["equity"] * 0.01
    too_big = await order(auth_client, quantity=allowed / per_unit * 1.01, stop_loss=90)
    assert too_big["status"] == "rejected" and "your limit is 1%" in too_big["reject_reason"]
    sized = await order(auth_client, quantity=allowed / per_unit, stop_loss=90)  # exactly at the limit: allowed
    assert sized["status"] == "filled", sized["reject_reason"]

    # A short is capped the same way, with its stop above the entry.
    short = await order(auth_client, symbol="ETH-USD", side="sell", quantity=1000, stop_loss=1e9)
    assert short["status"] == "rejected" and "Hitting the stop-loss would lose" in short["reject_reason"]

    # Turning the limit off lifts it.
    await limits(auth_client)
    assert (await order(auth_client, quantity=1))["status"] == "filled"


async def test_trade_plan_validation(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    resp = await auth_client.put(f"{API}/portfolio/risk-limits", json={
        "max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 5, "max_risk_per_trade_pct": 20})  # fmt: skip
    assert resp.status_code == 422


async def portfolio(client) -> dict:  # type: ignore[no-untyped-def]
    resp = await client.get(f"{API}/portfolio")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_open_risk_is_measured_to_the_resting_stops(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    slip, fee = 0.0005, 0.001
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    pf = await portfolio(auth_client)
    (pos,) = pf["positions"]
    assert (pos["stop_price"], pos["risk_to_stop"], pos["unprotected_qty"]) == (None, None, 10)
    assert pf["open_risk"] == 0 and pf["unprotected_positions"] == 1

    await protect(auth_client, stop_loss=90, take_profit=130)
    fill = 90 * (1 - slip)
    pf = await portfolio(auth_client)
    (pos,) = pf["positions"]
    assert pos["stop_price"] == 90 and pos["unprotected_qty"] == 0 and pf["unprotected_positions"] == 0
    assert pos["risk_to_stop"] == pytest.approx(10 * (100 - fill + fill * fee))
    assert pf["open_risk"] == pytest.approx(pos["risk_to_stop"])
    assert pf["open_risk_pct"] == pytest.approx(pf["open_risk"] / pf["equity"] * 100)

    # Measured from the current price: a rally puts more of the open profit at risk.
    await provider.set_price("SOL-USD", 110.0)
    assert (await portfolio(auth_client))["open_risk"] == pytest.approx(10 * (110 - fill + fill * fee))

    # A second, farther stop on part of the position: the worst case counts it first.
    await order(auth_client, side="sell", order_type="stop", stop_price=80, quantity=4)
    (pos,) = (await portfolio(auth_client))["positions"]
    far = 80 * (1 - slip)
    assert pos["stop_price"] == 80
    assert pos["risk_to_stop"] == pytest.approx(4 * (110 - far + far * fee) + 6 * (110 - fill + fill * fee))


async def test_open_risk_of_a_short_and_on_the_dashboard(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await limits(auth_client)
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client, side="sell")
    await protect(auth_client, stop_loss=110)
    fill = 110 * 1.0005
    expected = 10 * (fill - 100 + fill * 0.001)
    assert (await portfolio(auth_client))["open_risk"] == pytest.approx(expected)
    dashboard = (await auth_client.get("/api/v1/dashboard")).json()
    assert dashboard["portfolio"]["open_risk"] == pytest.approx(expected)
