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
