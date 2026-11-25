"""Rebalancing the paper portfolio to target weights (simulated market orders)."""

import pytest

API = "/api/v1/paper"


async def setup(client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    await provider.set_price("ETH-USD", 2_000.0)
    await provider.set_price("SOL-USD", 100.0)
    # $10k of BTC, nothing else; $100k account.
    resp = await client.post(f"{API}/orders", json={"symbol": "BTC-USD", "side": "buy", "order_type": "market", "quantity": 0.2})
    assert resp.json()["status"] == "filled"


async def test_preview_then_rebalance(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await setup(auth_client, provider)
    body = {"targets": [{"symbol": "BTC-USD", "pct": 5}, {"symbol": "ETH-USD", "pct": 20}]}
    plan = (await auth_client.post(f"{API}/rebalance/preview", json=body)).json()
    legs = {leg["symbol"]: leg for leg in plan["legs"]}
    assert [leg["side"] for leg in plan["legs"]] == ["sell", "buy"]  # sells first
    assert legs["BTC-USD"]["value"] == pytest.approx(plan["equity"] * 0.10 - plan["equity"] * 0.05, rel=0.01)
    assert legs["ETH-USD"]["target_pct"] == 20 and legs["ETH-USD"]["current_pct"] == 0
    assert 70 < plan["cash_after_pct"] < 80
    # A preview places nothing.
    assert len((await auth_client.get(f"{API}/orders")).json()) == 1

    done = (await auth_client.post(f"{API}/rebalance", json=body)).json()
    assert done["message"] == "Rebalanced: 2 of 2 orders filled"
    assert all(o["note"] == "Rebalance" for o in done["orders"])
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    alloc = {p["asset"]["symbol"]: p["market_value"] / pf["equity"] * 100 for p in pf["positions"]}
    assert alloc["BTC-USD"] == pytest.approx(5, abs=0.1) and alloc["ETH-USD"] == pytest.approx(20, abs=0.1)

    # Close to target already: nothing to do.
    again = (await auth_client.post(f"{API}/rebalance/preview", json=body)).json()
    assert again["legs"] == [] and set(again["unchanged"]) == {"BTC-USD", "ETH-USD"}
    assert (await auth_client.post(f"{API}/rebalance", json=body)).status_code == 422


async def test_zero_sells_everything_and_unlisted_assets_are_untouched(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await setup(auth_client, provider)
    await auth_client.post(f"{API}/orders", json={"symbol": "SOL-USD", "side": "buy", "order_type": "market", "quantity": 10})
    await auth_client.post(f"{API}/rebalance", json={"targets": [{"symbol": "BTC-USD", "pct": 0}]})
    symbols = [p["asset"]["symbol"] for p in (await auth_client.get(f"{API}/portfolio")).json()["positions"]]
    assert symbols == ["SOL-USD"]


async def test_targets_are_validated(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await setup(auth_client, provider)

    async def err(targets: list[dict]) -> str:  # type: ignore[type-arg]
        resp = await auth_client.post(f"{API}/rebalance/preview", json={"targets": targets})
        assert resp.status_code == 422, resp.text
        return resp.text

    assert "position-size limit" in await err([{"symbol": "BTC-USD", "pct": 30}])  # default limit 25%
    assert "at most 100%" in await err([{"symbol": s, "pct": 25} for s in ("BTC-USD", "ETH-USD", "SOL-USD", "LTC-USD", "ADA-USD")])
    assert "only once" in await err([{"symbol": "BTC-USD", "pct": 5}, {"symbol": "btc-usd", "pct": 6}])
    await err([])
