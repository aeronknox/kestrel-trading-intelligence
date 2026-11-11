from datetime import datetime

from sqlalchemy import Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, IdMixin, JSONType, Money, TimestampMixin, UTCDateTime, utcnow
from app.models.enums import MessageRole, SignalAction
from app.models.market import Asset


class AIAnalysisResult(IdMixin, Base):
    """Snapshot of one analysis run. All numbers come from computed market data;
    only `narrative` may be LLM-written, and `narrative_source` records which."""

    __tablename__ = "ai_analysis_results"
    __table_args__ = (
        Index("ix_ai_analysis_asset_created", "asset_id", "created_at"),
        Index("ix_ai_analysis_user_created", "user_id", "created_at"),  # dashboard and history lists
    )

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    timeframe: Mapped[str] = mapped_column(String(8))
    trend: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text)
    narrative: Mapped[str] = mapped_column(Text)
    narrative_source: Mapped[str] = mapped_column(String(32))
    indicators: Mapped[dict] = mapped_column(JSONType)
    patterns: Mapped[list] = mapped_column(JSONType)
    ml: Mapped[dict] = mapped_column(JSONType)
    data_source: Mapped[str] = mapped_column(String(32))
    data_as_of: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    asset: Mapped[Asset] = relationship(lazy="selectin")
    signal: Mapped["TradingSignal"] = relationship(back_populates="analysis", uselist=False, lazy="selectin")


class TradingSignal(IdMixin, Base):
    __tablename__ = "trading_signals"
    __table_args__ = (Index("ix_trading_signals_asset_created", "asset_id", "created_at"),)

    analysis_id: Mapped[int] = mapped_column(ForeignKey("ai_analysis_results.id", ondelete="CASCADE"), unique=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    timeframe: Mapped[str] = mapped_column(String(8))
    action: Mapped[SignalAction] = mapped_column(
        Enum(SignalAction, native_enum=False, length=8, values_callable=lambda e: [m.value for m in e])
    )
    score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    price_at_signal: Mapped[float] = mapped_column(Money)
    components: Mapped[list] = mapped_column(JSONType)
    risks: Mapped[list] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    analysis: Mapped[AIAnalysisResult] = relationship(back_populates="signal")
    asset: Mapped[Asset] = relationship(lazy="selectin")


class AIConversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_conversations"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.id", lazy="selectin"
    )


class AIMessage(IdMixin, Base):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])
    )
    content: Mapped[str] = mapped_column(Text)
    # Which tools/data the answer was grounded on, and which engine produced it.
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")
