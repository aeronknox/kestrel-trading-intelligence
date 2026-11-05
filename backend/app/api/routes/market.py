from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.indicators.technical import add_standard_indicators, candles_to_frame, latest_snapshot, series_to_points
from app.market_data.providers.base import TIMEFRAMES
from app.market_data.service import MarketDataService
from app.models.enums import AssetClass
from app.schemas.common import DataMeta
from app.schemas.market import (
    AssetOut,
    AssetWithTicker,
    CandlesResponse,
    CatalogEntry,
    MarketOverview,
    SentimentOut,
    TickerOut,
    TrackAssetRequest,
)
from app.services.audit import audit
from app.services.sentiment import compute_sentiment

router = APIRouter(prefix="/market", tags=["market"])

INDICATOR_COLUMNS = [
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "rsi_14", "macd", "macd_signal", "macd_hist",
    "bb_upper", "bb_middle", "bb_lower", "volume_sma_20",
]  # fmt: skip


def _meta(svc: MarketDataService, stale: bool = False, fetched_at=None) -> DataMeta:  # type: ignore[no-untyped-def]
    p = svc.provider
    return DataMeta(source=p.name, is_sample=p.is_sample, attribution=p.attribution, stale=stale, fetched_at=fetched_at)


@router.get("/timeframes")
async def timeframes() -> dict:
    return {"timeframes": list(TIMEFRAMES)}


@router.get("/assets", response_model=list[AssetOut])
async def list_assets(
    db: DbSession, _: CurrentUser, q: str | None = Query(None, max_length=40), asset_class: AssetClass | None = None
) -> object:
    return await MarketDataService(db).list_assets(q, asset_class)


@router.get("/catalog", response_model=list[CatalogEntry])
async def search_catalog(db: DbSession, _: CurrentUser, q: str = Query(min_length=1, max_length=20)) -> object:
    """Search the provider's full product catalog (to start tracking new assets)."""
    return await MarketDataService(db).search_provider_catalog(q)


@router.post("/assets", response_model=AssetOut, status_code=201)
async def track_asset(body: TrackAssetRequest, db: DbSession, user: CurrentUser) -> object:
    asset = await MarketDataService(db).track_asset(body.symbol)
    await audit(db, "asset.tracked", user_id=user.id, entity_type="asset", entity_id=asset.id)
    return asset


@router.get("/overview", response_model=MarketOverview)
async def overview(db: DbSession, _: CurrentUser) -> MarketOverview:
    svc = MarketDataService(db)
    assets = await svc.list_assets()
    tickers = await svc.get_tickers(assets)
    return MarketOverview(
        assets=[
            AssetWithTicker(
                asset=AssetOut.model_validate(a),
                ticker=TickerOut(**tickers[a.symbol].to_dict()) if tickers.get(a.symbol) else None,
            )
            for a in assets
        ],
        meta=_meta(svc),
    )


@router.get("/assets/{symbol}/ticker", response_model=TickerOut)
async def ticker(symbol: str, db: DbSession, _: CurrentUser) -> TickerOut:
    svc = MarketDataService(db)
    t = await svc.get_ticker(await svc.get_asset(symbol))
    return TickerOut(**t.to_dict())


@router.get("/assets/{symbol}/candles", response_model=CandlesResponse)
async def candles(
    symbol: str,
    db: DbSession,
    _: CurrentUser,
    timeframe: str = Query("1h"),
    limit: int = Query(300, ge=10, le=2000),
) -> CandlesResponse:
    svc = MarketDataService(db)
    asset = await svc.get_asset(symbol)
    # Fetch extra history so long indicators (SMA200) are warmed up across the visible range.
    series = await svc.get_candles(asset, timeframe, limit=min(limit + 200, 2000))
    df = add_standard_indicators(candles_to_frame(series.candles))
    visible = df.iloc[-limit:]
    return CandlesResponse(
        symbol=asset.symbol,
        timeframe=timeframe,
        candles=[
            {"time": int(c.ts.timestamp()), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
            for c in series.candles[-limit:]
        ],
        indicators={col: series_to_points(visible, col) for col in INDICATOR_COLUMNS},
        latest=latest_snapshot(df),
        meta=_meta(svc, series.stale, series.fetched_at),
    )


@router.get("/sentiment", response_model=SentimentOut)
async def sentiment(db: DbSession, _: CurrentUser) -> SentimentOut:
    svc = MarketDataService(db)
    data = await compute_sentiment(svc)
    return SentimentOut(**data, meta=_meta(svc))
