from fastapi import APIRouter, Query
from sqlalchemy import select

from app.ai.analysis_engine import run_analysis
from app.api.deps import CurrentUser, DbSession, rate_limit
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.market_data.providers.base import TIMEFRAMES
from app.market_data.service import MarketDataService
from app.models.ai import AIAnalysisResult, TradingSignal
from app.schemas.analysis import AnalysisOut, AnalyzeRequest, SignalOut
from app.services.audit import audit
from app.services.demo import llm_allowed

router = APIRouter(tags=["ai-analysis"])


@router.post("/analysis", response_model=AnalysisOut, status_code=201, dependencies=[rate_limit("analysis", "compute_rate_limit_per_minute")])
async def analyze(body: AnalyzeRequest, user: CurrentUser, db: DbSession) -> object:
    if body.timeframe not in TIMEFRAMES:
        raise ValidationFailedError(f"Unsupported timeframe '{body.timeframe}'")
    asset = await MarketDataService(db).get_asset(body.symbol)
    result = await run_analysis(db, asset, body.timeframe, user.id, narrate=llm_allowed(user))
    await audit(db, "analysis.run", user_id=user.id, entity_type="analysis", entity_id=result.id,
                details={"symbol": asset.symbol, "timeframe": body.timeframe})  # fmt: skip
    return result


@router.get("/analysis", response_model=list[AnalysisOut])
async def list_analyses(
    user: CurrentUser, db: DbSession, symbol: str | None = None, limit: int = Query(20, le=100)
) -> object:
    stmt = select(AIAnalysisResult).where(AIAnalysisResult.user_id == user.id)
    if symbol:
        asset = await MarketDataService(db).get_asset(symbol)
        stmt = stmt.where(AIAnalysisResult.asset_id == asset.id)
    return (await db.scalars(stmt.order_by(AIAnalysisResult.created_at.desc()).limit(limit))).all()


@router.get("/analysis/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(analysis_id: int, user: CurrentUser, db: DbSession) -> object:
    a = await db.get(AIAnalysisResult, analysis_id)
    if a is None or a.user_id != user.id:
        raise NotFoundError("Analysis not found")
    return a


@router.get("/signals", response_model=list[SignalOut])
async def list_signals(
    user: CurrentUser, db: DbSession, symbol: str | None = None, limit: int = Query(50, le=200)
) -> object:
    stmt = (
        select(TradingSignal)
        .join(AIAnalysisResult, AIAnalysisResult.id == TradingSignal.analysis_id)
        .where(AIAnalysisResult.user_id == user.id)
    )
    if symbol:
        asset = await MarketDataService(db).get_asset(symbol)
        stmt = stmt.where(TradingSignal.asset_id == asset.id)
    return (await db.scalars(stmt.order_by(TradingSignal.created_at.desc()).limit(limit))).all()
