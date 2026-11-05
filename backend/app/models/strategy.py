from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, JSONType, TimestampMixin, UTCDateTime, utcnow
from app.models.market import Asset


class Strategy(IdMixin, TimestampMixin, Base):
    __tablename__ = "strategies"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_strategies_user_name"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1)

    configurations: Mapped[list["StrategyConfiguration"]] = relationship(
        back_populates="strategy",
        cascade="all, delete-orphan",
        order_by="StrategyConfiguration.version",
        lazy="selectin",
    )

    @property
    def current_config(self) -> "StrategyConfiguration | None":
        for cfg in self.configurations:
            if cfg.version == self.current_version:
                return cfg
        return self.configurations[-1] if self.configurations else None


class StrategyConfiguration(IdMixin, Base):
    """Immutable, versioned strategy definition. Edits create a new version so
    historical backtests always reference the exact rules that produced them."""

    __tablename__ = "strategy_configurations"
    __table_args__ = (UniqueConstraint("strategy_id", "version", name="uq_strategy_configurations_version"),)

    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"))
    timeframe: Mapped[str] = mapped_column(String(8))
    entry_rules: Mapped[dict] = mapped_column(JSONType)
    exit_rules: Mapped[dict] = mapped_column(JSONType)
    risk: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    strategy: Mapped[Strategy] = relationship(back_populates="configurations")
    asset: Mapped[Asset] = relationship(lazy="selectin")
