from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, Money, UTCDateTime, utcnow
from app.models.market import Asset


class RecurringBuy(IdMixin, Base):
    """A simulated dollar-cost-averaging plan: buy `amount_usd` of an asset at market in the user's paper
    portfolio every `interval_days`. Paper trading only: each run is an ordinary simulated market order,
    checked against the portfolio's risk limits like any other. Missed runs (e.g. downtime) are not
    replayed: the plan runs once and moves on to its next date."""

    __tablename__ = "recurring_buys"
    __table_args__ = (Index("ix_recurring_buys_due", "active", "next_run_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    amount_usd: Mapped[float] = mapped_column(Money)
    interval_days: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "filled" | "rejected" | "failed"
    last_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    runs: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # filled buys so far
    invested_usd: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")  # cost of those buys, fees included
    quantity_bought: Mapped[float] = mapped_column(Money, default=0.0, server_default="0")

    asset: Mapped[Asset] = relationship(lazy="selectin")
