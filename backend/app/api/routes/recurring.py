"""Recurring paper buys (dollar-cost averaging). SIMULATED ONLY: each run is a paper market order."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.market_data.service import MarketDataService
from app.models.recurring import RecurringBuy
from app.paper_trading.service import MIN_NOTIONAL
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut
from app.services.audit import audit

router = APIRouter(prefix="/paper/recurring-buys", tags=["paper-trading"])

MAX_ACTIVE = 10
INTERVALS = (1, 7, 14, 30)


class RecurringBuyIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    amount_usd: float = Field(ge=MIN_NOTIONAL, le=1_000_000)
    interval_days: Literal[1, 7, 14, 30]
    start_now: bool = Field(True, description="Make the first buy within a minute; otherwise one interval from now")


class RecurringBuyUpdate(BaseModel):
    active: bool


class RecurringBuyOut(ORMModel):
    id: int
    asset: AssetOut
    amount_usd: float
    interval_days: int
    active: bool
    next_run_at: datetime
    created_at: datetime
    last_run_at: datetime | None
    last_status: str | None
    last_message: str | None
    runs: int
    invested_usd: float
    quantity_bought: float
    average_price: float | None = None  # invested (fees included) per unit bought


def _out(p: RecurringBuy) -> RecurringBuyOut:
    out = RecurringBuyOut.model_validate(p)
    out.average_price = p.invested_usd / p.quantity_bought if p.quantity_bought else None
    return out


async def _owned(db: DbSession, plan_id: int, user_id: int) -> RecurringBuy:
    plan = await db.scalar(select(RecurringBuy).where(RecurringBuy.id == plan_id, RecurringBuy.user_id == user_id))
    if plan is None:
        raise NotFoundError("Recurring buy not found")
    return plan


@router.get("", response_model=list[RecurringBuyOut])
async def list_recurring_buys(user: CurrentUser, db: DbSession) -> list[RecurringBuyOut]:
    plans = (await db.scalars(select(RecurringBuy).where(RecurringBuy.user_id == user.id).order_by(RecurringBuy.created_at))).all()
    return [_out(p) for p in plans]


@router.post("", response_model=RecurringBuyOut, status_code=201)
async def create_recurring_buy(body: RecurringBuyIn, user: CurrentUser, db: DbSession) -> RecurringBuyOut:
    """Buy a fixed dollar amount of an asset on a schedule, in your paper portfolio (simulated)."""
    asset = await MarketDataService(db).get_asset(body.symbol)
    active = await db.scalar(select(func.count()).select_from(RecurringBuy).where(RecurringBuy.user_id == user.id, RecurringBuy.active.is_(True)))
    if (active or 0) >= MAX_ACTIVE:
        raise ValidationFailedError(f"You can have up to {MAX_ACTIVE} active recurring buys; pause or delete one first")
    now = datetime.now(UTC)
    plan = RecurringBuy(user_id=user.id, asset_id=asset.id, amount_usd=body.amount_usd, interval_days=body.interval_days,
                        next_run_at=now if body.start_now else now + timedelta(days=body.interval_days))  # fmt: skip
    plan.asset = asset
    db.add(plan)
    await db.flush()
    await audit(db, "paper.recurring_buy_created", user_id=user.id, entity_type="recurring_buy", entity_id=plan.id,
                details={"symbol": asset.symbol, "amount_usd": body.amount_usd, "interval_days": body.interval_days})  # fmt: skip
    return _out(plan)


@router.patch("/{plan_id}", response_model=RecurringBuyOut)
async def update_recurring_buy(plan_id: int, body: RecurringBuyUpdate, user: CurrentUser, db: DbSession) -> RecurringBuyOut:
    """Pause or resume. Resuming schedules the next buy one interval from now (paused dates aren't made up)."""
    plan = await _owned(db, plan_id, user.id)
    if body.active and not plan.active:
        active = await db.scalar(select(func.count()).select_from(RecurringBuy).where(RecurringBuy.user_id == user.id, RecurringBuy.active.is_(True)))
        if (active or 0) >= MAX_ACTIVE:
            raise ValidationFailedError(f"You can have up to {MAX_ACTIVE} active recurring buys")
        plan.next_run_at = datetime.now(UTC) + timedelta(days=plan.interval_days)
    plan.active = body.active
    await audit(db, "paper.recurring_buy_resumed" if body.active else "paper.recurring_buy_paused", user_id=user.id,
                entity_type="recurring_buy", entity_id=plan.id)  # fmt: skip
    return _out(plan)


@router.delete("/{plan_id}", status_code=204)
async def delete_recurring_buy(plan_id: int, user: CurrentUser, db: DbSession) -> Response:
    """Stop the plan. Buys it already made stay in the portfolio."""
    plan = await _owned(db, plan_id, user.id)
    await db.delete(plan)
    await audit(db, "paper.recurring_buy_deleted", user_id=user.id, entity_type="recurring_buy", entity_id=plan_id)
    return Response(status_code=204)
