from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AssetClass
from app.schemas.common import DataMeta, ORMModel


class AssetOut(ORMModel):
    id: int
    symbol: str
    name: str
    asset_class: AssetClass
    base_currency: str
    quote_currency: str
    provider: str


class TickerOut(BaseModel):
    symbol: str
    price: float
    open_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    change_pct_24h: float
    ts: datetime


class AssetWithTicker(BaseModel):
    asset: AssetOut
    ticker: TickerOut | None


class MarketOverview(BaseModel):
    assets: list[AssetWithTicker]
    meta: DataMeta


class CandleOut(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class Point(BaseModel):
    time: int
    value: float


class CandlesResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[CandleOut]
    indicators: dict[str, list[Point]]
    latest: dict[str, float | None]
    meta: DataMeta


class CatalogEntry(BaseModel):
    symbol: str
    base: str
    quote: str
    name: str
    tracked: bool


class TrackAssetRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9]+-[A-Za-z0-9]+$")


class WatchlistItemOut(ORMModel):
    id: int
    asset: AssetOut
    position: int
    added_at: datetime


class WatchlistOut(ORMModel):
    id: int
    name: str
    items: list[WatchlistItemOut]


class WatchlistAddRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)


class SentimentOut(BaseModel):
    fear_greed: dict | None
    breadth_above_sma50_pct: float | None
    avg_rsi: float | None
    advancers: int
    decliners: int
    avg_change_pct_24h: float | None
    label: str
    meta: DataMeta
