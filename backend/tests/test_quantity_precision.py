"""Quantities are stored to 10 decimal places: closing a position in parts must still close the journal trip."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models.enums import OrderSide
from app.paper_trading.round_trips import round_trips
from tests.test_stop_orders import API, order


def _trade(i: int, side: OrderSide, qty: float, closing: bool):  # type: ignore[no-untyped-def]
    return SimpleNamespace(id=i, order_id=i, asset_id=1, asset=SimpleNamespace(symbol="ETH-USD"), side=side, quantity=qty,
                           price=100.0, fee=0.0, realized_pnl=0.0, is_closing=closing,
                           executed_at=datetime(2026, 11, 16, tzinfo=UTC) + timedelta(minutes=i))  # fmt: skip


def test_a_position_closed_in_halves_is_flat_despite_rounding() -> None:
    # Half of 1.2345678901 has an 11th decimal; stored, each half rounds up: 1e-10 more is sold than was bought.
    trades = [_trade(1, OrderSide.BUY, 1.2345678901, False), _trade(2, OrderSide.SELL, 0.6172839451, True),
              _trade(3, OrderSide.SELL, 0.6172839451, True)]  # fmt: skip
    (trip,) = round_trips(trades)  # type: ignore[arg-type]
    assert trip.closed_at is not None and not trip.is_open
    # The next buy opens a new trip rather than continuing the old one.
    assert len(round_trips([*trades, _trade(4, OrderSide.BUY, 1.0, False)])) == 2  # type: ignore[arg-type]


async def test_order_quantities_are_rounded_to_the_stored_precision(auth_client, provider) -> None:  # type: ignore[no-untyped-def]
    await provider.set_price("SOL-USD", 100.0)
    o = await order(auth_client, quantity=1.23456789012345)
    assert o["quantity"] == pytest.approx(1.2345678901, abs=1e-15)
    # Selling half (an 11th decimal) and then the rest leaves no position and a closed journal trip.
    await order(auth_client, side="sell", quantity=0.617283945062)
    pos = (await auth_client.get(f"{API}/portfolio")).json()["positions"][0]["quantity"]
    await order(auth_client, side="sell", quantity=pos)
    assert (await auth_client.get(f"{API}/portfolio")).json()["positions"] == []
    (trip,) = (await auth_client.get(f"{API}/journal")).json()["trips"]
    assert trip["closed_at"] is not None
