"""Strategy alerts and their notifications. Research signals only; nothing places orders."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.market_data.service import MarketDataService
from app.models.alert import AlertEvent, StrategyAlert
from app.paper_trading.service import PaperTradingService
from app.schemas.common import ORMModel
from app.services.alerts import DISCLAIMER
from app.services.forward_test import SHORTS_DISABLED, forward_test_summary
from app.services.strategies import get_owned_strategy

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertSettings(BaseModel):
    enabled: bool = True
    on_entry: bool = True
    on_exit: bool = True
    notify_email: bool = False
    notify_webhook: bool = False  # to the webhook set in account settings
    auto_trade: bool = False  # forward test: simulated paper orders on the strategy's signals


class AlertOut(AlertSettings):
    id: int
    strategy_id: int
    strategy_name: str
    symbol: str | None
    timeframe: str | None
    last_bar_at: datetime | None
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime


class AlertEventOut(ORMModel):
    id: int
    strategy_id: int
    strategy_version: int
    kind: str
    symbol: str
    timeframe: str
    bar_at: datetime
    close_price: float
    message: str
    data_source: str
    created_at: datetime
    read_at: datetime | None
    emailed_at: datetime | None
    order_id: int | None = None


class EventsPage(BaseModel):
    events: list[AlertEventOut]
    unread: int
    disclaimer: str = DISCLAIMER


class MarkRead(BaseModel):
    ids: list[int] | None = Field(None, max_length=500, description="Omit to mark everything read")


def _out(a: StrategyAlert) -> AlertOut:
    cfg = a.strategy.current_config
    return AlertOut(
        id=a.id, strategy_id=a.strategy_id, strategy_name=a.strategy.name, enabled=a.enabled, on_entry=a.on_entry,
        on_exit=a.on_exit, notify_email=a.notify_email, notify_webhook=a.notify_webhook, auto_trade=a.auto_trade, symbol=cfg.asset.symbol if cfg else None,
        timeframe=cfg.timeframe if cfg else None, last_bar_at=a.last_bar_at, last_checked_at=a.last_checked_at,
        last_error=a.last_error, created_at=a.created_at,
    )  # fmt: skip


@router.get("", response_model=list[AlertOut])
async def list_alerts(user: CurrentUser, db: DbSession) -> list[AlertOut]:
    rows = (await db.scalars(select(StrategyAlert).where(StrategyAlert.user_id == user.id).order_by(StrategyAlert.id))).all()
    return [_out(a) for a in rows]


@router.get("/strategy/{strategy_id}", response_model=AlertOut | None)
async def get_alert(strategy_id: int, user: CurrentUser, db: DbSession) -> AlertOut | None:
    await get_owned_strategy(db, strategy_id, user.id)
    alert = await db.scalar(select(StrategyAlert).where(StrategyAlert.strategy_id == strategy_id))
    return _out(alert) if alert else None


@router.put("/strategy/{strategy_id}", response_model=AlertOut)
async def upsert_alert(strategy_id: int, body: AlertSettings, user: CurrentUser, db: DbSession) -> AlertOut:
    strategy = await get_owned_strategy(db, strategy_id, user.id)
    cfg = strategy.current_config
    if body.auto_trade and cfg is not None and (cfg.risk or {}).get("direction", "long") == "short":
        portfolio = await PaperTradingService(db).get_or_create_portfolio(user.id)
        if not portfolio.allow_short:
            raise ValidationFailedError(SHORTS_DISABLED)
    alert = await db.scalar(select(StrategyAlert).where(StrategyAlert.strategy_id == strategy_id))
    if alert is None:
        alert = StrategyAlert(user_id=user.id, strategy_id=strategy.id)
        db.add(alert)
    elif body.enabled and not alert.enabled:
        alert.last_bar_at = None  # re-enabled: start from the newest bar, don't replay the gap
    # Demo accounts have no mailbox; their alerts stay in-app.
    notify_email = body.notify_email and not user.is_demo
    alert.enabled, alert.on_entry, alert.on_exit, alert.notify_email = body.enabled, body.on_entry, body.on_exit, notify_email
    alert.auto_trade = body.auto_trade
    alert.notify_webhook = body.notify_webhook and not user.is_demo
    await db.flush()
    await db.refresh(alert, attribute_names=["strategy"])
    return _out(alert)


@router.get("/strategy/{strategy_id}/forward-test")
async def forward_test(strategy_id: int, user: CurrentUser, db: DbSession) -> dict:
    """The strategy's own simulated paper trades (round trips) and any open position."""
    await get_owned_strategy(db, strategy_id, user.id)
    return {**await forward_test_summary(db, MarketDataService(db), user.id, strategy_id), "disclaimer": DISCLAIMER}


@router.delete("/strategy/{strategy_id}", status_code=204)
async def delete_alert(strategy_id: int, user: CurrentUser, db: DbSession) -> Response:
    await get_owned_strategy(db, strategy_id, user.id)
    alert = await db.scalar(select(StrategyAlert).where(StrategyAlert.strategy_id == strategy_id))
    if alert is None:
        raise NotFoundError("No alert for this strategy")
    await db.delete(alert)
    return Response(status_code=204)


@router.get("/events", response_model=EventsPage)
async def list_events(
    user: CurrentUser, db: DbSession, unread_only: bool = False, limit: int = Query(50, ge=1, le=500)
) -> EventsPage:
    stmt = select(AlertEvent).where(AlertEvent.user_id == user.id)
    if unread_only:
        stmt = stmt.where(AlertEvent.read_at.is_(None))
    events = (await db.scalars(stmt.order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc()).limit(limit))).all()
    unread = await db.scalar(
        select(func.count()).select_from(AlertEvent).where(AlertEvent.user_id == user.id, AlertEvent.read_at.is_(None))
    )
    return EventsPage(events=[AlertEventOut.model_validate(e) for e in events], unread=int(unread or 0))


@router.post("/events/read", response_model=EventsPage)
async def mark_read(body: MarkRead, user: CurrentUser, db: DbSession) -> EventsPage:
    stmt = update(AlertEvent).where(AlertEvent.user_id == user.id, AlertEvent.read_at.is_(None))
    if body.ids is not None:
        stmt = stmt.where(AlertEvent.id.in_(body.ids))
    await db.execute(stmt.values(read_at=datetime.now(UTC)))
    return await list_events(user, db, unread_only=False, limit=50)
