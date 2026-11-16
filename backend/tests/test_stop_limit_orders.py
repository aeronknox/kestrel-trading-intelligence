"""Stop-limit orders: a stop that, once reached, rests as a limit order, so a fast move can't fill it far past the stop."""

import pytest

from tests.test_stop_orders import API, order, orders

SLIP, FEE = 0.0005, 0.001


async def test_sell_stop_limit_triggers_then_fills_no_worse_than_its_limit(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl = await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93)
    assert (sl["status"], sl["stop_price"], sl["limit_price"], sl["triggered_at"]) == ("open", 95, 93, None)

    await provider.set_price("SOL-USD", 97.0)  # above the stop: nothing happens
    assert (await orders(auth_client))[sl["id"]]["triggered_at"] is None

    await provider.set_price("SOL-USD", 94.0)  # through the stop, still above the limit: fills like a stop
    filled = (await orders(auth_client))[sl["id"]]
    assert filled["status"] == "filled" and filled["triggered_at"] is not None
    assert filled["filled_price"] == pytest.approx(94 * (1 - SLIP))
    assert (await auth_client.get(f"{API}/portfolio")).json()["positions"] == []


async def test_a_gap_past_the_limit_leaves_it_resting_as_a_limit_order(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl = await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93)

    await provider.set_price("SOL-USD", 90.0)  # gapped through both: triggered, but no fill below 93
    gapped = (await orders(auth_client))[sl["id"]]
    assert gapped["status"] == "open" and gapped["triggered_at"] is not None
    assert (await auth_client.get(f"{API}/portfolio")).json()["positions"][0]["quantity"] == pytest.approx(10)

    await provider.set_price("SOL-USD", 92.0)  # still below the limit
    assert (await orders(auth_client))[sl["id"]]["status"] == "open"

    # Back above the stop: once triggered it stays a limit order, so it now fills (at the market, above its limit).
    await provider.set_price("SOL-USD", 96.0)
    filled = (await orders(auth_client))[sl["id"]]
    assert filled["status"] == "filled" and filled["filled_price"] == pytest.approx(96 * (1 - SLIP))


async def test_buy_stop_limit_reserves_cash_at_its_limit_and_caps_the_fill(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    before = (await auth_client.get(f"{API}/portfolio")).json()["available_cash"]
    sl = await order(auth_client, order_type="stop_limit", stop_price=110, limit_price=112)
    after = (await auth_client.get(f"{API}/portfolio")).json()["available_cash"]
    assert before - after == pytest.approx(10 * 112 * (1 + FEE))  # never fills above 112

    await provider.set_price("SOL-USD", 111.99)  # breakout; with slippage the fill would pass 112, so it's capped
    filled = (await orders(auth_client))[sl["id"]]
    assert filled["status"] == "filled" and filled["filled_price"] == pytest.approx(112)


async def test_stop_limit_validation(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sell = {"side": "sell", "order_type": "stop_limit"}
    assert "limit price" in (await order(auth_client, 422, **sell, stop_price=95))["error"]["message"]
    assert "stop price" in (await order(auth_client, 422, **sell, limit_price=93))["error"]["message"]
    wrong_side = await order(auth_client, 422, **sell, stop_price=95, limit_price=96)
    assert "at or below its stop" in wrong_side["error"]["message"]
    assert "at or above its stop" in (await order(auth_client, 422, order_type="stop_limit", stop_price=110, limit_price=109))["error"]["message"]
    assert "would trigger at once" in (await order(auth_client, 422, **sell, stop_price=101, limit_price=100))["error"]["message"]
    # A limit equal to the stop is allowed, and so is an expiry.
    ok = await order(auth_client, **sell, stop_price=95, limit_price=95, expires_in_hours=24)
    assert ok["status"] == "open" and ok["expires_at"] is not None


async def test_open_risk_counts_a_stop_limit_at_its_limit(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93, reduce_only=True)
    (pos,) = (await auth_client.get(f"{API}/portfolio")).json()["positions"]
    assert pos["stop_price"] == 95 and pos["unprotected_qty"] == pytest.approx(0)
    assert pos["risk_to_stop"] == pytest.approx(10 * ((100 - 93) + 93 * FEE))


async def test_journal_measures_r_from_a_stop_limit(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93, reduce_only=True)
    await provider.set_price("SOL-USD", 110.0)
    await order(auth_client, side="sell", order_type="market", quantity=10)
    (trip,) = (await auth_client.get(f"{API}/journal")).json()["trips"]
    assert (trip["initial_stop"], trip["stop_source"]) == (95, "stop order")
    assert trip["r_multiple"] > 1.5  # risked ~5 a unit, made ~10


async def test_a_gap_past_the_limit_is_notified_once(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    async def notes() -> list[dict]:
        await auth_client.get(f"{API}/portfolio")  # runs order matching, as the background job does
        return (await auth_client.get("/api/v1/notifications")).json()["notifications"]

    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93, reduce_only=True)
    await provider.set_price("SOL-USD", 90.0)
    (n,) = await notes()
    assert n["kind"] == "order_triggered" and n["title"] == "Stop-limit sell triggered, not filled · SOL-USD"
    assert "reached its stop (95.00), but the price (90.00) is already below its limit (93.00)" in n["message"]
    assert "the position is not protected" in n["message"]

    await provider.set_price("SOL-USD", 91.0)  # still waiting: no repeat
    assert len(await notes()) == 1
    await provider.set_price("SOL-USD", 94.0)  # back above the limit: it fills, and that is notified as usual
    assert [x["kind"] for x in await notes()] == ["order_filled", "order_triggered"]


async def test_a_stop_limit_that_fills_when_triggered_sends_only_the_fill(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93)
    await provider.set_price("SOL-USD", 94.0)
    await auth_client.get(f"{API}/portfolio")
    kinds = [x["kind"] for x in (await auth_client.get("/api/v1/notifications")).json()["notifications"]]
    assert kinds == ["order_filled"]
