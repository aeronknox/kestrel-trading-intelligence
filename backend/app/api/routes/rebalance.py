"""Rebalance the paper portfolio to target weights. SIMULATED ONLY: market orders in the paper portfolio."""

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.api.routes.paper import _service_and_portfolio
from app.core.exceptions import ValidationFailedError
from app.market_data.service import MarketDataService
from app.models.enums import OrderSide
from app.paper_trading import rebalance
from app.schemas.paper import OrderOut
from app.services.audit import audit

router = APIRouter(prefix="/paper/rebalance", tags=["paper-trading"])


class Target(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    pct: float = Field(ge=0, le=100, description="% of equity; 0 sells the whole position")


class RebalanceIn(BaseModel):
    targets: list[Target] = Field(min_length=1, max_length=20)

    @field_validator("targets")
    @classmethod
    def unique(cls, v: list[Target]) -> list[Target]:
        symbols = [t.symbol.upper() for t in v]
        if len(set(symbols)) != len(symbols):
            raise ValueError("Each asset can appear only once")
        return v


class LegOut(BaseModel):
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    value: float
    current_pct: float
    target_pct: float


class PlanOut(BaseModel):
    equity: float
    legs: list[LegOut]
    unchanged: list[str]
    cash_after_pct: float
    drift_band_usd: float  # differences smaller than this are left alone


class RebalanceOut(BaseModel):
    message: str
    orders: list[OrderOut]


async def _plan(body: RebalanceIn, user_id: int, db: DbSession, lock: bool):  # type: ignore[no-untyped-def]
    svc, pf = await _service_and_portfolio(db, user_id, lock=lock)
    market = MarketDataService(db)
    assets = [await market.get_asset(t.symbol) for t in body.targets]
    plan = await rebalance.plan_rebalance(svc, pf, assets, [t.pct for t in body.targets])
    return svc, pf, plan


def _plan_out(plan: rebalance.Plan) -> PlanOut:
    return PlanOut(
        equity=plan.equity, unchanged=plan.unchanged, cash_after_pct=plan.cash_after_pct,
        drift_band_usd=max(rebalance.MIN_TRADE_USD, plan.equity * rebalance.DRIFT_PCT / 100),
        legs=[LegOut(symbol=leg.asset.symbol, side=leg.side, quantity=leg.quantity, price=leg.price, value=leg.value,
                     current_pct=leg.current_pct, target_pct=leg.target_pct) for leg in plan.legs],
    )  # fmt: skip


@router.post("/preview", response_model=PlanOut)
async def preview_rebalance(body: RebalanceIn, user: CurrentUser, db: DbSession) -> PlanOut:
    """The orders that would bring the listed assets to their target weights, at current prices. Nothing is placed."""
    _, _, plan = await _plan(body, user.id, db, lock=False)
    return _plan_out(plan)


@router.post("", response_model=RebalanceOut, dependencies=[rate_limit("orders")])
async def run_rebalance(body: RebalanceIn, user: CurrentUser, db: DbSession) -> RebalanceOut:
    """Plan again at current prices and place the orders (simulated market orders, sells first)."""
    svc, pf, plan = await _plan(body, user.id, db, lock=True)
    if not plan.legs:
        raise ValidationFailedError("Already on target: nothing to trade")
    orders = await rebalance.execute(svc, pf, plan)
    done = rebalance.filled(orders)
    await audit(db, "paper.rebalanced", user_id=user.id, entity_type="portfolio", entity_id=pf.id,
                details={"targets": {t.symbol.upper(): t.pct for t in body.targets}, "orders": len(orders), "filled": done})  # fmt: skip
    rejected = [o for o in orders if o.status.value != "filled"]
    message = f"Rebalanced: {done} of {len(orders)} order{'s' if len(orders) != 1 else ''} filled"
    if rejected:
        message += ". Not filled: " + "; ".join(f"{o.asset.symbol} {o.side.value}: {o.reject_reason}" for o in rejected)
    return RebalanceOut(message=message, orders=[OrderOut.model_validate(o) for o in orders])
