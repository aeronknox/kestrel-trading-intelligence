import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.backtesting.engine import BacktestConfig, downsample_equity, run_backtest
from app.core.exceptions import AppError, NotFoundError, ValidationFailedError
from app.core.logging import get_logger
from app.indicators.technical import candles_to_frame
from app.market_data.providers.base import timeframe_seconds
from app.market_data.service import MarketDataService
from app.models.backtest import BacktestResult, BacktestSession
from app.models.enums import BacktestStatus
from app.schemas.strategy import BacktestOut, BacktestRequest, BacktestSummary
from app.services.audit import audit
from app.services.export import csv_response, iso, safe_filename
from app.services.strategies import get_owned_strategy, summarize_backtest
from app.strategies.definition import StrategyDefinition

router = APIRouter(prefix="/backtests", tags=["backtesting"])
logger = get_logger(__name__)


def _out(b: BacktestSession) -> BacktestOut:
    r = b.result
    return BacktestOut(
        id=b.id,
        strategy_id=b.strategy_id,
        strategy_name=b.strategy.name,
        strategy_version=b.config.version,
        asset=b.asset,
        timeframe=b.timeframe,
        start_at=b.start_at,
        end_at=b.end_at,
        initial_capital=b.initial_capital,
        fee_bps=b.fee_bps,
        slippage_bps=b.slippage_bps,
        status=b.status,
        error=b.error,
        data_source=b.data_source,
        created_at=b.created_at,
        completed_at=b.completed_at,
        metrics=r.metrics if r else None,
        equity_curve=r.equity_curve if r else None,
        trades=r.trades if r else None,
    )


@router.post("", response_model=BacktestOut, status_code=201, dependencies=[rate_limit("backtest", "compute_rate_limit_per_minute")])
async def create_backtest(body: BacktestRequest, user: CurrentUser, db: DbSession) -> BacktestOut:
    strategy = await get_owned_strategy(db, body.strategy_id, user.id)
    cfg = strategy.current_config
    if cfg is None:
        raise ValidationFailedError("Strategy has no configuration")
    definition = StrategyDefinition.model_validate({"entry": cfg.entry_rules, "exit": cfg.exit_rules, "risk": cfg.risk})

    session = BacktestSession(
        user_id=user.id,
        strategy_id=strategy.id,
        strategy_config_id=cfg.id,
        asset_id=cfg.asset_id,
        timeframe=cfg.timeframe,
        initial_capital=body.initial_capital,
        fee_bps=body.fee_bps,
        slippage_bps=body.slippage_bps,
        status=BacktestStatus.RUNNING,
    )
    db.add(session)
    await db.flush()

    try:
        market = MarketDataService(db)
        series = await market.get_history(cfg.asset, cfg.timeframe, body.bars)
        closed = series.candles
        if len(closed) < 100:
            raise ValidationFailedError(f"Only {len(closed)} closed candles available; need at least 100")
        df = candles_to_frame(closed)
        output = await asyncio.to_thread(  # CPU-bound: keep the event loop free for other requests
            run_backtest,
            df,
            definition,
            BacktestConfig(
                initial_capital=body.initial_capital,
                fee_bps=body.fee_bps,
                slippage_bps=body.slippage_bps,
                timeframe_seconds=timeframe_seconds(cfg.timeframe),
            ),
        )
        m = output.metrics
        m["warmup_bars"] = output.warmup_bars
        m["signal_counts"] = output.signals
        m["bars_requested"] = body.bars
        m["direction"] = definition.risk.direction
        m["history_complete"] = series.complete
        session.start_at, session.end_at = closed[0].ts, closed[-1].ts
        session.data_source = series.source + (":sample" if series.is_sample else "") + (":stale" if series.stale else "")
        session.result = BacktestResult(
            total_return_pct=m["total_return_pct"],
            buy_hold_return_pct=m["buy_hold_return_pct"],
            max_drawdown_pct=m["max_drawdown_pct"],
            win_rate=m["win_rate"],
            profit_factor=m["profit_factor"],
            sharpe_ratio=m["sharpe_ratio"],
            num_trades=m["num_trades"],
            final_equity=m["final_equity"],
            metrics=m,
            equity_curve=downsample_equity(output.equity, benchmark=output.benchmark),
            trades=[t.to_dict() for t in output.trades],
        )
        session.status = BacktestStatus.COMPLETED
    except AppError as exc:
        session.status, session.error = BacktestStatus.FAILED, exc.message
    except Exception as exc:
        logger.exception("backtest_failed", backtest_id=session.id)
        session.status, session.error = BacktestStatus.FAILED, f"Backtest failed: {type(exc).__name__}"
    session.completed_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(session, attribute_names=["result", "strategy", "config", "asset"])
    await audit(db, "backtest.run", user_id=user.id, entity_type="backtest", entity_id=session.id,
                details={"strategy_id": strategy.id, "status": session.status.value})  # fmt: skip
    return _out(session)


@router.get("", response_model=list[BacktestSummary])
async def list_backtests(
    user: CurrentUser, db: DbSession, strategy_id: int | None = None, limit: int = Query(50, le=200)
) -> list[BacktestSummary]:
    stmt = select(BacktestSession).where(BacktestSession.user_id == user.id)
    if strategy_id:
        stmt = stmt.where(BacktestSession.strategy_id == strategy_id)
    rows = (await db.scalars(stmt.order_by(BacktestSession.created_at.desc()).limit(limit))).all()
    return [summarize_backtest(b) for b in rows]


@router.get("/compare", response_model=list[BacktestOut])
async def compare(user: CurrentUser, db: DbSession, ids: str = Query(..., description="Comma-separated backtest ids")) -> list[BacktestOut]:
    try:
        id_list = [int(x) for x in ids.split(",") if x.strip()][:6]
    except ValueError as exc:
        raise ValidationFailedError("ids must be comma-separated integers") from exc
    rows = (
        await db.scalars(select(BacktestSession).where(BacktestSession.id.in_(id_list), BacktestSession.user_id == user.id))
    ).all()
    by_id = {b.id: b for b in rows}
    return [_out(by_id[i]) for i in id_list if i in by_id]


async def _owned(db, backtest_id: int, user_id: int) -> BacktestSession:  # type: ignore[no-untyped-def]
    b = await db.get(BacktestSession, backtest_id)
    if b is None or b.user_id != user_id:
        raise NotFoundError("Backtest not found")
    return b


@router.get("/{backtest_id}", response_model=BacktestOut)
async def get_backtest(backtest_id: int, user: CurrentUser, db: DbSession) -> BacktestOut:
    return _out(await _owned(db, backtest_id, user.id))


TRADE_COLUMNS = ("entry_time", "entry_price", "quantity", "entry_fee", "exit_time", "exit_price", "exit_fee",
                 "exit_reason", "pnl", "return_pct", "bars_held")  # fmt: skip


@router.get("/{backtest_id}/trades.csv")
async def export_trades(backtest_id: int, user: CurrentUser, db: DbSession) -> Response:
    b = await _owned(db, backtest_id, user.id)
    trades = b.result.trades if b.result else []
    rows = (
        [iso(t["entry_time"]) if c == "entry_time" else iso(t["exit_time"]) if c == "exit_time" else t.get(c) for c in TRADE_COLUMNS]
        for t in trades
    )
    return csv_response(safe_filename("backtest", b.id, b.strategy.name, b.asset.symbol, b.timeframe, "trades"), TRADE_COLUMNS, rows)


@router.get("/{backtest_id}/equity.csv")
async def export_equity(backtest_id: int, user: CurrentUser, db: DbSession) -> Response:
    """The stored equity curve (sampled to at most ~500 points), with buy-and-hold when available."""
    b = await _owned(db, backtest_id, user.id)
    curve = b.result.equity_curve if b.result else []
    header = ("time", "equity", "drawdown_pct", "buy_and_hold_equity")
    rows = ((iso(p["time"]), p["equity"], p["drawdown_pct"], p.get("benchmark")) for p in curve)
    return csv_response(safe_filename("backtest", b.id, b.strategy.name, b.asset.symbol, b.timeframe, "equity"), header, rows)


@router.delete("/{backtest_id}", status_code=204)
async def delete_backtest(backtest_id: int, user: CurrentUser, db: DbSession) -> Response:
    await db.delete(await _owned(db, backtest_id, user.id))
    return Response(status_code=204)
