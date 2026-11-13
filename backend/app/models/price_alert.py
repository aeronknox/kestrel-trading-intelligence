from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, false
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, Money, UTCDateTime, utcnow
from app.models.market import Asset


class PriceAlert(IdMixin, Base):
    """Notify a user once an asset's market price reaches a level. A research notification only:
    it never places an order, simulated or real.

    `condition` is fixed at creation from where the price was: "above" fires once the price is at or
    above `target`, "below" once it is at or below. Each alert fires once, then stays as history."""

    __tablename__ = "price_alerts"
    __table_args__ = (Index("ix_price_alerts_active", "triggered_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    condition: Mapped[str] = mapped_column(String(8))  # "above" | "below"
    target: Mapped[float] = mapped_column(Money)
    created_price: Mapped[float] = mapped_column(Money)  # the price when it was set
    note: Mapped[str] = mapped_column(String(120), default="")
    notify_webhook: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    triggered_price: Mapped[float | None] = mapped_column(Money, nullable=True)

    asset: Mapped[Asset] = relationship(lazy="selectin")

    def hit(self, price: float) -> bool:
        return price >= self.target if self.condition == "above" else price <= self.target
