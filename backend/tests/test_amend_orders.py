"""Changing a resting paper order in place: its size, limit, stop or trail, with the checks of placing it."""

import pytest

from tests.test_stop_orders import API, order, orders, protect

FEE = 0.001


async def amend(client, order_id: int, expect: int = 200, **body):  # type: ignore[no-untyped-def]
    resp = await client.patch(f"{API}/orders/{order_id}", json=body)
    assert resp.status_code == expect, resp.text
    return resp.json()


async def test_move_a_stop_loss_up_and_the_journal_keeps_the_first_stop(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl, tp = await protect(auth_client, stop_loss=90, take_profit=120)
    moved = await amend(auth_client, sl["id"], stop_price=98)
    assert (moved["stop_price"], moved["status"], moved["oco_group"], moved["note"]) == (98, "open", sl["oco_group"], "Stop-loss")

    await provider.set_price("SOL-USD", 97.0)  # the moved stop fires; its pair is cancelled
    after = await orders(auth_client)
    assert after[sl["id"]]["status"] == "filled" and after[tp["id"]]["status"] == "cancelled"
    (trip,) = (await auth_client.get(f"{API}/journal")).json()["trips"]
    assert trip["initial_stop"] == 90  # R is measured from where the stop started, not where it was moved


async def test_a_limit_moved_to_the_price_fills_at_once(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    lim = await order(auth_client, order_type="limit", limit_price=90, quantity=5)
    assert lim["status"] == "open"
    filled = await amend(auth_client, lim["id"], limit_price=101)
    assert filled["status"] == "filled" and filled["filled_price"] <= 101


async def test_quantity_change_rechecks_buying_power_and_reserves_the_new_size(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    lim = await order(auth_client, order_type="limit", limit_price=90, quantity=5)
    before = (await auth_client.get(f"{API}/portfolio")).json()["available_cash"]
    await amend(auth_client, lim["id"], quantity=10)
    after = (await auth_client.get(f"{API}/portfolio")).json()["available_cash"]
    assert before - after == pytest.approx(5 * 90 * (1 + FEE))
    # Far beyond the cash: refused, and the order is left exactly as it was.
    resp = await amend(auth_client, lim["id"], 422, quantity=100_000)
    assert "Insufficient virtual buying power" in resp["error"]["message"]
    assert (await orders(auth_client))[lim["id"]]["quantity"] == 10


async def test_refusals_leave_the_order_unchanged(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    stop = await order(auth_client, side="sell", order_type="stop", stop_price=90, reduce_only=True)
    assert "would trigger at once" in (await amend(auth_client, stop["id"], 422, stop_price=101))["error"]["message"]
    assert "have a limit price" in (await amend(auth_client, stop["id"], 422, limit_price=95))["error"]["message"]
    assert "Only trailing stops" in (await amend(auth_client, stop["id"], 422, trail_pct=5))["error"]["message"]
    assert "Nothing to change" in (await amend(auth_client, stop["id"], 422))["error"]["message"]
    assert (await orders(auth_client))[stop["id"]]["stop_price"] == 90
    # Reduce-only: can't grow past the position.
    assert "Cannot sell" in (await amend(auth_client, stop["id"], 422, quantity=11))["error"]["message"]
    # Only open orders, and only your own.
    await auth_client.post(f"{API}/orders/{stop['id']}/cancel")
    assert "Only open orders" in (await amend(auth_client, stop["id"], 422, stop_price=80))["error"]["message"]
    await amend(auth_client, 999_999, 404, stop_price=80)


async def test_stop_limit_amend_keeps_the_limit_on_the_right_side(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl = await order(auth_client, side="sell", order_type="stop_limit", stop_price=95, limit_price=93, reduce_only=True)
    assert "at or below its stop (95.00)" in (await amend(auth_client, sl["id"], 422, limit_price=96))["error"]["message"]
    both = await amend(auth_client, sl["id"], stop_price=97, limit_price=96)
    assert (both["stop_price"], both["limit_price"]) == (97, 96)
    # Once triggered (here a gap past the limit), the stop is history: only the limit can still move.
    await provider.set_price("SOL-USD", 90.0)
    assert (await orders(auth_client))[sl["id"]]["triggered_at"] is not None
    assert "already triggered" in (await amend(auth_client, sl["id"], 422, stop_price=92))["error"]["message"]
    filled = await amend(auth_client, sl["id"], limit_price=89)  # accept a lower price to get out
    assert filled["status"] == "filled"


async def test_trailing_stop_trail_changes_from_the_same_best_price(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    trail = await order(auth_client, side="sell", order_type="trailing_stop", trail_pct=10, reduce_only=True)
    await provider.set_price("SOL-USD", 110.0)
    await orders(auth_client)  # the anchor follows to 110
    tighter = await amend(auth_client, trail["id"], trail_pct=2)
    assert tighter["trail_pct"] == 2 and tighter["trail_anchor"] == 110 and tighter["stop_price"] == pytest.approx(107.8)
    assert "change its trail" in (await amend(auth_client, trail["id"], 422, stop_price=100))["error"]["message"]
    # Price slips to 108 (the best price stays 110): a 1% trail would put the stop at 108.90, above the price.
    await provider.set_price("SOL-USD", 108.0)
    assert "would trigger at once" in (await amend(auth_client, trail["id"], 422, trail_pct=1))["error"]["message"]


async def test_amending_one_of_an_oco_pair_doesnt_count_the_other_against_it(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await order(auth_client)
    sl, tp = await protect(auth_client, stop_loss=90, take_profit=120)
    moved = await amend(auth_client, tp["id"], limit_price=130)
    assert moved["limit_price"] == 130
    assert (await orders(auth_client))[sl["id"]]["status"] == "open"
