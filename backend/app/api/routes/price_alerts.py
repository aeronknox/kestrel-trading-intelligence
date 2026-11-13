"""Price alerts: be notified when an asset reaches a price. Research notifications only; no orders."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.market_data.service import MarketDataService
from app.models.price_alert import PriceAlert
from app.schemas.common import ORMModel
from app.schemas.market import AssetOut
from app.services.audit import audit

router = APIRouter(prefix="/price-alerts", tags=["alerts"])

MAX_ACTIVE = 50
HISTORY = 50


class PriceAlertIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    target: float = Field(gt=0, le=1e12)
    note: str = Field("", max_length=120)
    notify_webhook: bool = False


class PriceAlertOut(ORMModel):
    id: int
    asset: AssetOut
    condition: Literal["above", "below"]
    target: float
    created_price: float
    note: str
    notify_webhook: bool
    created_at: datetime
    triggered_at: datetime | None
    triggered_price: float | None


@router.get("", response_model=list[PriceAlertOut])
async def list_price_alerts(user: CurrentUser, db: DbSession, symbol: str | None = None) -> object:
    """Active alerts (nearest first per asset), then the most recent ones that fired."""
    base = select(PriceAlert).where(PriceAlert.user_id == user.id)
    if symbol:
        base = base.where(PriceAlert.asset_id == (await MarketDataService(db).get_asset(symbol)).id)
    active = (await db.scalars(base.where(PriceAlert.triggered_at.is_(None)).order_by(PriceAlert.created_at.desc()))).all()
    fired = (
        await db.scalars(base.where(PriceAlert.triggered_at.is_not(None)).order_by(PriceAlert.triggered_at.desc()).limit(HISTORY))
    ).all()
    return [*active, *fired]


@router.post("", response_model=PriceAlertOut, status_code=201)
async def create_price_alert(body: PriceAlertIn, user: CurrentUser, db: DbSession) -> PriceAlert:
    market = MarketDataService(db)
    asset = await market.get_asset(body.symbol)
    count = await db.scalar(
        select(func.count()).select_from(PriceAlert).where(PriceAlert.user_id == user.id, PriceAlert.triggered_at.is_(None))
    )
    if (count or 0) >= MAX_ACTIVE:
        raise ValidationFailedError(f"You can have up to {MAX_ACTIVE} active price alerts; delete some first")
    price = (await market.get_ticker(asset)).price  # the real current price decides the direction
    if body.target == price:
        raise ValidationFailedError(f"{asset.symbol} is already at {price:,.2f}; choose a level above or below it")
    alert = PriceAlert(
        user_id=user.id, asset_id=asset.id, condition="above" if body.target > price else "below", target=body.target,
        created_price=price, note=" ".join(body.note.split()), notify_webhook=body.notify_webhook,
    )  # fmt: skip
    alert.asset = asset
    db.add(alert)
    await db.flush()
    await audit(db, "price_alert.created", user_id=user.id, entity_type="price_alert", entity_id=alert.id,
                details={"symbol": asset.symbol, "condition": alert.condition, "target": body.target})  # fmt: skip
    return alert


@router.delete("/{alert_id}", status_code=204)
async def delete_price_alert(alert_id: int, user: CurrentUser, db: DbSession) -> Response:
    alert = await db.scalar(select(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user.id))
    if alert is None:
        raise NotFoundError("Price alert not found")
    await db.delete(alert)
    return Response(status_code=204)
