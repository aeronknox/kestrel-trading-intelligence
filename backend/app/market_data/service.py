"""Market data service: provider access + caching + persistence.

Flow for candles:
  1. Serve from cache when fresh.
  2. Otherwise fetch from the provider, persist *closed* candles to `market_data`.
  3. If the provider fails, fall back to stored candles and flag the series `stale`.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.exceptions import NotFoundError, UpstreamError, ValidationFailedError
from app.core.logging import get_logger
from app.models.enums import AssetClass
from app.models.market import Asset, MarketData
from app.market_data.providers.base import (
    TIMEFRAMES,
    Candle,
    MarketDataProvider,
    ProviderError,
    Ticker,
    timeframe_seconds,
)
from app.market_data.providers.registry import get_provider

logger = get_logger(__name__)

MAX_CANDLES = 2000

DEFAULT_CRYPTO_ASSETS: list[tuple[str, str]] = [
    ("BTC", "Bitcoin"),
    ("ETH", "Ethereum"),
    ("SOL", "Solana"),
    ("XRP", "XRP"),
    ("ADA", "Cardano"),
    ("DOGE", "Dogecoin"),
    ("AVAX", "Avalanche"),
    ("LINK", "Chainlink"),
    ("LTC", "Litecoin"),
    ("DOT", "Polkadot"),
]


@dataclass
class CandleSeries:
    symbol: str
    timeframe: str
    candles: list[Candle]
    source: str
    is_sample: bool
    attribution: str
    stale: bool = False
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def closed(self) -> list[Candle]:
        """Only candles whose interval has fully elapsed — analysis never uses a forming bar."""
        cutoff = self.fetched_at - timedelta(seconds=timeframe_seconds(self.timeframe))
        return [c for c in self.candles if c.ts <= cutoff]

    def meta(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "source": self.source,
            "is_sample": self.is_sample,
            "attribution": self.attribution,
            "stale": self.stale,
            "fetched_at": self.fetched_at.isoformat(),
        }


def _candle_cache_ttl(timeframe: str) -> float:
    return min(max(timeframe_seconds(timeframe) / 12, 10.0), 120.0)


def _serialize(candles: list[Candle]) -> list[list]:
    return [[c.ts.timestamp(), c.open, c.high, c.low, c.close, c.volume] for c in candles]


def _deserialize(rows: list[list]) -> list[Candle]:
    return [
        Candle(ts=datetime.fromtimestamp(r[0], tz=UTC), open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
        for r in rows
    ]


class MarketDataService:
    def __init__(self, session: AsyncSession, provider: MarketDataProvider | None = None) -> None:
        self.session = session
        self.provider = provider or get_provider()
        self.cache = get_cache()

    def provider_for(self, asset: Asset) -> MarketDataProvider:
        """Crypto assets use the configured crypto provider (so switching
        MARKET_DATA_PROVIDER needs no data migration); other asset classes are routed
        to the provider recorded on the asset (e.g. a future stocks/forex provider)."""
        if asset.asset_class == AssetClass.CRYPTO:
            return self.provider
        return get_provider(asset.provider)

    # ----------------------------------------------------------------- assets
    async def ensure_default_assets(self) -> None:
        existing = set((await self.session.scalars(select(Asset.symbol))).all())
        for base, name in DEFAULT_CRYPTO_ASSETS:
            symbol = f"{base}-USD"
            if symbol not in existing:
                self.session.add(
                    Asset(
                        symbol=symbol,
                        name=name,
                        asset_class=AssetClass.CRYPTO,
                        base_currency=base,
                        quote_currency="USD",
                        provider=self.provider.name,
                        provider_symbol=symbol,
                    )
                )
        await self.session.flush()

    async def list_assets(self, query: str | None = None, asset_class: AssetClass | None = None) -> list[Asset]:
        stmt = select(Asset).where(Asset.is_active.is_(True))
        if query:
            like = f"%{query.strip().lower()}%"
            stmt = stmt.where(or_(func.lower(Asset.symbol).like(like), func.lower(Asset.name).like(like)))
        if asset_class:
            stmt = stmt.where(Asset.asset_class == asset_class)
        return list((await self.session.scalars(stmt.order_by(Asset.id))).all())

    async def get_asset(self, symbol: str) -> Asset:
        asset = await self.session.scalar(select(Asset).where(Asset.symbol == symbol.upper()))
        if asset is None or not asset.is_active:
            raise NotFoundError(f"Asset '{symbol}' is not tracked")
        return asset

    async def search_provider_catalog(self, query: str, limit: int = 20) -> list[dict]:
        key = f"catalog:{self.provider.name}"
        catalog = await self.cache.get_json(key)
        if catalog is None:
            try:
                products = await self.provider.list_products()
            except ProviderError as exc:
                raise UpstreamError("Could not load the provider's product catalog") from exc
            catalog = [
                {"symbol": p.provider_symbol, "base": p.base_currency, "quote": p.quote_currency, "name": p.name}
                for p in products
            ]
            await self.cache.set_json(key, catalog, ttl=3600)
        q = query.strip().upper()
        tracked = set((await self.session.scalars(select(Asset.symbol))).all())
        matches = [dict(p, tracked=p["symbol"] in tracked) for p in catalog if q in p["symbol"] or q in p["base"]]
        matches.sort(key=lambda p: (p["base"] != q, p["quote"] != "USD", p["symbol"]))
        return matches[:limit]

    async def track_asset(self, provider_symbol: str, name: str | None = None) -> Asset:
        symbol = provider_symbol.upper()
        existing = await self.session.scalar(select(Asset).where(Asset.symbol == symbol))
        if existing:
            existing.is_active = True
            return existing
        catalog = await self.search_provider_catalog(symbol, limit=200)
        product = next((p for p in catalog if p["symbol"] == symbol), None)
        if product is None:
            raise ValidationFailedError(f"'{symbol}' is not available from provider '{self.provider.name}'")
        asset = Asset(
            symbol=symbol,
            name=name or product["base"],
            asset_class=AssetClass.CRYPTO,
            base_currency=product["base"],
            quote_currency=product["quote"],
            provider=self.provider.name,
            provider_symbol=symbol,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    # ---------------------------------------------------------------- candles
    async def get_candles(
        self, asset: Asset, timeframe: str, limit: int = 300, *, use_cache: bool = True
    ) -> CandleSeries:
        if timeframe not in TIMEFRAMES:
            raise ValidationFailedError(f"Unsupported timeframe '{timeframe}'", details={"allowed": list(TIMEFRAMES)})
        limit = max(10, min(limit, MAX_CANDLES))
        provider = self.provider_for(asset)
        key = f"candles:{provider.name}:{asset.provider_symbol}:{timeframe}:{limit}"
        if use_cache:
            cached = await self.cache.get_json(key)
            if cached:
                return CandleSeries(
                    symbol=asset.symbol,
                    timeframe=timeframe,
                    candles=_deserialize(cached["candles"]),
                    source=provider.name,
                    is_sample=provider.is_sample,
                    attribution=provider.attribution,
                    fetched_at=datetime.fromisoformat(cached["fetched_at"]),
                )
        try:
            candles = await provider.get_candles(asset.provider_symbol, timeframe, limit=limit)
        except ProviderError as exc:
            logger.warning("provider_candles_failed", symbol=asset.symbol, timeframe=timeframe, error=str(exc))
            stored = await self._stored_candles(asset, timeframe, limit)
            if not stored:
                raise UpstreamError(f"Market data for {asset.symbol} is currently unavailable") from exc
            return CandleSeries(
                symbol=asset.symbol,
                timeframe=timeframe,
                candles=stored,
                source=provider.name,
                is_sample=provider.is_sample,
                attribution=provider.attribution,
                stale=True,
            )
        series = CandleSeries(
            symbol=asset.symbol,
            timeframe=timeframe,
            candles=candles,
            source=provider.name,
            is_sample=provider.is_sample,
            attribution=provider.attribution,
        )
        await self._persist(asset, timeframe, series.closed(), provider)
        await self.cache.set_json(
            key,
            {"candles": _serialize(candles), "fetched_at": series.fetched_at.isoformat()},
            ttl=_candle_cache_ttl(timeframe),
        )
        return series

    async def _stored_candles(self, asset: Asset, timeframe: str, limit: int) -> list[Candle]:
        rows = (
            await self.session.scalars(
                select(MarketData)
                .where(MarketData.asset_id == asset.id, MarketData.timeframe == timeframe)
                .order_by(MarketData.ts.desc())
                .limit(limit)
            )
        ).all()
        return [
            Candle(ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
            for r in reversed(rows)
        ]

    async def _persist(self, asset: Asset, timeframe: str, candles: list[Candle], provider: MarketDataProvider) -> None:
        if not candles or provider.is_sample:
            return  # never store synthetic data alongside real history
        dialect = self.session.bind.dialect.name if self.session.bind else "sqlite"
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        rows = [
            {
                "asset_id": asset.id,
                "timeframe": timeframe,
                "ts": c.ts,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "source": provider.name,
            }
            for c in candles
        ]
        # SAVEPOINT: on PostgreSQL a failed statement aborts the whole transaction, so the
        # best-effort insert must be isolated from the caller's unit of work.
        try:
            async with self.session.begin_nested():
                for i in range(0, len(rows), 500):
                    stmt = insert(MarketData).values(rows[i : i + 500])
                    await self.session.execute(
                        stmt.on_conflict_do_nothing(index_elements=["asset_id", "timeframe", "ts"])
                    )
        except Exception as exc:  # noqa: BLE001 - persistence is best-effort, never break reads
            logger.warning("candle_persist_failed", symbol=asset.symbol, error=str(exc))

    # ---------------------------------------------------------------- tickers
    async def get_ticker(self, asset: Asset) -> Ticker:
        provider = self.provider_for(asset)
        key = f"ticker:{provider.name}:{asset.provider_symbol}"
        cached = await self.cache.get_json(key)
        if cached:
            return Ticker(
                symbol=cached["symbol"],
                price=cached["price"],
                open_24h=cached["open_24h"],
                high_24h=cached["high_24h"],
                low_24h=cached["low_24h"],
                volume_24h=cached["volume_24h"],
                ts=datetime.fromisoformat(cached["ts"]),
            )
        try:
            ticker = await provider.get_ticker(asset.provider_symbol)
        except ProviderError as exc:
            raise UpstreamError(f"Live price for {asset.symbol} is currently unavailable") from exc
        await self.cache.set_json(key, ticker.to_dict(), ttl=4)
        return ticker

    async def get_tickers(self, assets: list[Asset]) -> dict[str, Ticker | None]:
        import asyncio

        async def one(a: Asset) -> tuple[str, Ticker | None]:
            try:
                return a.symbol, await self.get_ticker(a)
            except UpstreamError:
                return a.symbol, None

        results = await asyncio.gather(*(one(a) for a in assets))
        return dict(results)

    async def get_fear_greed(self) -> dict | None:
        """Crypto Fear & Greed Index from alternative.me (public source, attributed in UI)."""
        if self.provider.is_sample:
            return None
        cached = await self.cache.get_json("sentiment:fng")
        if cached is not None:
            return cached or None
        import httpx

        from app.core.config import get_settings

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(get_settings().sentiment_url, params={"limit": 7})
                resp.raise_for_status()
                data = resp.json().get("data", [])
            result = {
                "value": int(data[0]["value"]),
                "classification": data[0]["value_classification"],
                "history": [{"ts": int(d["timestamp"]), "value": int(d["value"])} for d in data],
                "source": "alternative.me Crypto Fear & Greed Index",
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("fear_greed_unavailable", error=str(exc))
            await self.cache.set_json("sentiment:fng", {}, ttl=300)
            return None
        await self.cache.set_json("sentiment:fng", result, ttl=1800)
        return result
