"""Price alerts: notify a user once an asset's market price reaches a level they chose.

Prices come from the configured market data provider; an asset whose price can't be fetched is
simply not checked this round. Alerts never place orders, simulated or real."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.market_data.service import MarketDataService
from app.models.notification import Notification
from app.models.price_alert import PriceAlert
from app.models.user import UserSettings

logger = get_logger(__name__)

DISCLAIMER = "Research notification only; no order was placed. Not financial advice."


def _price(v: float) -> str:
    return f"{v:,.2f}" if v >= 1 else f"{v:.6g}"


def describe(alert: PriceAlert) -> str:
    """'BTC-USD at or above 70,000.00'"""
    return f"{alert.asset.symbol} at or {alert.condition} {_price(alert.target)}"


async def check_price_alerts() -> int:
    """Background job: fire every active alert whose level the price has reached. Returns alerts fired."""
    fired = 0
    async with get_sessionmaker()() as session:
        alerts = (
            await session.scalars(select(PriceAlert).where(PriceAlert.triggered_at.is_(None)).order_by(PriceAlert.id))
        ).all()
        if not alerts:
            return 0
        tickers = await MarketDataService(session).get_tickers(list({a.asset_id: a.asset for a in alerts}.values()))
        webhook_ready: dict[int, bool] = {}
        for alert in alerts:
            t = tickers.get(alert.asset.symbol)
            if t is None or not alert.hit(t.price):
                continue
            alert.triggered_at, alert.triggered_price = datetime.now(UTC), t.price
            if alert.notify_webhook and alert.user_id not in webhook_ready:
                s = await session.scalar(select(UserSettings).where(UserSettings.user_id == alert.user_id))
                webhook_ready[alert.user_id] = bool(s and s.webhook_url and s.webhook_secret)
            message = f"{alert.asset.symbol} traded at {_price(t.price)}, reaching your alert at {_price(alert.target)}"
            message += f" (set when it was {_price(alert.created_price)})."
            if alert.note:
                message += f" Your note: {alert.note}"
            session.add(Notification(
                user_id=alert.user_id, kind="price_alert", title=f"Price alert · {describe(alert)}",
                message=f"{message} {DISCLAIMER}", symbol=alert.asset.symbol,
                webhook_pending=alert.notify_webhook and webhook_ready.get(alert.user_id, False),
            ))  # fmt: skip
            fired += 1
        await session.commit()
    if fired:
        logger.info("price_alerts_fired", count=fired)
    return fired
