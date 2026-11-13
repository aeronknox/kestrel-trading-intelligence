"""Import all models so SQLAlchemy metadata (and Alembic autogenerate) sees them."""

from app.models.ai import AIAnalysisResult, AIConversation, AIMessage, TradingSignal
from app.models.alert import AlertEvent, StrategyAlert
from app.models.audit import AuditLog
from app.models.backtest import BacktestResult, BacktestSession, ResearchRun
from app.models.journal import JournalEntry
from app.models.market import Asset, MarketData, Watchlist, WatchlistItem
from app.models.notification import Notification
from app.models.paper import (
    PaperPortfolio,
    PortfolioPosition,
    PortfolioSnapshot,
    SimulatedOrder,
    SimulatedTrade,
)
from app.models.price_alert import PriceAlert
from app.models.strategy import Strategy, StrategyConfiguration
from app.models.user import AuthToken, User, UserSession, UserSettings

__all__ = [
    "AIAnalysisResult",
    "AIConversation",
    "AIMessage",
    "AlertEvent",
    "Asset",
    "AuditLog",
    "AuthToken",
    "BacktestResult",
    "BacktestSession",
    "JournalEntry",
    "MarketData",
    "Notification",
    "PaperPortfolio",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "PriceAlert",
    "ResearchRun",
    "SimulatedOrder",
    "SimulatedTrade",
    "Strategy",
    "StrategyAlert",
    "StrategyConfiguration",
    "TradingSignal",
    "User",
    "UserSession",
    "UserSettings",
    "Watchlist",
    "WatchlistItem",
]
