"""Parameter sweeps and walk-forward analysis — HYPOTHETICAL research on historical data."""

import asyncio

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, rate_limit
from app.backtesting.engine import BacktestConfig
from app.backtesting.optimization import OptimizationError, ParamGrid, run_sweep, run_walk_forward, tunable_parameters
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.indicators.technical import candles_to_frame
from app.market_data.providers.base import timeframe_seconds
from app.market_data.service import MarketDataService
from app.models.backtest import ResearchRun
from app.models.strategy import Strategy
from app.schemas.research import ResearchOut, ResearchRequest, ResearchSummary, TunableParameter, WalkForwardRequest
from app.services.audit import audit
from app.services.export import csv_response, iso, safe_filename
from app.services.strategies import get_owned_strategy

router = APIRouter(prefix="/research", tags=["research"])
compute_limit = rate_limit("research", "compute_rate_limit_per_minute")


def _definition(strategy: Strategy) -> dict:
    cfg = strategy.current_config
    if cfg is None:
        raise ValidationFailedError("Strategy has no configuration")
    return {"entry": cfg.entry_rules, "exit": cfg.exit_rules, "risk": cfg.risk}


def _summary(run: ResearchRun) -> dict:
    verdict = run.result.get("verdict") if run.kind == "walk_forward" else None
    return {
        "id": run.id,
        "kind": run.kind,
        "strategy_id": run.strategy_id,
        "strategy_name": run.strategy.name,
        "strategy_version": run.config.version,
        "asset": run.asset,
        "timeframe": run.timeframe,
        "start_at": run.start_at,
        "end_at": run.end_at,
        "data_source": run.data_source,
        "created_at": run.created_at,
        "headline": verdict["headline"] if verdict else None,
    }


def _out(run: ResearchRun) -> ResearchOut:
    return ResearchOut(**_summary(run), request=run.request, result=run.result)


async def _execute(kind: str, body: ResearchRequest, user_id: int, db) -> ResearchOut:  # type: ignore[no-untyped-def]
    strategy = await get_owned_strategy(db, body.strategy_id, user_id)
    definition = _definition(strategy)
    cfg = strategy.current_config
    assert cfg is not None
    series = await MarketDataService(db).get_history(cfg.asset, cfg.timeframe, body.bars)
    closed = series.candles
    if len(closed) < 200:
        raise ValidationFailedError(f"Only {len(closed)} closed candles available; need at least 200")
    df = candles_to_frame(closed)
    config = BacktestConfig(body.initial_capital, body.fee_bps, body.slippage_bps, timeframe_seconds(cfg.timeframe))
    grid = [ParamGrid(p.path, p.values) for p in body.params]
    try:
        # CPU-bound (up to a few hundred backtests): keep it off the event loop.
        if isinstance(body, WalkForwardRequest):
            result = await asyncio.to_thread(
                run_walk_forward, df, definition, grid, config, folds=body.folds, is_ratio=body.is_ratio,
                objective=body.objective, min_trades=body.min_trades,
            )  # fmt: skip
        else:
            result = await asyncio.to_thread(
                run_sweep, df, definition, grid, config, objective=body.objective, min_trades=body.min_trades
            )
    except OptimizationError as exc:
        raise ValidationFailedError(str(exc)) from exc

    run = ResearchRun(
        user_id=user_id,
        strategy_id=strategy.id,
        strategy_config_id=cfg.id,
        asset_id=cfg.asset_id,
        kind=kind,
        timeframe=cfg.timeframe,
        start_at=closed[0].ts,
        end_at=closed[-1].ts,
        request=body.model_dump() | {"bars_used": len(closed), "history_complete": series.complete},
        result=result,
        data_source=series.source + (":sample" if series.is_sample else "") + (":stale" if series.stale else ""),
    )
    db.add(run)
    await db.flush()
    await db.refresh(run, attribute_names=["strategy", "config", "asset"])
    await audit(db, f"research.{kind}", user_id=user_id, entity_type="research_run", entity_id=run.id,
                details={"strategy_id": strategy.id, "params": [p.path for p in body.params]})  # fmt: skip
    return _out(run)


@router.get("/parameters", response_model=list[TunableParameter])
async def parameters(user: CurrentUser, db: DbSession, strategy_id: int = Query(...)) -> list[dict]:
    """Numeric settings of the strategy's current version that a sweep can vary."""
    strategy = await get_owned_strategy(db, strategy_id, user.id)
    return tunable_parameters(_definition(strategy))


@router.post("/sweeps", response_model=ResearchOut, status_code=201, dependencies=[compute_limit])
async def create_sweep(body: ResearchRequest, user: CurrentUser, db: DbSession) -> ResearchOut:
    return await _execute("sweep", body, user.id, db)


@router.post("/walk-forward", response_model=ResearchOut, status_code=201, dependencies=[compute_limit])
async def create_walk_forward(body: WalkForwardRequest, user: CurrentUser, db: DbSession) -> ResearchOut:
    return await _execute("walk_forward", body, user.id, db)


@router.get("", response_model=list[ResearchSummary])
async def list_runs(
    user: CurrentUser, db: DbSession, strategy_id: int | None = None, limit: int = Query(50, le=200)
) -> list[dict]:
    stmt = select(ResearchRun).where(ResearchRun.user_id == user.id)
    if strategy_id:
        stmt = stmt.where(ResearchRun.strategy_id == strategy_id)
    rows = (await db.scalars(stmt.order_by(ResearchRun.created_at.desc()).limit(limit))).all()
    return [_summary(r) for r in rows]


async def _owned(db, run_id: int, user_id: int) -> ResearchRun:  # type: ignore[no-untyped-def]
    run = await db.get(ResearchRun, run_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError("Research run not found")
    return run


@router.get("/{run_id}", response_model=ResearchOut)
async def get_run(run_id: int, user: CurrentUser, db: DbSession) -> ResearchOut:
    return _out(await _owned(db, run_id, user.id))


METRIC_COLUMNS = ("total_return_pct", "sharpe_ratio", "max_drawdown_pct", "num_trades", "win_rate", "profit_factor")


@router.get("/{run_id}/results.csv")
async def export_results(run_id: int, user: CurrentUser, db: DbSession) -> Response:
    """Sweeps: one row per parameter combination. Walk-forward: one row per fold."""
    run = await _owned(db, run_id, user.id)
    r = run.result
    labels = [p.get("label", p["path"]) for p in r["params"]]
    name = safe_filename(run.kind.replace("_", "-"), run.id, run.strategy.name, run.asset.symbol, run.timeframe)
    if run.kind == "sweep":
        header = (*labels, "valid", "score", *METRIC_COLUMNS)
        rows = (
            (*c["values"], c["valid"], c["score"], *((c["metrics"] or {}).get(k) for k in METRIC_COLUMNS))
            for c in r["cells"]
        )
        return csv_response(name, header, rows)
    header = ("fold", "tuning_start", "tuning_end", "test_start", "test_end", *(f"chosen: {lb}" for lb in labels),
              *(f"tuning_{k}" for k in METRIC_COLUMNS), *(f"test_{k}" for k in METRIC_COLUMNS), "untuned_test_return_pct")  # fmt: skip
    paths = [p["path"] for p in r["params"]]
    rows = (
        (
            f["fold"],
            iso(f["in_sample"]["start"]),
            iso(f["in_sample"]["end"]),
            iso(f["out_of_sample"]["start"]),
            iso(f["out_of_sample"]["end"]),
            *((f["chosen"] or {}).get(p) for p in paths),
            *(f["is_metrics"].get(k) for k in METRIC_COLUMNS),
            *(f["oos_metrics"].get(k) for k in METRIC_COLUMNS),
            f["baseline_oos_return_pct"],
        )
        for f in r["fold_results"]
    )
    return csv_response(name, header, rows)


@router.delete("/{run_id}", status_code=204)
async def delete_run(run_id: int, user: CurrentUser, db: DbSession) -> Response:
    await db.delete(await _owned(db, run_id, user.id))
    return Response(status_code=204)
