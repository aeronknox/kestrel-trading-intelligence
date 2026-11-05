"""Import all models so SQLAlchemy metadata (and Alembic autogenerate) sees them."""

from app.models.ai import AIAnalysisResult, AIConversation, AIMessage, TradingSignal
from app.models.audit import AuditLog
from app.models.backtest import BacktestResult, BacktestSession
from app.models.market import Asset, MarketData, Watchlist, WatchlistItem
from app.models.paper import (
    PaperPortfolio,
    PortfolioPosition,
    PortfolioSnapshot,
    SimulatedOrder,
    SimulatedTrade,
)
from app.models.strategy import Strategy, StrategyConfiguration
from app.models.user import User, UserSession, UserSettings

__all__ = [
    "AIAnalysisResult",
    "AIConversation",
    "AIMessage",
    "Asset",
    "AuditLog",
    "BacktestResult",
    "BacktestSession",
    "MarketData",
    "PaperPortfolio",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "SimulatedOrder",
    "SimulatedTrade",
    "Strategy",
    "StrategyConfiguration",
    "TradingSignal",
    "User",
    "UserSession",
    "UserSettings",
    "Watchlist",
    "WatchlistItem",
]
