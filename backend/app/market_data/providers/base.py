"""Market data provider interface.

Providers are asset-class agnostic: an `Asset` row stores which provider serves it
and the provider-specific symbol, so stock/forex providers can be added later by
implementing this interface and registering them in `registry.py`.
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

TIMEFRAMES: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}


def timeframe_seconds(timeframe: str) -> int:
    try:
        return TIMEFRAMES[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Use one of {list(TIMEFRAMES)}") from exc


@dataclass(slots=True)
class Candle:
    ts: datetime  # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        return d


@dataclass(slots=True)
class Ticker:
    symbol: str
    price: float
    open_24h: float
    high_24h: float
    low_24h: float
    volume_24h: float
    ts: datetime

    @property
    def change_pct_24h(self) -> float:
        return 0.0 if not self.open_24h else (self.price - self.open_24h) / self.open_24h * 100.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "open_24h": self.open_24h,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "volume_24h": self.volume_24h,
            "change_pct_24h": self.change_pct_24h,
            "ts": self.ts.isoformat(),
        }


@dataclass(slots=True)
class ProductInfo:
    provider_symbol: str
    base_currency: str
    quote_currency: str
    name: str


class ProviderError(Exception):
    pass


class MarketDataProvider(ABC):
    name: str
    #: True only for synthetic data. The UI shows a prominent banner when set.
    is_sample: bool = False
    attribution: str = ""

    @abstractmethod
    async def get_candles(
        self, provider_symbol: str, timeframe: str, limit: int = 300, end: datetime | None = None
    ) -> list[Candle]:
        """Return up to `limit` candles ending at `end` (default: now), oldest first.
        The most recent candle may still be forming."""

    @abstractmethod
    async def get_ticker(self, provider_symbol: str) -> Ticker: ...

    @abstractmethod
    async def list_products(self) -> list[ProductInfo]: ...

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


def utc_from_ts(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=UTC)
