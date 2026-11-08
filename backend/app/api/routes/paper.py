"""Paper trading API — SIMULATED ONLY. No brokerage connectivity exists."""

from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.core.config import get_settings
from app.core.exceptions import ValidationFailedError
from app.market_data.service import MarketDataService
from app.models.enums import OrderStatus
from app.paper_trading.service import PaperTradingService
from app.schemas.market import AssetOut
from app.schemas.paper import OrderCreate, OrderOut, PortfolioOut, PositionOut, RiskLimits, SnapshotOut, TradeOut
from app.services.audit import audit
from app.services.export import csv_response, safe_filename

router = APIRouter(prefix="/paper", tags=["paper-trading"])


def portfolio_out(summary: dict) -> PortfolioOut:
    pf = summary["portfolio"]
    settings = get_settings()
    equity = summary["equity"] or 1.0
    return PortfolioOut(
        id=pf.id,
        name=pf.name,
        starting_balance=pf.starting_balance,
        cash_balance=pf.cash_balance,
        reserved_cash=summary["reserved_cash"],
        short_liability=summary["short_liability"],
        available_cash=summary["available_cash"],
        positions_value=summary["positions_value"],
        equity=summary["equity"],
        realized_pnl=pf.realized_pnl,
        unrealized_pnl=summary["unrealized_pnl"],
        total_pnl=summary["total_pnl"],
        total_return_pct=summary["total_return_pct"],
        daily_pnl=summary["daily_pnl"],
        daily_pnl_pct=summary["daily_pnl_pct"],
        total_fees=pf.total_fees,
        risk_limits=RiskLimits(
            max_position_pct=pf.max_position_pct,
            max_open_positions=pf.max_open_positions,
            daily_loss_limit_pct=pf.daily_loss_limit_pct,
            allow_short=pf.allow_short,
        ),
        positions=[
            PositionOut(
                id=v.position.id,
                asset=AssetOut.model_validate(v.position.asset),
                side="short" if v.is_short else "long",
                quantity=v.position.quantity,
                avg_entry_price=v.position.avg_entry_price,
                current_price=v.price,
                market_value=v.market_value,
                unrealized_pnl=v.unrealized_pnl,
                unrealized_pnl_pct=(v.price / v.position.avg_entry_price - 1) * 100 * (-1 if v.is_short else 1)
                if v.price is not None and v.position.avg_entry_price
                else None,
                realized_pnl=v.position.realized_pnl,
                allocation_pct=abs(v.market_value) / equity * 100,
                opened_at=v.position.opened_at,
            )
            for v in summary["positions"]
        ],
        prices_complete=summary["prices_complete"],
        fee_bps=settings.paper_fee_bps,
        slippage_bps=settings.paper_slippage_bps,
    )


async def _service_and_portfolio(db, user_id: int, lock: bool = False):  # type: ignore[no-untyped-def]
    svc = PaperTradingService(db)
    pf = await svc.get_or_create_portfolio(user_id, lock=lock)
    return svc, pf


@router.get("/portfolio", response_model=PortfolioOut)
async def get_portfolio(user: CurrentUser, db: DbSession) -> PortfolioOut:
    # Matching resting orders mutates cash/positions, so take the same row lock as order placement.
    svc, pf = await _service_and_portfolio(db, user.id, lock=True)
    await svc.process_open_orders(pf)
    await svc.record_snapshot(pf)
    return portfolio_out(await svc.summary(pf))


@router.put("/portfolio/risk-limits", response_model=PortfolioOut)
async def update_risk_limits(body: RiskLimits, user: CurrentUser, db: DbSession) -> PortfolioOut:
    svc, pf = await _service_and_portfolio(db, user.id, lock=True)
    pf.max_position_pct = body.max_position_pct
    pf.max_open_positions = body.max_open_positions
    pf.daily_loss_limit_pct = body.daily_loss_limit_pct
    if not body.allow_short and any(p.quantity < 0 for p in pf.positions):
        raise ValidationFailedError("Cover your open shorts before turning short selling off")
    pf.allow_short = body.allow_short
    await audit(db, "paper.risk_limits_updated", user_id=user.id, entity_type="portfolio", entity_id=pf.id, details=body.model_dump())
    return portfolio_out(await svc.summary(pf))


@router.post("/portfolio/reset", response_model=PortfolioOut)
async def reset_portfolio(user: CurrentUser, db: DbSession) -> PortfolioOut:
    svc, pf = await _service_and_portfolio(db, user.id, lock=True)
    await svc.reset(pf)
    await audit(db, "paper.portfolio_reset", user_id=user.id, entity_type="portfolio", entity_id=pf.id)
    return portfolio_out(await svc.summary(pf))


@router.post("/orders", response_model=OrderOut, status_code=201, dependencies=[rate_limit("orders")])
async def place_order(body: OrderCreate, user: CurrentUser, db: DbSession) -> object:
    svc, pf = await _service_and_portfolio(db, user.id, lock=True)
    asset = await MarketDataService(db).get_asset(body.symbol)
    order = await svc.place_order(pf, asset, body.side, body.order_type, body.quantity, body.limit_price)
    await audit(db, "paper.order_placed", user_id=user.id, entity_type="order", entity_id=order.id,
                details={"symbol": asset.symbol, "side": body.side.value, "type": body.order_type.value,
                         "quantity": body.quantity, "status": order.status.value})  # fmt: skip
    return order


@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    user: CurrentUser, db: DbSession, status: OrderStatus | None = None, limit: int = Query(100, le=500)
) -> object:
    svc, pf = await _service_and_portfolio(db, user.id)
    return await svc.list_orders(pf, status, limit)


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(order_id: int, user: CurrentUser, db: DbSession) -> object:
    svc, pf = await _service_and_portfolio(db, user.id, lock=True)
    order = await svc.cancel_order(pf, order_id)
    await audit(db, "paper.order_cancelled", user_id=user.id, entity_type="order", entity_id=order.id)
    return order


@router.get("/trades", response_model=list[TradeOut])
async def list_trades(user: CurrentUser, db: DbSession, limit: int = Query(100, le=500)) -> object:
    svc, pf = await _service_and_portfolio(db, user.id)
    return await svc.list_trades(pf, limit)


@router.get("/history", response_model=list[SnapshotOut])
async def equity_history(user: CurrentUser, db: DbSession, limit: int = Query(1000, le=5000)) -> object:
    svc, pf = await _service_and_portfolio(db, user.id)
    return await svc.equity_history(pf, limit)


@router.get("/analytics")
async def analytics(user: CurrentUser, db: DbSession) -> dict:
    svc, pf = await _service_and_portfolio(db, user.id)
    return await svc.analytics(pf)


EXPORT_LIMIT = 100_000


@router.get("/trades.csv")
async def export_trades(user: CurrentUser, db: DbSession) -> Response:
    svc, pf = await _service_and_portfolio(db, user.id)
    trades = await svc.list_trades(pf, EXPORT_LIMIT)
    header = ("executed_at", "symbol", "side", "quantity", "price", "fee", "realized_pnl", "order_id", "simulated")
    rows = ((t.executed_at, t.asset.symbol, t.side.value, t.quantity, t.price, t.fee, t.realized_pnl, t.order_id, True)
            for t in reversed(trades))  # fmt: skip
    return csv_response(safe_filename("paper", "trades"), header, rows)


@router.get("/history.csv")
async def export_history(user: CurrentUser, db: DbSession) -> Response:
    svc, pf = await _service_and_portfolio(db, user.id)
    snaps = await svc.equity_history(pf, EXPORT_LIMIT)
    header = ("time", "equity", "cash", "positions_value")
    return csv_response(safe_filename("paper", "equity"), header, ((s.ts, s.equity, s.cash, s.positions_value) for s in snaps))
