from datetime import datetime

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, String, UniqueConstraint, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, Money, TimestampMixin, UTCDateTime, utcnow
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.market import Asset


def _enum(e):  # type: ignore[no-untyped-def]
    return Enum(e, native_enum=False, length=16, values_callable=lambda x: [m.value for m in x])


class PaperPortfolio(IdMixin, TimestampMixin, Base):
    """A purely simulated portfolio. It is never connected to a brokerage."""

    __tablename__ = "paper_portfolios"
    __table_args__ = (
        # One active portfolio per user, enforced by the database (closes the first-request race).
        Index(
            "uq_paper_portfolios_active_user",
            "user_id",
            unique=True,
            sqlite_where=text("is_active"),
            postgresql_where=text("is_active"),
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), default="Main")
    starting_balance: Mapped[float] = mapped_column(Money)
    cash_balance: Mapped[float] = mapped_column(Money)
    realized_pnl: Mapped[float] = mapped_column(Money, default=0.0)
    total_fees: Mapped[float] = mapped_column(Money, default=0.0)
    # Risk limits
    max_position_pct: Mapped[float] = mapped_column(Float, default=25.0)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=10)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, default=5.0)
    # Short selling (negative positions); off unless the user enables it.
    allow_short: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Trade-plan rules for the trader's own entries (not strategies or margin calls): every new position
    # needs a stop-loss, and/or what that stop would lose is capped at a share of equity (implies the stop).
    require_stop_loss: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    max_risk_per_trade_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan", lazy="selectin"
    )


class PortfolioPosition(IdMixin, Base):
    __tablename__ = "portfolio_positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "asset_id", name="uq_portfolio_positions_pf_asset"),)

    portfolio_id: Mapped[int] = mapped_column(ForeignKey("paper_portfolios.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    quantity: Mapped[float] = mapped_column(Money, default=0.0)  # negative = short
    avg_entry_price: Mapped[float] = mapped_column(Money, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Money, default=0.0)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    portfolio: Mapped[PaperPortfolio] = relationship(back_populates="positions")
    asset: Mapped[Asset] = relationship(lazy="selectin")


class SimulatedOrder(IdMixin, Base):
    __tablename__ = "simulated_orders"
    __table_args__ = (
        Index("ix_simulated_orders_pf_created", "portfolio_id", "created_at"),
        Index("ix_simulated_orders_status", "status"),
    )

    portfolio_id: Mapped[int] = mapped_column(ForeignKey("paper_portfolios.id", ondelete="CASCADE"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    side: Mapped[OrderSide] = mapped_column(_enum(OrderSide))
    order_type: Mapped[OrderType] = mapped_column(_enum(OrderType))
    quantity: Mapped[float] = mapped_column(Money)
    limit_price: Mapped[float | None] = mapped_column(Money, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Money, nullable=True)
    # Trailing stops: the stop sits trail_pct away from the best price seen since placement
    # (trail_anchor: the highest price for a sell, the lowest for a buy) and only moves toward it.
    trail_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_anchor: Mapped[float | None] = mapped_column(Money, nullable=True)
    # Where a stop or trailing stop started (a trailing stop's stop_price moves): the journal's initial risk.
    initial_stop: Mapped[float | None] = mapped_column(Money, nullable=True)
    # A partial take-profit can move the position's stop-loss here when it fills (breakeven). After the
    # fill it holds where the stop was moved to, or None if it couldn't be (e.g. the price was already below).
    move_stop_to: Mapped[float | None] = mapped_column(Money, nullable=True)
    # Entry orders can carry a stop-loss / take-profit, attached as protection once they fill.
    bracket_stop_loss: Mapped[float | None] = mapped_column(Money, nullable=True)
    bracket_take_profit: Mapped[float | None] = mapped_column(Money, nullable=True)
    # Only ever shrinks a position; cancelled automatically once that position is closed.
    reduce_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # One-cancels-other: when an order in the group fills, the rest are cancelled.
    oco_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus), default=OrderStatus.OPEN)
    filled_price: Mapped[float | None] = mapped_column(Money, nullable=True)
    fee: Mapped[float] = mapped_column(Money, default=0.0)
    reject_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)  # e.g. why the system placed it
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Time in force: None is good-till-cancelled; otherwise a resting order still open at this time expires.
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Set when a strategy's forward test placed the order (null for manual orders).
    strategy_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    asset: Mapped[Asset] = relationship(lazy="selectin")


class SimulatedTrade(IdMixin, Base):
    __tablename__ = "simulated_trades"
    __table_args__ = (Index("ix_simulated_trades_pf_executed", "portfolio_id", "executed_at"),)

    order_id: Mapped[int] = mapped_column(ForeignKey("simulated_orders.id", ondelete="CASCADE"), unique=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("paper_portfolios.id", ondelete="CASCADE"))
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    side: Mapped[OrderSide] = mapped_column(_enum(OrderSide))
    quantity: Mapped[float] = mapped_column(Money)
    price: Mapped[float] = mapped_column(Money)
    fee: Mapped[float] = mapped_column(Money)
    realized_pnl: Mapped[float] = mapped_column(Money, default=0.0)
    # True when the trade reduced or closed a position (a long sale or a short cover).
    is_closing: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    executed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    asset: Mapped[Asset] = relationship(lazy="selectin")


class PortfolioSnapshot(IdMixin, Base):
    """Point-in-time equity, used for performance charts and daily P&L."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (Index("ix_portfolio_snapshots_pf_ts", "portfolio_id", "ts"),)

    portfolio_id: Mapped[int] = mapped_column(ForeignKey("paper_portfolios.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    equity: Mapped[float] = mapped_column(Money)
    cash: Mapped[float] = mapped_column(Money)
    positions_value: Mapped[float] = mapped_column(Money)
