from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, JSONType, Money, UTCDateTime, utcnow
from app.models.enums import BacktestStatus
from app.models.market import Asset
from app.models.strategy import Strategy, StrategyConfiguration


class BacktestSession(IdMixin, Base):
    __tablename__ = "backtest_sessions"
    __table_args__ = (Index("ix_backtest_sessions_user_created", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    strategy_config_id: Mapped[int] = mapped_column(ForeignKey("strategy_configurations.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    timeframe: Mapped[str] = mapped_column(String(8))
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    initial_capital: Mapped[float] = mapped_column(Money)
    fee_bps: Mapped[float] = mapped_column(Float)
    slippage_bps: Mapped[float] = mapped_column(Float)
    status: Mapped[BacktestStatus] = mapped_column(
        Enum(BacktestStatus, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e]),
        default=BacktestStatus.PENDING,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_source: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    strategy: Mapped[Strategy] = relationship(lazy="selectin")
    config: Mapped[StrategyConfiguration] = relationship(lazy="selectin")
    asset: Mapped[Asset] = relationship(lazy="selectin")
    result: Mapped["BacktestResult | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class BacktestResult(IdMixin, Base):
    __tablename__ = "backtest_results"

    session_id: Mapped[int] = mapped_column(ForeignKey("backtest_sessions.id", ondelete="CASCADE"), unique=True)
    total_return_pct: Mapped[float] = mapped_column(Float)
    buy_hold_return_pct: Mapped[float] = mapped_column(Float)
    max_drawdown_pct: Mapped[float] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    num_trades: Mapped[int] = mapped_column(Integer)
    final_equity: Mapped[float] = mapped_column(Money)
    metrics: Mapped[dict] = mapped_column(JSONType)
    equity_curve: Mapped[list] = mapped_column(JSONType)
    trades: Mapped[list] = mapped_column(JSONType)

    session: Mapped[BacktestSession] = relationship(back_populates="result")


class ResearchRun(IdMixin, Base):
    """A saved parameter sweep or walk-forward analysis (both HYPOTHETICAL, like backtests)."""

    __tablename__ = "research_runs"
    __table_args__ = (Index("ix_research_runs_user_created", "user_id", "created_at"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    strategy_config_id: Mapped[int] = mapped_column(ForeignKey("strategy_configurations.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    kind: Mapped[str] = mapped_column(String(16))  # "sweep" | "walk_forward"
    timeframe: Mapped[str] = mapped_column(String(8))
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    request: Mapped[dict] = mapped_column(JSONType)
    result: Mapped[dict] = mapped_column(JSONType)
    data_source: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    strategy: Mapped[Strategy] = relationship(lazy="selectin")
    config: Mapped[StrategyConfiguration] = relationship(lazy="selectin")
    asset: Mapped[Asset] = relationship(lazy="selectin")
