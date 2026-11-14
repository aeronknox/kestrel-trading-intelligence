"""A user's own data: export all of it, or delete the account and everything in it."""

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import ColumnElement, delete, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import AIAnalysisResult, AIConversation, AIMessage, TradingSignal
from app.models.alert import AlertEvent, StrategyAlert
from app.models.audit import AuditLog
from app.models.backtest import BacktestResult, BacktestSession, ResearchRun
from app.models.journal import JournalEntry
from app.models.market import Watchlist, WatchlistItem
from app.models.notification import Notification
from app.models.paper import PaperPortfolio, PortfolioPosition, PortfolioSnapshot, SimulatedOrder, SimulatedTrade
from app.models.price_alert import PriceAlert
from app.models.strategy import Strategy, StrategyConfiguration
from app.models.user import User, UserSession, UserSettings

# Never exported: password and token hashes, and the webhook signing secret (it can be regenerated).
SECRET_COLUMNS = {"hashed_password", "token_hash", "webhook_secret"}


def _portfolios(uid: int) -> Any:
    return select(PaperPortfolio.id).where(PaperPortfolio.user_id == uid).scalar_subquery()


# Section name -> (model, rows that belong to the user). Order: roughly how a person thinks about the app.
SECTIONS: list[tuple[str, type, Callable[[int], ColumnElement[bool]]]] = [
    ("profile", User, lambda uid: User.id == uid),
    ("settings", UserSettings, lambda uid: UserSettings.user_id == uid),
    ("sessions", UserSession, lambda uid: UserSession.user_id == uid),
    ("watchlists", Watchlist, lambda uid: Watchlist.user_id == uid),
    ("watchlist_items", WatchlistItem,
     lambda uid: WatchlistItem.watchlist_id.in_(select(Watchlist.id).where(Watchlist.user_id == uid))),
    ("strategies", Strategy, lambda uid: Strategy.user_id == uid),
    ("strategy_versions", StrategyConfiguration,
     lambda uid: StrategyConfiguration.strategy_id.in_(select(Strategy.id).where(Strategy.user_id == uid))),
    ("backtests", BacktestSession, lambda uid: BacktestSession.user_id == uid),
    ("backtest_results", BacktestResult,
     lambda uid: BacktestResult.session_id.in_(select(BacktestSession.id).where(BacktestSession.user_id == uid))),
    ("research_runs", ResearchRun, lambda uid: ResearchRun.user_id == uid),
    ("paper_portfolios", PaperPortfolio, lambda uid: PaperPortfolio.user_id == uid),
    ("paper_positions", PortfolioPosition, lambda uid: PortfolioPosition.portfolio_id.in_(_portfolios(uid))),
    ("paper_orders", SimulatedOrder, lambda uid: SimulatedOrder.portfolio_id.in_(_portfolios(uid))),
    ("paper_trades", SimulatedTrade, lambda uid: SimulatedTrade.portfolio_id.in_(_portfolios(uid))),
    ("paper_equity_history", PortfolioSnapshot, lambda uid: PortfolioSnapshot.portfolio_id.in_(_portfolios(uid))),
    ("journal_entries", JournalEntry, lambda uid: JournalEntry.portfolio_id.in_(_portfolios(uid))),
    ("strategy_alerts", StrategyAlert, lambda uid: StrategyAlert.user_id == uid),
    ("alert_events", AlertEvent, lambda uid: AlertEvent.user_id == uid),
    ("price_alerts", PriceAlert, lambda uid: PriceAlert.user_id == uid),
    ("notifications", Notification, lambda uid: Notification.user_id == uid),
    ("ai_analyses", AIAnalysisResult, lambda uid: AIAnalysisResult.user_id == uid),
    ("ai_signals", TradingSignal,
     lambda uid: TradingSignal.analysis_id.in_(select(AIAnalysisResult.id).where(AIAnalysisResult.user_id == uid))),
    ("assistant_conversations", AIConversation, lambda uid: AIConversation.user_id == uid),
    ("assistant_messages", AIMessage,
     lambda uid: AIMessage.conversation_id.in_(select(AIConversation.id).where(AIConversation.user_id == uid))),
    ("activity_log", AuditLog, lambda uid: AuditLog.user_id == uid),
]  # fmt: skip


def _value(v: Any) -> Any:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, Decimal):
        return float(v)
    return v


def _row(obj: object) -> dict[str, Any]:
    return {c.key: _value(getattr(obj, c.key)) for c in inspect(obj).mapper.column_attrs if c.key not in SECRET_COLUMNS}


async def export_user_data(session: AsyncSession, user: User) -> dict[str, Any]:
    """Every row the app holds about `user`, as JSON-ready dicts (secrets left out). Market data is public
    and shared, so it isn't included; asset ids refer to the public asset list."""
    data: dict[str, Any] = {
        "exported_at": datetime.now(UTC).isoformat(),
        "about": "Your Kestrel Intelligence data. Paper trading is simulated: no real money or brokerage was involved. "
        "Password hashes, sign-in tokens and your webhook signing secret are not included.",
    }
    for name, model, belongs in SECTIONS:
        rows: list[Any] = list((await session.scalars(select(model).where(belongs(user.id)).order_by(model.id))).all())  # type: ignore[attr-defined]
        data[name] = [_row(r) for r in rows]
    data["profile"] = data["profile"][0] if data["profile"] else None
    data["settings"] = data["settings"][0] if data["settings"] else None
    return data


async def delete_account(session: AsyncSession, user: User) -> None:
    """Delete the user and everything that is theirs. The database cascades remove nearly all of it; AI
    analyses would only lose their owner (their foreign key is SET NULL), so they are deleted here explicitly.
    Security log entries stay, without the user, but lose any copy of the email address."""
    uid, email = user.id, user.email
    await session.execute(delete(AIAnalysisResult).where(AIAnalysisResult.user_id == uid))
    for entry in (
        await session.scalars(select(AuditLog).where((AuditLog.user_id == uid) | (AuditLog.action == "auth.login_failed")))
    ).all():
        if entry.user_id == uid or (entry.details or {}).get("email") == email:
            entry.details = {k: v for k, v in (entry.details or {}).items() if k != "email"}
    await session.flush()
    session.expunge(user)
    await session.execute(delete(User).where(User.id == uid))
