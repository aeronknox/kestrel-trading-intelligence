from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, UTCDateTime, utcnow
from app.models.strategy import Strategy


class StrategyAlert(IdMixin, Base):
    """A user's subscription to a strategy's entry/exit rules on live (closed) candles.

    Alerts are research notifications only: they never place orders, simulated or real.
    """

    __tablename__ = "strategy_alerts"
    __table_args__ = (UniqueConstraint("strategy_id", name="uq_strategy_alerts_strategy"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    on_entry: Mapped[bool] = mapped_column(Boolean, default=True)
    on_exit: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    # Forward test: act on the signals with simulated paper orders (long strategies only).
    auto_trade: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Newest closed bar already evaluated; events only fire for bars after it.
    last_bar_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    strategy: Mapped[Strategy] = relationship(lazy="selectin")


class AlertEvent(IdMixin, Base):
    """One fired alert: a rule set became true on a closed bar."""

    __tablename__ = "alert_events"
    __table_args__ = (
        UniqueConstraint("alert_id", "kind", "bar_at", name="uq_alert_events_once_per_bar"),
        Index("ix_alert_events_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    alert_id: Mapped[int] = mapped_column(ForeignKey("strategy_alerts.id", ondelete="CASCADE"))
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"))
    strategy_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(8))  # "entry" | "exit"
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    bar_at: Mapped[datetime] = mapped_column(UTCDateTime())  # open time of the closed bar
    close_price: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    emailed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("simulated_orders.id", ondelete="SET NULL"), nullable=True)

    strategy: Mapped[Strategy] = relationship(lazy="selectin")
