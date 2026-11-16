"""Close everything: cancel every open order and close every position at market (simulated)."""

from tests.test_stop_orders import API, order, orders, protect


async def test_closes_longs_and_shorts_and_cancels_orders(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    resp = await auth_client.put(f"{API}/portfolio/risk-limits", json={"max_position_pct": 100, "max_open_positions": 10, "daily_loss_limit_pct": 50,
                                                                        "allow_short": True})  # fmt: skip
    assert resp.status_code == 200, resp.text
    await provider.set_price("SOL-USD", 100.0)
    await provider.set_price("BTC-USD", 50_000.0)
    await order(auth_client)  # long SOL
    await protect(auth_client, stop_loss=90, take_profit=120)
    await order(auth_client, symbol="BTC-USD", side="sell", quantity=0.01)  # short BTC
    entry = await order(auth_client, order_type="limit", limit_price=50, quantity=1)  # a resting entry

    resp = await auth_client.post(f"{API}/close-everything")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"] == "Closed 2 positions, cancelled 3 open orders"
    assert sorted((o["asset"]["symbol"], o["side"], o["status"]) for o in body["closed"]) == [
        ("BTC-USD", "buy", "filled"), ("SOL-USD", "sell", "filled")]  # fmt: skip
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"] == [] and pf["reserved_cash"] == 0
    after = await orders(auth_client)
    assert after[entry["id"]]["status"] == "cancelled" and after[entry["id"]]["note"] == "Cancelled: you closed everything"
    assert not [o for o in after.values() if o["status"] == "open"]


async def test_nothing_to_close(auth_client) -> None:  # type: ignore[no-untyped-def]
    body = (await auth_client.post(f"{API}/close-everything")).json()
    assert body == {"message": "No positions were open", "cancelled_orders": 0, "closed": []}
