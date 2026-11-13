"""Trading journal for simulated round trips: why a trade was taken, how it felt, what it taught,
and which setups and states of mind actually pay. Simulated paper trading only."""

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.paper import _service_and_portfolio
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.journal import JournalEntry
from app.models.paper import PaperPortfolio, SimulatedOrder, SimulatedTrade
from app.paper_trading.round_trips import STOP_TYPES, RoundTrip, initial_stop, round_trips
from app.schemas.common import ORMModel
from app.services.export import csv_response, safe_filename

router = APIRouter(prefix="/paper/journal", tags=["paper-trading"])

Emotion = Literal["calm", "confident", "anxious", "fearful", "greedy", "impatient", "fomo", "revenge", "bored"]
EMOTIONS: tuple[str, ...] = Emotion.__args__  # type: ignore[attr-defined]
MAX_TRADES = 5000
DISCLAIMER = "Simulated paper trades only. Past results, simulated or real, don't predict future ones."


class JournalIn(BaseModel):
    setup: str | None = Field(None, max_length=40, description="Name of the setup, e.g. 'Breakout'")
    emotion: Emotion | None = None
    rating: int | None = Field(None, ge=1, le=5, description="How well the plan was followed, 1-5")
    notes: str = Field("", max_length=4000)
    lesson: str = Field("", max_length=2000)
    planned_stop: float | None = Field(None, gt=0, description="Where you planned to exit at a loss, for R-multiples")

    @field_validator("setup")
    @classmethod
    def _tidy(cls, v: str | None) -> str | None:
        v = " ".join(v.split()) if v else None
        return v or None


class JournalOut(ORMModel):
    setup: str | None
    emotion: str | None
    rating: int | None
    notes: str
    lesson: str
    planned_stop: float | None
    updated_at: datetime


class TripOut(BaseModel):
    trade_id: int
    symbol: str
    side: str
    opened_at: datetime
    closed_at: datetime | None
    quantity: float
    entry_price: float
    exit_price: float | None
    pnl: float | None  # None while the trip is open
    pnl_pct: float | None
    fees: float
    holding_seconds: float | None
    fills: int
    initial_stop: float | None
    stop_source: Literal["journal", "bracket", "stop order"] | None
    risk: float | None  # what the initial stop stood to lose
    r_multiple: float | None  # P&L in units of that risk; None while open or without a stop
    entry: JournalOut | None


class GroupStats(BaseModel):
    name: str | None  # None: not journaled / not recorded
    trades: int
    win_rate: float
    total_pnl: float
    avg_pnl: float  # expectancy: what a trade like this made on average
    avg_win: float | None
    avg_loss: float | None
    avg_rating: float | None
    r_trades: int  # trades with a known initial risk
    avg_r: float | None  # expectancy in R over those


class RPoint(BaseModel):
    trade_id: int
    symbol: str
    closed_at: datetime
    r: float
    cumulative_r: float


class RCurve(BaseModel):
    """Closed trips with a known risk, in the order they closed, and what their R adds up to."""

    points: list[RPoint]
    total_r: float
    max_drawdown_r: float  # largest fall from a peak of cumulative R (0 at the start), as a positive number
    longest_losing_streak: int  # consecutive trades below 0R


class JournalPage(BaseModel):
    trips: list[TripOut]
    by_setup: list[GroupStats]
    by_emotion: list[GroupStats]
    setups: list[str]
    emotions: list[str] = list(EMOTIONS)
    needs_review: int
    overall: GroupStats | None  # every closed trip
    r_curve: RCurve | None  # None until a closed trip has an initial stop
    disclaimer: str = DISCLAIMER


class Trip:
    """A round trip with its journal entry and initial stop."""

    def __init__(self, trip: RoundTrip, entry: JournalEntry | None, orders: list[SimulatedOrder]) -> None:
        self.trip, self.entry = trip, entry
        found = (entry.planned_stop, "journal") if entry and entry.planned_stop else initial_stop(trip, orders)
        self.stop: float | None = found[0] if found else None
        self.stop_source: str | None = found[1] if found else None
        self.risk = trip.risk(self.stop)
        self.r_multiple = trip.r_multiple(self.stop)


async def _load(db: DbSession, pf: PaperPortfolio) -> list[Trip]:
    trades = (
        await db.scalars(
            select(SimulatedTrade)
            .where(SimulatedTrade.portfolio_id == pf.id)
            .order_by(SimulatedTrade.executed_at, SimulatedTrade.id)
            .limit(MAX_TRADES)
        )
    ).all()
    entries = {e.trade_id: e for e in (await db.scalars(select(JournalEntry).where(JournalEntry.portfolio_id == pf.id))).all()}
    orders = (
        await db.scalars(
            select(SimulatedOrder)
            .where(
                SimulatedOrder.portfolio_id == pf.id,
                or_(SimulatedOrder.bracket_stop_loss.is_not(None), SimulatedOrder.order_type.in_(STOP_TYPES)),
            )
            .order_by(SimulatedOrder.created_at, SimulatedOrder.id)
        )
    ).all()
    return [Trip(t, entries.get(t.trade_id), list(orders)) for t in round_trips(list(trades))]


def _group(name: str | None, items: list[Trip]) -> GroupStats:
    pnls = [t.trip.pnl for t in items]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    ratings = [t.entry.rating for t in items if t.entry and t.entry.rating]
    rs = [t.r_multiple for t in items if t.r_multiple is not None]
    return GroupStats(
        name=name, trades=len(pnls), win_rate=len(wins) / len(pnls) * 100, total_pnl=sum(pnls), avg_pnl=sum(pnls) / len(pnls),
        avg_win=sum(wins) / len(wins) if wins else None, avg_loss=sum(losses) / len(losses) if losses else None,
        avg_rating=sum(ratings) / len(ratings) if ratings else None, r_trades=len(rs), avg_r=sum(rs) / len(rs) if rs else None,
    )  # fmt: skip


def _stats(closed: list[Trip], key: Callable[[JournalEntry | None], str | None]) -> list[GroupStats]:
    groups: dict[str | None, list[Trip]] = defaultdict(list)
    for t in closed:
        groups[key(t.entry)].append(t)
    out = [_group(name, items) for name, items in groups.items()]
    # Most-used first; the unlabelled group last.
    return sorted(out, key=lambda g: (g.name is None, -g.trades, g.name or ""))


def _trip_out(t: Trip) -> TripOut:
    trip, entry = t.trip, t.entry
    return TripOut(
        trade_id=trip.trade_id, symbol=trip.symbol, side=trip.side, opened_at=trip.opened_at, closed_at=trip.closed_at,
        quantity=trip.quantity, entry_price=trip.entry_price, exit_price=trip.exit_price,
        pnl=None if trip.is_open else trip.pnl, pnl_pct=trip.pnl_pct, fees=trip.fees, holding_seconds=trip.holding_seconds,
        fills=trip.fills, initial_stop=t.stop, stop_source=t.stop_source, risk=t.risk, r_multiple=t.r_multiple,
        entry=JournalOut.model_validate(entry) if entry else None,
    )  # fmt: skip


def _r_curve(closed: list[Trip]) -> RCurve | None:
    with_r = sorted((t for t in closed if t.r_multiple is not None), key=lambda t: (t.trip.closed_at, t.trip.trade_id))
    if not with_r:
        return None
    points, total, peak, drawdown, streak, longest = [], 0.0, 0.0, 0.0, 0, 0
    for t in with_r:
        r = t.r_multiple
        assert r is not None and t.trip.closed_at is not None
        total += r
        peak = max(peak, total)
        drawdown = max(drawdown, peak - total)
        streak = streak + 1 if r < 0 else 0
        longest = max(longest, streak)
        points.append(RPoint(trade_id=t.trip.trade_id, symbol=t.trip.symbol, closed_at=t.trip.closed_at, r=r, cumulative_r=total))
    return RCurve(points=points, total_r=total, max_drawdown_r=drawdown, longest_losing_streak=longest)


@router.get("", response_model=JournalPage)
async def get_journal(user: CurrentUser, db: DbSession) -> JournalPage:
    _, pf = await _service_and_portfolio(db, user.id)
    trips = await _load(db, pf)
    closed = [t for t in trips if not t.trip.is_open]
    setups = sorted({t.entry.setup for t in trips if t.entry and t.entry.setup}, key=str.lower)
    return JournalPage(
        trips=[_trip_out(t) for t in reversed(trips)],
        by_setup=_stats(closed, lambda e: e.setup if e else None),
        by_emotion=_stats(closed, lambda e: e.emotion if e else None),
        setups=setups,
        needs_review=sum(1 for t in closed if t.entry is None),
        overall=_group("All trades", closed) if closed else None,
        r_curve=_r_curve(closed),
    )


@router.put("/{trade_id}", response_model=JournalOut)
async def save_entry(trade_id: int, body: JournalIn, user: CurrentUser, db: DbSession) -> JournalEntry:
    _, pf = await _service_and_portfolio(db, user.id)
    trips = await _load(db, pf)
    trip = next((t for t in trips if t.trip.trade_id == trade_id), None)
    if trip is None:
        raise NotFoundError("No trade in your journal starts with that fill")
    if body.planned_stop is not None and trip.trip.risk(body.planned_stop) is None:
        side = trip.trip.side
        raise ValidationFailedError(
            f"A {side} trade's stop must be {'below' if side == 'long' else 'above'} its entry price ({trip.trip.entry_price:,.2f})"
        )
    setup = body.setup
    if setup:  # reuse an existing spelling, so "breakout" and "Breakout" are one setup in the stats
        setup = next((t.entry.setup for t in trips if t.entry and t.entry.setup and t.entry.setup.lower() == setup.lower()), setup)
    entry = trip.entry or JournalEntry(portfolio_id=pf.id, trade_id=trade_id)
    entry.setup, entry.emotion, entry.rating = setup, body.emotion, body.rating
    entry.notes, entry.lesson, entry.planned_stop = body.notes.strip(), body.lesson.strip(), body.planned_stop
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry


@router.delete("/{trade_id}", status_code=204)
async def delete_entry(trade_id: int, user: CurrentUser, db: DbSession) -> Response:
    _, pf = await _service_and_portfolio(db, user.id)
    entry = await db.scalar(select(JournalEntry).where(JournalEntry.portfolio_id == pf.id, JournalEntry.trade_id == trade_id))
    if entry is None:
        raise NotFoundError("No journal entry for that trade")
    await db.delete(entry)
    return Response(status_code=204)


@router.get(".csv")
async def export_journal(user: CurrentUser, db: DbSession) -> Response:
    _, pf = await _service_and_portfolio(db, user.id)
    trips = await _load(db, pf)
    header = ("opened_at", "closed_at", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "pnl_pct", "fees",
              "initial_stop", "risk", "r_multiple", "setup", "emotion", "rating", "notes", "lesson", "simulated")  # fmt: skip
    rows = []
    for x in trips:
        t, e = x.trip, x.entry
        rows.append((t.opened_at, t.closed_at, t.symbol, t.side, t.quantity, t.entry_price, t.exit_price,
                     None if t.is_open else t.pnl, t.pnl_pct, t.fees, x.stop, x.risk, x.r_multiple,
                     e.setup if e else None, e.emotion if e else None,
                     e.rating if e else None, e.notes if e else None, e.lesson if e else None, True))  # fmt: skip
    return csv_response(safe_filename("paper", "journal"), header, rows)
