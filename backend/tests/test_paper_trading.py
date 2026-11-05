import pytest

API = "/api/v1/paper"


async def _order(client, **body):  # type: ignore[no-untyped-def]
    payload = {"symbol": "BTC-USD", "side": "buy", "order_type": "market", "quantity": 0.1} | body
    resp = await client.post(f"{API}/orders", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_starting_portfolio(auth_client) -> None:  # type: ignore[no-untyped-def]
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["simulated"] is True
    assert pf["equity"] == pytest.approx(100_000)
    assert pf["positions"] == []


async def test_buy_sell_pnl_accounting(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    buy = await _order(auth_client, quantity=0.2)
    assert buy["status"] == "filled"
    # Slippage 5 bps, fee 10 bps
    assert buy["filled_price"] == pytest.approx(50_000 * 1.0005)
    assert buy["fee"] == pytest.approx(0.2 * 50_000 * 1.0005 * 0.001)

    await provider.set_price("BTC-USD", 55_000.0)
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    pos = pf["positions"][0]
    assert pos["quantity"] == pytest.approx(0.2)
    # Identity: equity - start == realized + unrealized
    assert pf["equity"] - pf["starting_balance"] == pytest.approx(pf["realized_pnl"] + pf["unrealized_pnl"])

    sell = await _order(auth_client, side="sell", quantity=0.2)
    assert sell["status"] == "filled"
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"] == []
    assert pf["unrealized_pnl"] == 0
    assert pf["realized_pnl"] > 0
    assert pf["equity"] == pytest.approx(pf["starting_balance"] + pf["realized_pnl"])
    trades = (await auth_client.get(f"{API}/trades")).json()
    assert len(trades) == 2


async def test_short_selling_rejected(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("ETH-USD", 3000.0)
    order = await _order(auth_client, symbol="ETH-USD", side="sell", quantity=1)
    assert order["status"] == "rejected"
    assert "short selling" in order["reject_reason"]


async def test_position_size_and_cash_limits(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    too_big = await _order(auth_client, quantity=1.0)  # 50% of equity > 25% default limit
    assert too_big["status"] == "rejected" and "limit" in too_big["reject_reason"]
    resp = await auth_client.put(
        f"{API}/portfolio/risk-limits", json={"max_position_pct": 100, "max_open_positions": 10, "daily_loss_limit_pct": 5}
    )
    assert resp.status_code == 200
    no_cash = await _order(auth_client, quantity=3.0)
    assert no_cash["status"] == "rejected" and "Insufficient" in no_cash["reject_reason"]


async def test_limit_order_rests_then_fills(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    order = await _order(auth_client, symbol="SOL-USD", order_type="limit", quantity=10, limit_price=90)
    assert order["status"] == "open"
    open_orders = (await auth_client.get(f"{API}/orders", params={"status": "open"})).json()
    assert [o["id"] for o in open_orders] == [order["id"]]

    await provider.set_price("SOL-USD", 89.0)
    pf = (await auth_client.get(f"{API}/portfolio")).json()  # triggers matching
    assert pf["positions"][0]["asset"]["symbol"] == "SOL-USD"
    filled = (await auth_client.get(f"{API}/orders")).json()[0]
    assert filled["status"] == "filled"
    assert filled["filled_price"] <= 90


async def test_cancel_order(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    order = await _order(auth_client, symbol="SOL-USD", order_type="limit", quantity=10, limit_price=50)
    resp = await auth_client.post(f"{API}/orders/{order['id']}/cancel")
    assert resp.json()["status"] == "cancelled"
    again = await auth_client.post(f"{API}/orders/{order['id']}/cancel")
    assert again.status_code == 422


async def test_reset_portfolio(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    await _order(auth_client, quantity=0.1)
    pf = (await auth_client.post(f"{API}/portfolio/reset")).json()
    assert pf["cash_balance"] == pytest.approx(100_000) and pf["positions"] == []
    assert (await auth_client.get(f"{API}/trades")).json() == []


async def test_invalid_orders(auth_client) -> None:  # type: ignore[no-untyped-def]
    resp = await auth_client.post(f"{API}/orders", json={"symbol": "BTC-USD", "side": "buy", "quantity": -1})
    assert resp.status_code == 422
    resp = await auth_client.post(f"{API}/orders", json={"symbol": "NOPE-USD", "side": "buy", "quantity": 1})
    assert resp.status_code == 404
    resp = await auth_client.post(f"{API}/orders", json={"symbol": "BTC-USD", "side": "buy", "order_type": "limit", "quantity": 1})
    assert resp.status_code == 422
