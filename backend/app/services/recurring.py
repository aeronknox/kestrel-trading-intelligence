"""Recurring paper buys (dollar-cost averaging), run by a background job.

Each due plan places one simulated market buy of its dollar amount in the owner's active paper portfolio,
through the normal order path (risk limits, fees, slippage). Nothing is replayed after downtime: a plan
that missed several dates runs once and is rescheduled to its next date in the future. Simulation only:
no real orders, money or brokerage are involved.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.enums import OrderSide, OrderStatus, OrderType
from app.models.recurring import RecurringBuy
from app.paper_trading.service import PaperTradingService
from app.services.notifications import notify_order

logger = get_logger(__name__)

NOTE = "Recurring buy"


def next_after(plan: RecurringBuy, now: datetime) -> datetime:
    """The plan's next date strictly after `now`, keeping its time of day and spacing."""
    step = timedelta(days=plan.interval_days)
    nxt = plan.next_run_at
    while nxt <= now:
        nxt += step
    return nxt


async def run_plan(paper: PaperTradingService, plan: RecurringBuy, now: datetime) -> None:
    """Place one run of `plan` and record the outcome on it (the caller commits)."""
    portfolio = await paper.get_or_create_portfolio(plan.user_id, lock=True)
    ticker = await paper.market.get_ticker(plan.asset)
    # Size so that the cost, slippage and fee included, is the plan's amount.
    price = ticker.price * (1 + paper.slip_rate)
    quantity = plan.amount_usd / (price * (1 + paper.fee_rate))
    order = await paper.place_order(portfolio, plan.asset, OrderSide.BUY, OrderType.MARKET, quantity, note=NOTE, source="recurring")
    plan.last_run_at = now
    if order.status == OrderStatus.FILLED:
        plan.runs += 1
        plan.invested_usd += order.quantity * (order.filled_price or 0.0) + order.fee
        plan.quantity_bought += order.quantity
        plan.last_status, plan.last_message = "filled", f"Bought {order.quantity:g} {plan.asset.base_currency} at {order.filled_price:,.2f}"
    else:
        plan.last_status, plan.last_message = "rejected", (order.reject_reason or "Rejected")[:255]
    await notify_order(paper.session, plan.user_id, order)


async def run_due_recurring_buys() -> int:
    """Background job: run every active plan whose date has come. Returns buys filled."""
    filled = 0
    async with get_sessionmaker()() as session:
        now = datetime.now(UTC)
        due = (
            await session.scalars(
                select(RecurringBuy).where(RecurringBuy.active.is_(True), RecurringBuy.next_run_at <= now).order_by(RecurringBuy.id)
            )
        ).all()
        for plan_id in [p.id for p in due]:
            plan = await session.get(RecurringBuy, plan_id, with_for_update=True)
            if plan is None or not plan.active or plan.next_run_at > now:
                continue  # removed, paused or run by someone else meanwhile
            try:
                await run_plan(PaperTradingService(session), plan, now)
                filled += plan.last_status == "filled"
            except Exception as exc:  # noqa: BLE001 - one plan's failure (e.g. no price) must not stop the others
                await session.rollback()
                plan = await session.get(RecurringBuy, plan_id)
                if plan is None:
                    continue
                plan.last_run_at, plan.last_status = now, "failed"
                plan.last_message = f"Not run: {exc}"[:255]
                logger.warning("recurring_buy_failed", plan_id=plan_id, error=str(exc))
            plan.next_run_at = next_after(plan, now)
            await session.commit()
    if filled:
        logger.info("recurring_buys_filled", count=filled)
    return filled
