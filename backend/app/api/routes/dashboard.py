from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.routes.paper import portfolio_out
from app.api.routes.watchlists import _default_watchlist
from app.core.exceptions import AppError
from app.market_data.service import MarketDataService
from app.models.ai import AIAnalysisResult, TradingSignal
from app.paper_trading.service import PaperTradingService
from app.schemas.analysis import SignalOut
from app.schemas.market import AssetOut, TickerOut
from app.schemas.paper import OrderOut, SnapshotOut
from app.services.sentiment import compute_sentiment

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(user: CurrentUser, db: DbSession) -> dict:
    """One round-trip for the main dashboard. Each section degrades independently."""
    market = MarketDataService(db)
    paper = PaperTradingService(db, market)
    pf = await paper.get_or_create_portfolio(user.id, lock=True)  # order matching mutates it
    await paper.process_open_orders(pf)
    await paper.record_snapshot(pf)
    summary = await paper.summary(pf)
    await db.commit()  # release the portfolio lock before slower read-only sections

    assets = await market.list_assets()
    tickers = await market.get_tickers(assets)
    wl = await _default_watchlist(db, user.id)

    try:
        sentiment = await compute_sentiment(market)
    except AppError:
        sentiment = None

    orders = await paper.list_orders(pf, None, 8)
    history = await paper.equity_history(pf, 500)

    latest_signals = (
        await db.scalars(
            select(TradingSignal)
            .join(AIAnalysisResult, AIAnalysisResult.id == TradingSignal.analysis_id)
            .where(AIAnalysisResult.user_id == user.id)
            .order_by(TradingSignal.created_at.desc())
            .limit(6)
        )
    ).all()
    latest_insight = await db.scalar(
        select(AIAnalysisResult)
        .where(AIAnalysisResult.user_id == user.id)
        .order_by(AIAnalysisResult.created_at.desc())
        .limit(1)
    )

    def tick(symbol: str) -> dict | None:
        t = tickers.get(symbol)
        return TickerOut(**t.to_dict()).model_dump(mode="json") if t else None

    return {
        "portfolio": portfolio_out(summary, paper, await paper.open_stops(pf)).model_dump(mode="json"),
        "equity_history": [SnapshotOut.model_validate(s).model_dump(mode="json") for s in history],
        "market": [
            {"asset": AssetOut.model_validate(a).model_dump(mode="json"), "ticker": tick(a.symbol)} for a in assets
        ],
        "watchlist": [
            {"asset": AssetOut.model_validate(i.asset).model_dump(mode="json"), "ticker": tick(i.asset.symbol)}
            for i in wl.items
        ],
        "recent_orders": [OrderOut.model_validate(o).model_dump(mode="json") for o in orders],
        "signals": [SignalOut.model_validate(s).model_dump(mode="json") for s in latest_signals],
        "insight": {
            "id": latest_insight.id,
            "symbol": latest_insight.asset.symbol,
            "timeframe": latest_insight.timeframe,
            "summary": latest_insight.summary,
            "narrative": latest_insight.narrative,
            "narrative_source": latest_insight.narrative_source,
            "created_at": latest_insight.created_at.isoformat(),
        }
        if latest_insight
        else None,
        "sentiment": sentiment,
        "meta": {
            "source": market.provider.name,
            "is_sample": market.provider.is_sample,
            "attribution": market.provider.attribution,
        },
    }
