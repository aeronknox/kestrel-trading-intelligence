"""Coinbase Exchange public market data (https://docs.cdp.coinbase.com/exchange/).

Uses only unauthenticated, public endpoints. Data is real exchange data from Coinbase.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.core.logging import get_logger
from app.market_data.providers.base import (
    Candle,
    MarketDataProvider,
    ProductInfo,
    ProviderError,
    Ticker,
    timeframe_seconds,
    utc_from_ts,
)

logger = get_logger(__name__)

MAX_CANDLES_PER_REQUEST = 300


class CoinbaseProvider(MarketDataProvider):
    name = "coinbase"
    is_sample = False
    attribution = "Market data: Coinbase Exchange public API"

    def __init__(self, base_url: str = "https://api.exchange.coinbase.com", timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": "trading-intelligence-platform/1.0", "Accept": "application/json"},
        )
        # Public endpoints allow ~10 req/s; stay well under it.
        self._semaphore = asyncio.Semaphore(4)

    async def _get(self, path: str, params: dict | None = None) -> object:
        async with self._semaphore:
            for attempt in range(3):
                try:
                    resp = await self._client.get(path, params=params)
                    if resp.status_code == 429:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    if resp.status_code == 404:
                        raise ProviderError(f"Unknown product for path {path}")
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPError as exc:
                    if attempt == 2:
                        raise ProviderError(f"Coinbase request failed: {exc}") from exc
                    await asyncio.sleep(0.3 * (attempt + 1))
            raise ProviderError("Coinbase rate limit exceeded")

    async def get_candles(
        self, provider_symbol: str, timeframe: str, limit: int = 300, end: datetime | None = None
    ) -> list[Candle]:
        granularity = timeframe_seconds(timeframe)
        end = end or datetime.now(UTC)
        remaining = max(1, limit)
        by_ts: dict[datetime, Candle] = {}
        window_end = end
        # Page backwards in windows of at most 300 candles.
        for _ in range((remaining // MAX_CANDLES_PER_REQUEST) + 2):
            if remaining <= 0:
                break
            batch = min(remaining, MAX_CANDLES_PER_REQUEST)
            window_start = window_end - timedelta(seconds=granularity * batch)
            raw = await self._get(
                f"/products/{provider_symbol}/candles",
                params={
                    "granularity": granularity,
                    "start": window_start.isoformat(),
                    "end": window_end.isoformat(),
                },
            )
            if not isinstance(raw, list) or not raw:
                break
            # Row format: [time, low, high, open, close, volume]
            for row in raw:
                ts = utc_from_ts(row[0])
                by_ts[ts] = Candle(
                    ts=ts,
                    low=float(row[1]),
                    high=float(row[2]),
                    open=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]),
                )
            remaining = limit - len(by_ts)
            window_end = window_start
        candles = sorted(by_ts.values(), key=lambda c: c.ts)
        return candles[-limit:]

    async def get_ticker(self, provider_symbol: str) -> Ticker:
        raw = await self._get(f"/products/{provider_symbol}/stats")
        if not isinstance(raw, dict) or "last" not in raw:
            raise ProviderError(f"Unexpected stats payload for {provider_symbol}")
        return Ticker(
            symbol=provider_symbol,
            price=float(raw["last"]),
            open_24h=float(raw.get("open") or 0),
            high_24h=float(raw.get("high") or 0),
            low_24h=float(raw.get("low") or 0),
            volume_24h=float(raw.get("volume") or 0),
            ts=datetime.now(UTC),
        )

    async def list_products(self) -> list[ProductInfo]:
        raw = await self._get("/products")
        products: list[ProductInfo] = []
        if isinstance(raw, list):
            for p in raw:
                if p.get("status") != "online" or p.get("trading_disabled"):
                    continue
                products.append(
                    ProductInfo(
                        provider_symbol=p["id"],
                        base_currency=p["base_currency"],
                        quote_currency=p["quote_currency"],
                        name=p.get("display_name") or p["id"],
                    )
                )
        return products

    async def close(self) -> None:
        await self._client.aclose()
