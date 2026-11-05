from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, Money, TimestampMixin, UTCDateTime, utcnow
from app.models.enums import AssetClass

if TYPE_CHECKING:
    from app.models.user import User


class Asset(IdMixin, TimestampMixin, Base):
    """A tradable instrument. `provider_symbol` maps it to the upstream data source."""

    __tablename__ = "assets"

    symbol: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(AssetClass, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        index=True,
    )
    base_currency: Mapped[str] = mapped_column(String(16))
    quote_currency: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    provider_symbol: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketData(Base):
    """OHLCV candles cached from the market data provider."""

    __tablename__ = "market_data"
    __table_args__ = (
        UniqueConstraint("asset_id", "timeframe", "ts", name="uq_market_data_asset_tf_ts"),
        Index("ix_market_data_asset_tf_ts", "asset_id", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    timeframe: Mapped[str] = mapped_column(String(8))
    ts: Mapped[datetime] = mapped_column(UTCDateTime())
    open: Mapped[float] = mapped_column(Money)
    high: Mapped[float] = mapped_column(Money)
    low: Mapped[float] = mapped_column(Money)
    close: Mapped[float] = mapped_column(Money)
    volume: Mapped[float] = mapped_column(Money)
    source: Mapped[str] = mapped_column(String(32))


class Watchlist(IdMixin, TimestampMixin, Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlists_user_name"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))

    user: Mapped["User"] = relationship(back_populates="watchlists")
    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", lazy="selectin", order_by="WatchlistItem.position"
    )


class WatchlistItem(IdMixin, Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "asset_id", name="uq_watchlist_items_wl_asset"),)

    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    asset: Mapped[Asset] = relationship(lazy="selectin")
