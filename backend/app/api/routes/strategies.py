from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.strategy import Strategy
from app.schemas.strategy import StrategyCreate, StrategyOut, StrategyUpdate
from app.services import strategies as svc
from app.services.audit import audit
from app.strategies.definition import INDICATOR_FIELDS, INDICATOR_PARAMS, TEMPLATES

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _out(strategy: Strategy, latest: dict) -> StrategyOut:
    out = StrategyOut.model_validate(strategy)
    out.latest_backtest = latest.get(strategy.id)
    return out


@router.get("/templates")
async def templates() -> dict:
    return {"templates": TEMPLATES}


@router.get("/indicators")
async def indicators() -> dict:
    """Indicator catalog used by the strategy builder UI."""
    return {
        "indicators": [
            {
                "name": name,
                "params": {p: {"default": d, "min": lo, "max": hi} for p, (d, lo, hi) in spec.items()},
                "fields": list(INDICATOR_FIELDS.get(name, ())),
            }
            for name, spec in INDICATOR_PARAMS.items()
        ],
        "operators": [">", "<", ">=", "<=", "crosses_above", "crosses_below"],
    }


@router.get("", response_model=list[StrategyOut])
async def list_strategies(user: CurrentUser, db: DbSession, include_archived: bool = Query(False)) -> object:
    stmt = select(Strategy).where(Strategy.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(Strategy.is_archived.is_(False))
    rows = list((await db.scalars(stmt.order_by(Strategy.updated_at.desc()))).all())
    latest = await svc.latest_backtests(db, [s.id for s in rows])
    return [_out(s, latest) for s in rows]


@router.post("", response_model=StrategyOut, status_code=201)
async def create_strategy(body: StrategyCreate, user: CurrentUser, db: DbSession) -> object:
    name = body.name.strip()
    await svc.ensure_unique_name(db, user.id, name)
    svc.validate_definition(body.config)
    strategy = Strategy(user_id=user.id, name=name, description=body.description, current_version=1)
    db.add(strategy)
    await db.flush()
    await svc.add_configuration(db, strategy, body.config, version=1)
    await audit(db, "strategy.created", user_id=user.id, entity_type="strategy", entity_id=strategy.id)
    return _out(strategy, {})


@router.get("/{strategy_id}", response_model=StrategyOut)
async def get_strategy(strategy_id: int, user: CurrentUser, db: DbSession) -> object:
    strategy = await svc.get_owned_strategy(db, strategy_id, user.id)
    return _out(strategy, await svc.latest_backtests(db, [strategy.id]))


@router.patch("/{strategy_id}", response_model=StrategyOut)
async def update_strategy(strategy_id: int, body: StrategyUpdate, user: CurrentUser, db: DbSession) -> object:
    strategy = await svc.get_owned_strategy(db, strategy_id, user.id)
    if body.name is not None and body.name.strip() != strategy.name:
        await svc.ensure_unique_name(db, user.id, body.name.strip(), exclude_id=strategy.id)
        strategy.name = body.name.strip()
    if body.description is not None:
        strategy.description = body.description
    if body.is_archived is not None:
        strategy.is_archived = body.is_archived
    if body.config is not None:
        next_version = max((c.version for c in strategy.configurations), default=0) + 1
        await svc.add_configuration(db, strategy, body.config, version=next_version)
    await db.flush()
    await audit(db, "strategy.updated", user_id=user.id, entity_type="strategy", entity_id=strategy.id,
                details={"version": strategy.current_version})  # fmt: skip
    return _out(strategy, await svc.latest_backtests(db, [strategy.id]))


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: int, user: CurrentUser, db: DbSession) -> Response:
    strategy = await svc.get_owned_strategy(db, strategy_id, user.id)
    await db.delete(strategy)
    await audit(db, "strategy.deleted", user_id=user.id, entity_type="strategy", entity_id=strategy_id)
    return Response(status_code=204)
