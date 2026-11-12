"""Group simulated fills into round trips: from flat, into a position, and back to flat.

A trip is identified by its opening fill. Its P&L is the sum of the closing fills' realized P&L,
which already includes every fee (opening fees are part of the average entry price). Positions
can't flip from long to short in one order, so each trip is entirely long or entirely short.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.models.enums import OrderSide
from app.models.paper import SimulatedTrade

QTY_EPSILON = 1e-12


@dataclass
class RoundTrip:
    trade_id: int  # the opening fill (journal entries attach here)
    symbol: str
    side: str  # "long" | "short"
    opened_at: datetime
    closed_at: datetime | None = None
    quantity: float = 0.0  # largest size held during the trip
    entry_cost: float = 0.0  # sum of entry notional
    entry_qty: float = 0.0
    exit_value: float = 0.0
    exit_qty: float = 0.0
    pnl: float = 0.0
    fees: float = 0.0
    fills: int = 0
    order_ids: list[int] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def entry_price(self) -> float:
        return self.entry_cost / self.entry_qty if self.entry_qty else 0.0

    @property
    def exit_price(self) -> float | None:
        return self.exit_value / self.exit_qty if self.exit_qty else None

    @property
    def pnl_pct(self) -> float | None:
        """Realized P&L relative to what was put in (entry notional)."""
        return self.pnl / self.entry_cost * 100 if self.entry_cost and not self.is_open else None

    @property
    def holding_seconds(self) -> float | None:
        return (self.closed_at - self.opened_at).total_seconds() if self.closed_at else None


def round_trips(trades: list[SimulatedTrade]) -> list[RoundTrip]:
    """Trips oldest first; `trades` must be in execution order. The last trip per asset may be open."""
    held: dict[int, float] = {}
    current: dict[int, RoundTrip] = {}
    trips: list[RoundTrip] = []
    for t in trades:
        q = held.get(t.asset_id, 0.0)
        signed = t.quantity if t.side == OrderSide.BUY else -t.quantity
        trip = current.get(t.asset_id)
        if trip is None or abs(q) <= QTY_EPSILON:
            trip = RoundTrip(trade_id=t.id, symbol=t.asset.symbol, side="long" if signed > 0 else "short", opened_at=t.executed_at)
            current[t.asset_id] = trip
            trips.append(trip)
        trip.fills += 1
        trip.fees += t.fee
        trip.order_ids.append(t.order_id)
        if t.is_closing:
            trip.exit_value += t.quantity * t.price
            trip.exit_qty += t.quantity
            trip.pnl += t.realized_pnl
        else:
            trip.entry_cost += t.quantity * t.price
            trip.entry_qty += t.quantity
        q += signed
        held[t.asset_id] = q
        trip.quantity = max(trip.quantity, abs(q))
        if abs(q) <= QTY_EPSILON:
            trip.closed_at = t.executed_at
            del current[t.asset_id]
    return trips
