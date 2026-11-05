"""SAMPLE (synthetic) market data for offline development and tests.

THIS IS NOT REAL MARKET DATA. Every response from this provider is flagged with
`is_sample=True`, and the frontend displays a persistent warning banner.

Prices are a deterministic function of (symbol, timeframe, bar index), so repeated
requests are consistent with each other without storing state.
"""

import hashlib
import math
from datetime import UTC, datetime

from app.market_data.providers.base import (
    Candle,
    MarketDataProvider,
    ProductInfo,
    ProviderError,
    Ticker,
    timeframe_seconds,
    utc_from_ts,
)

_BASE_PRICES = {
    "BTC": 60000.0,
    "ETH": 3000.0,
    "SOL": 150.0,
    "XRP": 0.6,
    "ADA": 0.45,
    "DOGE": 0.12,
    "AVAX": 30.0,
    "LINK": 15.0,
    "LTC": 80.0,
    "DOT": 6.0,
}


def _unit(seed: str) -> float:
    """Deterministic pseudo-random number in [0, 1)."""
    h = hashlib.blake2b(seed.encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2**64


class SampleProvider(MarketDataProvider):
    name = "sample"
    is_sample = True
    attribution = "SAMPLE DATA — synthetic prices for development only, not real market data"

    def _price(self, symbol: str, k: int, granularity: int) -> float:
        base = _BASE_PRICES.get(symbol.split("-")[0], 100.0)
        phase = _unit(symbol) * 1000
        # Express time in hours so the shape is similar across timeframes.
        t = k * granularity / 3600.0
        log_dev = (
            0.18 * math.sin((t + phase) / 700.0)
            + 0.07 * math.sin((t + phase) / 90.0)
            + 0.025 * math.sin((t + phase) / 11.0)
            + 0.006 * (_unit(f"{symbol}:{granularity}:{k}") - 0.5)
        )
        return base * math.exp(log_dev)

    def _candle(self, symbol: str, k: int, granularity: int) -> Candle:
        o = self._price(symbol, k - 1, granularity)
        c = self._price(symbol, k, granularity)
        wiggle = abs(c - o) * 0.6 + o * 0.0015 * _unit(f"w:{symbol}:{k}")
        high = max(o, c) + wiggle * _unit(f"h:{symbol}:{k}")
        low = min(o, c) - wiggle * _unit(f"l:{symbol}:{k}")
        volume = 50 + 1000 * _unit(f"v:{symbol}:{granularity}:{k}") * (1 + abs(c - o) / o * 50)
        return Candle(ts=utc_from_ts(k * granularity), open=o, high=high, low=low, close=c, volume=volume)

    async def get_candles(
        self, provider_symbol: str, timeframe: str, limit: int = 300, end: datetime | None = None
    ) -> list[Candle]:
        if provider_symbol.split("-")[0] not in _BASE_PRICES:
            raise ProviderError(f"Sample provider has no data for {provider_symbol}")
        g = timeframe_seconds(timeframe)
        end_k = int((end or datetime.now(UTC)).timestamp() // g)
        return [self._candle(provider_symbol, k, g) for k in range(end_k - limit + 1, end_k + 1)]

    async def get_ticker(self, provider_symbol: str) -> Ticker:
        candles = await self.get_candles(provider_symbol, "1h", limit=25)
        last = candles[-1]
        window = candles[-24:]
        return Ticker(
            symbol=provider_symbol,
            price=last.close,
            open_24h=window[0].open,
            high_24h=max(c.high for c in window),
            low_24h=min(c.low for c in window),
            volume_24h=sum(c.volume for c in window),
            ts=datetime.now(UTC),
        )

    async def list_products(self) -> list[ProductInfo]:
        return [
            ProductInfo(provider_symbol=f"{b}-USD", base_currency=b, quote_currency="USD", name=f"{b}/USD (sample)")
            for b in _BASE_PRICES
        ]
