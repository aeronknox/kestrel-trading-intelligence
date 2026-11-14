"""Notifications about simulated paper orders that filled or failed in the background.

Created inside the order-matching transaction (cheap: one row), and posted to the user's webhook
later by a background job, so a slow endpoint never holds a portfolio's row lock.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.notification import Notification
from app.models.paper import SimulatedOrder
from app.models.user import UserSettings
from app.services import webhooks

logger = get_logger(__name__)

DISCLAIMER = "Simulated paper trading: no real money or brokerage is involved."
DELIVERY_BATCH = 100
NAMED = ("Stop-loss", "Take-profit", "Trailing stop", "Partial take-profit")  # notes set by position protection


def _price(v: float | None) -> str:
    return "—" if v is None else f"{v:,.2f}" if v >= 1 else f"{v:.6g}"


def describe(order: SimulatedOrder) -> str:
    """'Stop-loss', 'Limit buy', 'Trailing stop sell'…"""
    if order.note in NAMED:
        return order.note
    kind = {OrderType.LIMIT: "Limit", OrderType.STOP: "Stop", OrderType.TRAILING_STOP: "Trailing stop"}.get(order.order_type, "Market")
    return f"{kind} {order.side.value}"


async def notify_order(session: AsyncSession, user_id: int, order: SimulatedOrder, *, margin_call: bool = False) -> Notification | None:
    """Record a notification for an order the matching engine just filled or rejected."""
    symbol = order.asset.symbol
    verb = "bought" if order.side == OrderSide.BUY else "sold"
    if margin_call:
        kind = "margin_call"
        title = f"Margin call · {symbol}"
        message = f"{order.note or 'Margin call'}. The short was bought back: {order.quantity:g} {symbol}"
        message += f" at {_price(order.filled_price)}." if order.status == OrderStatus.FILLED else f", but it was rejected: {order.reject_reason}."
    elif order.status == OrderStatus.FILLED:
        kind = "order_filled"
        title = f"{describe(order)} filled · {symbol}"
        message = f"{describe(order)} {verb} {order.quantity:g} {symbol} at {_price(order.filled_price)}."
        if order.note == "Partial take-profit":
            message += " The rest of the position stays protected."
            if order.move_stop_to is not None:
                message += f" Its stop-loss moved to breakeven ({_price(order.move_stop_to)})."
        elif order.oco_group:
            message += " The other order of its pair was cancelled."
        if order.note and order.note.startswith("Filled, but"):
            message += f" {order.note}."
    elif order.status == OrderStatus.EXPIRED:
        kind = "order_expired"
        title = f"{describe(order)} expired · {symbol}"
        message = f"{describe(order)} for {order.quantity:g} {symbol} expired unfilled; anything it reserved is released."
    elif order.status == OrderStatus.REJECTED:
        kind = "order_rejected"
        title = f"{describe(order)} rejected · {symbol}"
        message = f"{describe(order)} for {order.quantity:g} {symbol} was rejected when it came to fill: {order.reject_reason}."
    else:
        return None
    settings = await session.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    pending = bool(settings and settings.webhook_orders and settings.webhook_url and settings.webhook_secret)
    note = Notification(user_id=user_id, kind=kind, title=title, message=f"{message} {DISCLAIMER}", symbol=symbol,
                        order_id=order.id, webhook_pending=pending)  # fmt: skip
    session.add(note)
    return note


async def deliver_pending_webhooks() -> int:
    """Background job: post pending notifications (orders, price alerts) to their owners' webhooks. Returns attempts."""
    attempts = 0
    async with get_sessionmaker()() as session:
        pending = (
            await session.scalars(
                select(Notification).where(Notification.webhook_pending.is_(True)).order_by(Notification.id).limit(DELIVERY_BATCH)
            )
        ).all()
        for note in pending:
            note.webhook_pending = False  # one attempt each: a dead endpoint must not be retried forever
            settings = await session.scalar(select(UserSettings).where(UserSettings.user_id == note.user_id))
            if settings is None or not settings.webhook_url or not settings.webhook_secret:
                continue
            price_alert = note.kind == "price_alert"  # opted in per alert, not by the order-events switch
            if not price_alert and not settings.webhook_orders:
                continue
            fmt = webhooks.webhook_format(settings.webhook_url)
            event = {"type": "price_alert" if price_alert else "paper_order", "kind": note.kind, "symbol": note.symbol, "order_id": note.order_id,
                     "message": note.message, "created_at": note.created_at.isoformat(), "disclaimer": DISCLAIMER}  # fmt: skip
            payload = webhooks.build_payload(fmt, note.title, [note.message], event)
            attempts += 1
            try:
                settings.webhook_last_status = await webhooks.deliver(settings.webhook_url, settings.webhook_secret, payload)
            except webhooks.WebhookError as exc:
                settings.webhook_last_status = f"Failed: {exc}"[:255]
                logger.warning("order_webhook_failed", user_id=note.user_id, error=str(exc))
            settings.webhook_last_at = datetime.now(UTC)
            await session.commit()  # record each attempt, so a crash can't resend what was delivered
        await session.commit()
    return attempts
