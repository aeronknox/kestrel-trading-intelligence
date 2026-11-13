from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IdMixin, UTCDateTime, utcnow


class Notification(IdMixin, Base):
    """Something that happened to a user's simulated paper orders while they weren't placing them:
    a resting order filled (limit, stop, trailing stop, take-profit), was rejected at fill time, or a
    margin call bought back a short; or a price alert fired. Strategy alert events have their own table (AlertEvent)."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))  # order_filled | order_rejected | order_expired | margin_call | price_alert
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("simulated_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Waiting for the background job to post it to the user's webhook (never sent while trading locks are held).
    webhook_pending: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
