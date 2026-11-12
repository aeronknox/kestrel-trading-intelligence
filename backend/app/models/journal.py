from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdMixin, UTCDateTime, utcnow


class JournalEntry(IdMixin, Base):
    """A trader's notes on one simulated round trip, keyed by the trip's opening fill.

    Deleted with the trade (a portfolio reset clears the journal along with the history)."""

    __tablename__ = "journal_entries"

    portfolio_id: Mapped[int] = mapped_column(ForeignKey("paper_portfolios.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("simulated_trades.id", ondelete="CASCADE"), unique=True)
    setup: Mapped[str | None] = mapped_column(String(40), nullable=True)  # e.g. "Breakout", "RSI bounce"
    emotion: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5: how well the plan was followed
    notes: Mapped[str] = mapped_column(Text, default="")
    lesson: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
