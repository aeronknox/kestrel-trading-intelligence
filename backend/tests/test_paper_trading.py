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


async def _limits(client, max_position_pct: float = 100) -> None:  # type: ignore[no-untyped-def]
    resp = await client.put(
        f"{API}/portfolio/risk-limits",
        json={"max_position_pct": max_position_pct, "max_open_positions": 10, "daily_loss_limit_pct": 5},
    )
    assert resp.status_code == 200


async def test_open_limit_buys_reserve_cash(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _limits(auth_client)
    await provider.set_price("SOL-USD", 100.0)
    first = await _order(auth_client, symbol="SOL-USD", order_type="limit", quantity=600, limit_price=90)
    assert first["status"] == "open"
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["reserved_cash"] == pytest.approx(600 * 90 * 1.001)
    assert pf["available_cash"] == pytest.approx(pf["cash_balance"] - pf["reserved_cash"])

    # Together with the first order this would commit more cash than the portfolio holds.
    second = await _order(auth_client, symbol="SOL-USD", order_type="limit", quantity=600, limit_price=90)
    assert second["status"] == "rejected" and "reserved by open orders" in second["reject_reason"]
    await provider.set_price("ETH-USD", 3000.0)
    market = await _order(auth_client, symbol="ETH-USD", quantity=20)  # $60k > $46k available
    assert market["status"] == "rejected" and "Insufficient" in market["reject_reason"]

    await auth_client.post(f"{API}/orders/{first['id']}/cancel")
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["reserved_cash"] == 0
    again = await _order(auth_client, symbol="SOL-USD", order_type="limit", quantity=600, limit_price=90)
    assert again["status"] == "open"


async def test_open_limit_sells_reserve_quantity(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _limits(auth_client)
    await provider.set_price("BTC-USD", 50_000.0)
    assert (await _order(auth_client, quantity=0.5))["status"] == "filled"
    resting = await _order(auth_client, side="sell", order_type="limit", quantity=0.4, limit_price=60_000)
    assert resting["status"] == "open"
    oversell = await _order(auth_client, side="sell", quantity=0.2)
    assert oversell["status"] == "rejected" and "reserved by open sell orders" in oversell["reject_reason"]
    assert (await _order(auth_client, side="sell", quantity=0.1))["status"] == "filled"


async def test_exposure_limits_rechecked_when_resting_buy_fills(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    resting = await _order(auth_client, symbol="SOL-USD", order_type="limit", quantity=200, limit_price=95)
    assert resting["status"] == "open"  # 19% of equity: within the 25% limit
    # A later market buy grows the position, so filling the resting order would breach the limit.
    assert (await _order(auth_client, symbol="SOL-USD", quantity=100))["status"] == "filled"

    await provider.set_price("SOL-USD", 94.0)
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    order = next(o for o in (await auth_client.get(f"{API}/orders")).json() if o["id"] == resting["id"])
    assert order["status"] == "rejected"
    assert order["reject_reason"].startswith("At fill time:") and "limit is 25%" in order["reject_reason"]
    assert pf["positions"][0]["quantity"] == pytest.approx(100)
    assert pf["reserved_cash"] == 0


async def test_concurrent_first_portfolio_creation_reuses_winner(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import func, select

    from app.database.session import get_sessionmaker
    from app.models.paper import PaperPortfolio
    from app.paper_trading.service import PaperTradingService

    me = (await auth_client.get("/api/v1/auth/me")).json()
    winner = (await auth_client.get(f"{API}/portfolio")).json()

    async with get_sessionmaker()() as session:
        # Simulate losing the race: the first lookup misses, as if the other request had not committed yet.
        real_scalar = session.scalar
        calls = 0

        async def racing_scalar(stmt, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return None if calls == 1 else await real_scalar(stmt, *args, **kwargs)

        session.scalar = racing_scalar  # type: ignore[method-assign]
        pf = await PaperTradingService(session).get_or_create_portfolio(me["id"])
        session.scalar = real_scalar  # type: ignore[method-assign]
        assert pf.id == winner["id"]
        count = await session.scalar(
            select(func.count()).select_from(PaperPortfolio).where(PaperPortfolio.user_id == me["id"])
        )
        assert count == 1


# --------------------------------------------------------------- short selling
async def _allow_short(client, max_position_pct: float = 100) -> None:  # type: ignore[no-untyped-def]
    resp = await client.put(
        f"{API}/portfolio/risk-limits",
        json={"max_position_pct": max_position_pct, "max_open_positions": 10, "daily_loss_limit_pct": 50, "allow_short": True},
    )
    assert resp.status_code == 200 and resp.json()["risk_limits"]["allow_short"] is True


def _identity(pf: dict) -> None:
    assert pf["equity"] - pf["starting_balance"] == pytest.approx(pf["realized_pnl"] + pf["unrealized_pnl"], abs=1e-6)


async def test_short_open_mark_and_cover_accounting(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _allow_short(auth_client)
    await provider.set_price("BTC-USD", 50_000.0)
    short = await _order(auth_client, side="sell", quantity=0.2)
    assert short["status"] == "filled"
    entry = 50_000 * (1 - 0.0005)  # sells fill below the price
    fee = 0.2 * entry * 0.001
    assert short["filled_price"] == pytest.approx(entry)
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    pos = pf["positions"][0]
    assert pos["side"] == "short" and pos["quantity"] == pytest.approx(-0.2)
    assert pf["cash_balance"] == pytest.approx(100_000 + 0.2 * entry - fee)  # proceeds credited
    assert pf["short_liability"] == pytest.approx(0.2 * 50_000)
    assert pf["available_cash"] == pytest.approx(pf["cash_balance"] - 2 * 0.2 * 50_000)  # proceeds can't be spent
    _identity(pf)

    await provider.set_price("BTC-USD", 45_000.0)  # the short profits when price falls
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["unrealized_pnl"] > 0 and pf["positions"][0]["unrealized_pnl_pct"] > 0
    _identity(pf)

    cover = await _order(auth_client, side="buy", quantity=0.2)
    assert cover["status"] == "filled" and cover["filled_price"] == pytest.approx(45_000 * 1.0005)
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"] == [] and pf["unrealized_pnl"] == 0
    avg = (0.2 * entry - fee) / 0.2
    expected = (avg - 45_000 * 1.0005) * 0.2 - 0.2 * 45_000 * 1.0005 * 0.001
    assert pf["realized_pnl"] == pytest.approx(expected)
    _identity(pf)
    analytics = (await auth_client.get(f"{API}/analytics")).json()
    assert analytics["closed_trades"] == 1 and analytics["win_rate"] == 100  # the cover counts as a closed trade


async def test_short_selling_is_off_by_default_and_orders_cannot_flip(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("BTC-USD", 50_000.0)
    off = await _order(auth_client, side="sell", quantity=0.1)
    assert off["status"] == "rejected" and "short selling is disabled" in off["reject_reason"]
    await _allow_short(auth_client)
    assert (await _order(auth_client, quantity=0.1))["status"] == "filled"
    flip = await _order(auth_client, side="sell", quantity=0.3)
    assert flip["status"] == "rejected" and "close the long before going short" in flip["reject_reason"]
    assert (await _order(auth_client, side="sell", quantity=0.1))["status"] == "filled"  # flat again
    assert (await _order(auth_client, side="sell", quantity=0.1))["status"] == "filled"  # now short
    flip_back = await _order(auth_client, side="buy", quantity=0.3)
    assert flip_back["status"] == "rejected" and "close the short before going long" in flip_back["reject_reason"]


async def test_short_proceeds_do_not_fund_longs(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _allow_short(auth_client)
    await provider.set_price("BTC-USD", 50_000.0)
    await provider.set_price("ETH-USD", 1_000.0)
    assert (await _order(auth_client, side="sell", quantity=0.5))["status"] == "filled"  # $25k short
    # Buying power is ~$75k: the $25k of proceeds plus $25k of margin are set aside.
    too_big = await _order(auth_client, symbol="ETH-USD", quantity=80)
    assert too_big["status"] == "rejected" and "buying power" in too_big["reject_reason"]
    assert (await _order(auth_client, symbol="ETH-USD", quantity=70))["status"] == "filled"


async def test_resting_short_sale_reserves_margin(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _allow_short(auth_client)
    await provider.set_price("SOL-USD", 100.0)
    rest = await _order(auth_client, symbol="SOL-USD", side="sell", order_type="limit", quantity=500, limit_price=110)
    assert rest["status"] == "open"
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["reserved_cash"] == pytest.approx(500 * 110 * 1.001)
    await provider.set_price("SOL-USD", 111.0)
    pf = (await auth_client.get(f"{API}/portfolio")).json()  # triggers matching
    assert pf["positions"][0]["side"] == "short" and pf["reserved_cash"] == 0
    filled = next(o for o in (await auth_client.get(f"{API}/orders")).json() if o["id"] == rest["id"])
    assert filled["status"] == "filled" and filled["filled_price"] >= 110


async def test_margin_call_covers_when_price_doubles(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _allow_short(auth_client, max_position_pct=25)
    await provider.set_price("BTC-USD", 50_000.0)
    assert (await _order(auth_client, side="sell", quantity=0.2))["status"] == "filled"
    await provider.set_price("BTC-USD", 99_000.0)
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"][0]["side"] == "short"  # not yet twice the entry
    await provider.set_price("BTC-USD", 101_000.0)
    pf = (await auth_client.get(f"{API}/portfolio")).json()
    assert pf["positions"] == []
    cover = (await auth_client.get(f"{API}/orders")).json()[0]
    assert cover["side"] == "buy" and cover["status"] == "filled" and cover["note"].startswith("Margin call")
    assert pf["realized_pnl"] < -9_000  # the short lost about its full value
    _identity(pf)


async def test_short_selling_cannot_be_disabled_with_open_shorts(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await _allow_short(auth_client)
    await provider.set_price("BTC-USD", 50_000.0)
    await _order(auth_client, side="sell", quantity=0.1)
    resp = await auth_client.put(f"{API}/portfolio/risk-limits", json={"max_position_pct": 25, "max_open_positions": 10, "daily_loss_limit_pct": 5, "allow_short": False})
    assert resp.status_code == 422 and "Cover your open shorts" in resp.json()["error"]["message"]
