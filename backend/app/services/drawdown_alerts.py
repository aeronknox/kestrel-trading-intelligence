"""Drawdown alerts: tell the user when their paper portfolio has fallen a set % below its highest equity.

The peak is the highest equity on record (snapshots, the starting balance, and equity now). An alert fires
once per drawdown: it re-arms only after equity makes a new high. A notification only: nothing is sold.
"""

from sqlalchemy import func, select

from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.notification import Notification
from app.models.paper import PaperPortfolio, PortfolioSnapshot
from app.models.user import UserSettings
from app.paper_trading.service import PaperTradingService

logger = get_logger(__name__)

DISCLAIMER = "Simulated paper trading: no real money or brokerage is involved. Nothing was sold."


async def check_drawdown_alerts() -> int:
    """Background job. Returns alerts sent."""
    sent = 0
    async with get_sessionmaker()() as session:
        portfolios = (
            await session.scalars(
                select(PaperPortfolio).where(PaperPortfolio.is_active.is_(True), PaperPortfolio.drawdown_alert_pct.is_not(None))
            )
        ).all()
        for pf in portfolios:
            try:
                sent += await check_portfolio(session, pf)
                await session.commit()
            except Exception as exc:  # noqa: BLE001 - one portfolio (e.g. no prices) must not stop the others
                await session.rollback()
                logger.warning("drawdown_alert_failed", portfolio_id=pf.id, error=str(exc))
    return sent


async def check_portfolio(session, pf: PaperPortfolio) -> int:  # type: ignore[no-untyped-def]
    threshold = pf.drawdown_alert_pct
    assert threshold is not None
    equity = (await PaperTradingService(session).summary(pf))["equity"]
    best = await session.scalar(select(func.max(PortfolioSnapshot.equity)).where(PortfolioSnapshot.portfolio_id == pf.id))
    peak = max(best or 0.0, pf.starting_balance, equity)
    drawdown = (1 - equity / peak) * 100 if peak > 0 else 0.0
    if drawdown < threshold:
        return 0
    if pf.drawdown_alert_peak is not None and peak <= pf.drawdown_alert_peak * (1 + 1e-9):
        return 0  # already told about this drawdown; re-armed by a new high
    pf.drawdown_alert_peak = peak
    settings = await session.scalar(select(UserSettings).where(UserSettings.user_id == pf.user_id))
    webhook = bool(settings and settings.webhook_orders and settings.webhook_url and settings.webhook_secret)
    session.add(Notification(
        user_id=pf.user_id, kind="drawdown", title=f"Portfolio down {drawdown:.1f}% from its high",
        message=(f"Your paper portfolio's equity is ${equity:,.2f}, {drawdown:.1f}% below its high of ${peak:,.2f} "
                 f"(your alert is at {threshold:g}%). Consider reviewing open positions and stops. {DISCLAIMER}"),
        webhook_pending=webhook,
    ))  # fmt: skip
    return 1
