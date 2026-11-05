from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.market_data.service import MarketDataService
from app.models.backtest import BacktestSession
from app.models.strategy import Strategy, StrategyConfiguration
from app.schemas.strategy import BacktestSummary, StrategyConfigIn
from app.strategies.definition import StrategyDefinition


def validate_definition(cfg: StrategyConfigIn) -> StrategyDefinition:
    try:
        return StrategyDefinition(entry=cfg.entry, exit=cfg.exit, risk=cfg.risk)
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc


async def get_owned_strategy(db: AsyncSession, strategy_id: int, user_id: int) -> Strategy:
    s = await db.get(Strategy, strategy_id)
    if s is None or s.user_id != user_id:
        raise NotFoundError("Strategy not found")
    return s


async def ensure_unique_name(db: AsyncSession, user_id: int, name: str, exclude_id: int | None = None) -> None:
    stmt = select(Strategy.id).where(Strategy.user_id == user_id, Strategy.name == name)
    if exclude_id:
        stmt = stmt.where(Strategy.id != exclude_id)
    if await db.scalar(stmt):
        raise ConflictError(f"You already have a strategy named '{name}'")


async def add_configuration(db: AsyncSession, strategy: Strategy, cfg: StrategyConfigIn, version: int) -> StrategyConfiguration:
    validate_definition(cfg)
    asset = await MarketDataService(db).get_asset(cfg.symbol)
    config = StrategyConfiguration(
        strategy_id=strategy.id,
        version=version,
        asset_id=asset.id,
        timeframe=cfg.timeframe,
        entry_rules=cfg.entry.model_dump(),
        exit_rules=cfg.exit.model_dump(),
        risk=cfg.risk.model_dump(),
    )
    config.asset = asset
    db.add(config)
    strategy.current_version = version
    await db.flush()
    await db.refresh(strategy, attribute_names=["configurations"])
    return config


async def latest_backtests(db: AsyncSession, strategy_ids: list[int]) -> dict[int, BacktestSummary]:
    if not strategy_ids:
        return {}
    rows = (
        await db.scalars(
            select(BacktestSession)
            .where(BacktestSession.strategy_id.in_(strategy_ids))
            .order_by(BacktestSession.created_at.desc())
        )
    ).all()
    out: dict[int, BacktestSummary] = {}
    for b in rows:
        if b.strategy_id not in out:
            out[b.strategy_id] = summarize_backtest(b)
    return out


def summarize_backtest(b: BacktestSession) -> BacktestSummary:
    r = b.result
    return BacktestSummary(
        id=b.id,
        strategy_id=b.strategy_id,
        status=b.status,
        timeframe=b.timeframe,
        created_at=b.created_at,
        total_return_pct=r.total_return_pct if r else None,
        max_drawdown_pct=r.max_drawdown_pct if r else None,
        sharpe_ratio=r.sharpe_ratio if r else None,
        win_rate=r.win_rate if r else None,
        num_trades=r.num_trades if r else None,
    )
