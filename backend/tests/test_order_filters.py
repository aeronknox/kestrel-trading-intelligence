"""Order history filters: by status and by asset, and open orders never crowded out by newer history."""

from tests.test_stop_orders import API, order


async def test_filter_by_status_and_symbol(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    await provider.set_price("BTC-USD", 50_000.0)
    await order(auth_client)  # filled SOL buy
    await order(auth_client, order_type="limit", limit_price=50)  # open SOL limit
    await order(auth_client, symbol="BTC-USD", quantity=0.01)  # filled BTC buy

    def ids(resp):  # type: ignore[no-untyped-def]
        assert resp.status_code == 200, resp.text
        return [(o["asset"]["symbol"], o["status"]) for o in resp.json()]

    assert ids(await auth_client.get(f"{API}/orders", params={"symbol": "SOL-USD"})) == [("SOL-USD", "open"), ("SOL-USD", "filled")]
    assert ids(await auth_client.get(f"{API}/orders", params={"symbol": "btc-usd"})) == [("BTC-USD", "filled")]  # any case
    assert ids(await auth_client.get(f"{API}/orders", params={"status": "filled", "symbol": "SOL-USD"})) == [("SOL-USD", "filled")]
    assert ids(await auth_client.get(f"{API}/orders", params={"symbol": "ETH-USD"})) == []
    assert (await auth_client.get(f"{API}/orders", params={"status": "nope"})).status_code == 422


async def test_an_old_open_order_is_listed_however_much_history_follows(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    old = await order(auth_client, order_type="limit", limit_price=10, quantity=1)
    for _ in range(3):
        await order(auth_client, quantity=0.1)
    latest_two = (await auth_client.get(f"{API}/orders", params={"limit": 2})).json()
    assert old["id"] not in [o["id"] for o in latest_two]  # pushed out of the recent history...
    open_now = (await auth_client.get(f"{API}/orders", params={"status": "open"})).json()
    assert [o["id"] for o in open_now] == [old["id"]]  # ...but the open-orders query still finds it
