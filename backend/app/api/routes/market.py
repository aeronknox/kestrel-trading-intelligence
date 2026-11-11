from collections import OrderedDict

from fastapi import APIRouter, Query, Response
from pydantic_core import to_json

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import PermissionDeniedError, ValidationFailedError
from app.indicators.technical import add_standard_indicators, candles_to_frame, columns_to_points, latest_snapshot
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

# Every viewer of a chart gets the same candles and indicators, so the serialized body is kept
# until any candle in the series changes (a new bar, a live price move or a revision). Stored
# as JSON bytes (about 150 KB for 300 bars), so the memo stays small and skips re-serializing.
CHART_MEMO_SIZE = 128
_chart_memo: OrderedDict[tuple, bytes] = OrderedDict()

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
    if user.is_demo:
        # The tracked-asset list is shared: every addition adds backfill and streaming load for everyone.
        raise PermissionDeniedError("Tracking new assets isn't available in the demo. Create a free account to add assets.")
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
                ticker=TickerOut(**t.to_dict()) if (t := tickers.get(a.symbol)) else None,
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
) -> Response:
    svc = MarketDataService(db)
    asset = await svc.get_asset(symbol)
    # Fetch extra history so long indicators (SMA200) are warmed up across the visible range.
    series = await svc.get_candles(asset, timeframe, limit=min(limit + 200, 2000))
    fingerprint = hash(tuple((c.ts, c.open, c.high, c.low, c.close, c.volume) for c in series.candles))
    key = (asset.symbol, timeframe, limit, series.source, series.is_sample, len(series.candles), fingerprint)
    body = _chart_memo.get(key)
    if body is None:
        df = add_standard_indicators(candles_to_frame(series.candles))
        body = to_json(
            {
                "symbol": asset.symbol,
                "timeframe": timeframe,
                "candles": [
                    {"time": int(c.ts.timestamp()), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume}
                    for c in series.candles[-limit:]
                ],
                "indicators": columns_to_points(df.iloc[-limit:], INDICATOR_COLUMNS),
                "latest": latest_snapshot(df),
            }
        )
        _chart_memo[key] = body
        if len(_chart_memo) > CHART_MEMO_SIZE:
            _chart_memo.popitem(last=False)
    else:
        _chart_memo.move_to_end(key)
    # Provenance of *this* series (an asset may be served by a non-default provider), always current.
    meta = DataMeta(
        source=series.source,
        is_sample=series.is_sample,
        attribution=series.attribution,
        stale=series.stale,
        fetched_at=series.fetched_at,
    )
    return Response(content=body[:-1] + b',"meta":' + meta.model_dump_json().encode() + b"}", media_type="application/json")


@router.get("/assets/{symbol}/history")
async def history_coverage(symbol: str, db: DbSession, _: CurrentUser, timeframe: str = Query("1h")) -> dict:
    """How many closed candles are stored for long backtests (sample data is generated, not stored)."""
    svc = MarketDataService(db)
    if timeframe not in TIMEFRAMES:
        raise ValidationFailedError(f"Unsupported timeframe '{timeframe}'", details={"allowed": list(TIMEFRAMES)})
    return {"symbol": symbol.upper(), "timeframe": timeframe, **await svc.history_coverage(await svc.get_asset(symbol), timeframe)}


@router.get("/sentiment", response_model=SentimentOut)
async def sentiment(db: DbSession, _: CurrentUser) -> SentimentOut:
    svc = MarketDataService(db)
    data = await compute_sentiment(svc)
    return SentimentOut(**data, meta=_meta(svc))
