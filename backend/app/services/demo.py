"""Demo sandboxes: a throwaway account per visitor, pre-loaded with sample work.

Enabled with DEMO_MODE=true. Each "Try the demo" click creates an isolated user, so
visitors never see or change each other's data, and a background job deletes demo
accounts (and, through ON DELETE CASCADE, everything they created) after
DEMO_TTL_HOURS. Demo accounts can't change credentials and never receive email.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.enums import OrderSide, OrderType
from app.models.user import User
from app.services.auth import register_user
from app.strategies.definition import TEMPLATES

logger = get_logger(__name__)

DEMO_EMAIL_DOMAIN = "demo.invalid"  # reserved TLD: can never be a real mailbox
SEED_STRATEGIES = (("rsi_mean_reversion", "BTC-USD", "1h"), ("ma_crossover", "ETH-USD", "6h"))


class DemoCapacityError(Exception):
    """Too many live demo sandboxes."""


async def live_demo_count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(User).where(User.is_demo.is_(True))) or 0)


async def ensure_capacity(db: AsyncSession) -> None:
    """Refuse new sandboxes at DEMO_MAX_ACCOUNTS, after first clearing out expired ones."""
    cap = get_settings().demo_max_accounts
    if await live_demo_count(db) < cap:
        return
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().demo_ttl_hours)
    await db.execute(delete(User).where(User.is_demo.is_(True), User.created_at < cutoff))
    if await live_demo_count(db) >= cap:
        raise DemoCapacityError


def llm_allowed(user: User) -> bool:
    """Paid LLM calls are for real accounts unless DEMO_ALLOW_LLM is set."""
    return not user.is_demo or get_settings().demo_allow_llm


async def create_demo_user(db: AsyncSession) -> User:
    email = f"demo-{secrets.token_hex(6)}@{DEMO_EMAIL_DOMAIN}"
    # Random password nobody knows: the session cookie is the only way in.
    user = await register_user(db, email, secrets.token_urlsafe(24) + "a1", "Demo trader")
    user.is_demo = True
    await db.flush()
    await _seed(db, user)
    return user


async def _seed(db: AsyncSession, user: User) -> None:
    """Sample strategies, a completed backtest and a paper position. Best-effort: a market data
    outage must not stop someone from entering the demo."""
    from app.api.routes.backtests import create_backtest
    from app.api.routes.strategies import create_strategy
    from app.market_data.service import MarketDataService
    from app.paper_trading.service import PaperTradingService
    from app.schemas.strategy import BacktestRequest, StrategyConfigIn, StrategyCreate

    templates = {t["key"]: t for t in TEMPLATES}
    strategy_ids: list[int] = []
    for key, symbol, timeframe in SEED_STRATEGIES:
        t = templates[key]
        config = StrategyConfigIn.model_validate({"symbol": symbol, "timeframe": timeframe, **t["definition"]})
        out = await create_strategy(StrategyCreate(name=t["name"], description=t["description"], config=config), user, db)
        strategy_ids.append(out.id)  # type: ignore[attr-defined]
    try:
        async with db.begin_nested():
            await create_backtest(BacktestRequest(strategy_id=strategy_ids[0], bars=2000), user, db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo_seed_backtest_failed", error=str(exc))
    try:
        async with db.begin_nested():
            market = MarketDataService(db)
            paper = PaperTradingService(db, market)
            portfolio = await paper.get_or_create_portfolio(user.id, lock=True)
            await paper.place_order(portfolio, await market.get_asset("BTC-USD"), OrderSide.BUY, OrderType.MARKET, 0.1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("demo_seed_paper_failed", error=str(exc))


async def purge_expired_demo_users() -> int:
    """Background job: delete demo accounts older than DEMO_TTL_HOURS. Returns how many."""
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().demo_ttl_hours)
    async with get_sessionmaker()() as session:
        stale = await session.scalar(
            select(func.count()).select_from(User).where(User.is_demo.is_(True), User.created_at < cutoff)
        )
        if stale:
            await session.execute(delete(User).where(User.is_demo.is_(True), User.created_at < cutoff))
            await session.commit()
            logger.info("demo_users_purged", count=stale)
    return int(stale or 0)
