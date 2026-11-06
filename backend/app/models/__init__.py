"""Import all models so SQLAlchemy metadata (and Alembic autogenerate) sees them."""

from app.models.ai import AIAnalysisResult, AIConversation, AIMessage, TradingSignal
from app.models.audit import AuditLog
from app.models.backtest import BacktestResult, BacktestSession, ResearchRun
from app.models.market import Asset, MarketData, Watchlist, WatchlistItem
from app.models.paper import (
    PaperPortfolio,
    PortfolioPosition,
    PortfolioSnapshot,
    SimulatedOrder,
    SimulatedTrade,
)
from app.models.strategy import Strategy, StrategyConfiguration
from app.models.user import AuthToken, User, UserSession, UserSettings

__all__ = [
    "AIAnalysisResult",
    "AIConversation",
    "AIMessage",
    "Asset",
    "AuditLog",
    "AuthToken",
    "BacktestResult",
    "BacktestSession",
    "MarketData",
    "PaperPortfolio",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "ResearchRun",
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
