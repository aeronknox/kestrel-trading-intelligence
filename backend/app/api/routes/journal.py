"""Trading journal for simulated round trips: why a trade was taken, how it felt, what it taught,
and which setups and states of mind actually pay. Simulated paper trading only."""

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.paper import _service_and_portfolio
from app.core.exceptions import NotFoundError
from app.models.journal import JournalEntry
from app.models.paper import PaperPortfolio, SimulatedTrade
from app.paper_trading.round_trips import RoundTrip, round_trips
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


class JournalPage(BaseModel):
    trips: list[TripOut]
    by_setup: list[GroupStats]
    by_emotion: list[GroupStats]
    setups: list[str]
    emotions: list[str] = list(EMOTIONS)
    needs_review: int
    disclaimer: str = DISCLAIMER


async def _load(db: DbSession, pf: PaperPortfolio) -> tuple[list[RoundTrip], dict[int, JournalEntry]]:
    trades = (
        await db.scalars(
            select(SimulatedTrade)
            .where(SimulatedTrade.portfolio_id == pf.id)
            .order_by(SimulatedTrade.executed_at, SimulatedTrade.id)
            .limit(MAX_TRADES)
        )
    ).all()
    entries = (await db.scalars(select(JournalEntry).where(JournalEntry.portfolio_id == pf.id))).all()
    return round_trips(list(trades)), {e.trade_id: e for e in entries}


def _stats(pairs: list[tuple[RoundTrip, JournalEntry | None]], key: Callable[[JournalEntry | None], str | None]) -> list[GroupStats]:
    groups: dict[str | None, list[tuple[RoundTrip, JournalEntry | None]]] = defaultdict(list)
    for trip, entry in pairs:
        groups[key(entry)].append((trip, entry))
    out = []
    for name, items in groups.items():
        pnls = [t.pnl for t, _ in items]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        ratings = [e.rating for _, e in items if e and e.rating]
        out.append(GroupStats(
            name=name, trades=len(pnls), win_rate=len(wins) / len(pnls) * 100, total_pnl=sum(pnls), avg_pnl=sum(pnls) / len(pnls),
            avg_win=sum(wins) / len(wins) if wins else None, avg_loss=sum(losses) / len(losses) if losses else None,
            avg_rating=sum(ratings) / len(ratings) if ratings else None,
        ))  # fmt: skip
    # Most-used first; the unlabelled group last.
    return sorted(out, key=lambda g: (g.name is None, -g.trades, g.name or ""))


def _trip_out(trip: RoundTrip, entry: JournalEntry | None) -> TripOut:
    return TripOut(
        trade_id=trip.trade_id, symbol=trip.symbol, side=trip.side, opened_at=trip.opened_at, closed_at=trip.closed_at,
        quantity=trip.quantity, entry_price=trip.entry_price, exit_price=trip.exit_price,
        pnl=None if trip.is_open else trip.pnl, pnl_pct=trip.pnl_pct, fees=trip.fees, holding_seconds=trip.holding_seconds,
        fills=trip.fills, entry=JournalOut.model_validate(entry) if entry else None,
    )  # fmt: skip


@router.get("", response_model=JournalPage)
async def get_journal(user: CurrentUser, db: DbSession) -> JournalPage:
    _, pf = await _service_and_portfolio(db, user.id)
    trips, entries = await _load(db, pf)
    closed = [(t, entries.get(t.trade_id)) for t in trips if not t.is_open]
    setups = sorted({e.setup for e in entries.values() if e.setup}, key=str.lower)
    return JournalPage(
        trips=[_trip_out(t, entries.get(t.trade_id)) for t in reversed(trips)],
        by_setup=_stats(closed, lambda e: e.setup if e else None),
        by_emotion=_stats(closed, lambda e: e.emotion if e else None),
        setups=setups,
        needs_review=sum(1 for _, e in closed if e is None),
    )


@router.put("/{trade_id}", response_model=JournalOut)
async def save_entry(trade_id: int, body: JournalIn, user: CurrentUser, db: DbSession) -> JournalEntry:
    _, pf = await _service_and_portfolio(db, user.id)
    trips, entries = await _load(db, pf)
    if not any(t.trade_id == trade_id for t in trips):
        raise NotFoundError("No trade in your journal starts with that fill")
    setup = body.setup
    if setup:  # reuse an existing spelling, so "breakout" and "Breakout" are one setup in the stats
        setup = next((e.setup for e in entries.values() if e.setup and e.setup.lower() == setup.lower()), setup)
    entry = entries.get(trade_id) or JournalEntry(portfolio_id=pf.id, trade_id=trade_id)
    entry.setup, entry.emotion, entry.rating = setup, body.emotion, body.rating
    entry.notes, entry.lesson = body.notes.strip(), body.lesson.strip()
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
    trips, entries = await _load(db, pf)
    header = ("opened_at", "closed_at", "symbol", "side", "quantity", "entry_price", "exit_price", "pnl", "pnl_pct", "fees",
              "setup", "emotion", "rating", "notes", "lesson", "simulated")  # fmt: skip
    rows = []
    for t in trips:
        e = entries.get(t.trade_id)
        rows.append((t.opened_at, t.closed_at, t.symbol, t.side, t.quantity, t.entry_price, t.exit_price,
                     None if t.is_open else t.pnl, t.pnl_pct, t.fees, e.setup if e else None, e.emotion if e else None,
                     e.rating if e else None, e.notes if e else None, e.lesson if e else None, True))  # fmt: skip
    return csv_response(safe_filename("paper", "journal"), header, rows)
