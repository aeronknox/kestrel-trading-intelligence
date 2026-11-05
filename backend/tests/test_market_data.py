"""Market data service: persistence, stale fallback, and Coinbase response parsing."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.database.session import get_sessionmaker
from app.market_data.providers.base import Candle, MarketDataProvider, ProductInfo, ProviderError, Ticker
from app.market_data.providers.coinbase import CoinbaseProvider
from app.market_data.service import MarketDataService
from app.models.market import Asset, MarketData


class FakeRealProvider(MarketDataProvider):
    """A non-sample provider with scripted responses (so persistence is exercised)."""

    name = "fakereal"
    is_sample = False
    attribution = "fake"

    def __init__(self) -> None:
        self.fail = False

    async def get_candles(self, provider_symbol, timeframe, limit=300, end=None):  # type: ignore[no-untyped-def]
        if self.fail:
            raise ProviderError("down")
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        return [
            Candle(ts=now - timedelta(hours=limit - 1 - i), open=100 + i, high=101 + i, low=99 + i, close=100.5 + i, volume=10)
            for i in range(limit)
        ]

    async def get_ticker(self, provider_symbol):  # type: ignore[no-untyped-def]
        raise ProviderError("down")

    async def list_products(self) -> list[ProductInfo]:
        return []


async def test_persists_closed_candles_and_falls_back_when_provider_fails(app) -> None:  # type: ignore[no-untyped-def]
    provider = FakeRealProvider()
    async with get_sessionmaker()() as s:
        asset = await s.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))
        svc = MarketDataService(s, provider)
        series = await svc.get_candles(asset, "1h", limit=50, use_cache=False)
        await s.commit()
        stored = await s.scalar(select(func.count()).select_from(MarketData))
        # The newest candle is still forming and must not be persisted.
        assert stored == 49
        assert len(series.closed()) == 49

        # Re-fetching the same range must not duplicate rows (upsert / on-conflict).
        await svc.get_candles(asset, "1h", limit=50, use_cache=False)
        await s.commit()
        assert await s.scalar(select(func.count()).select_from(MarketData)) == 49

        provider.fail = True
        fallback = await svc.get_candles(asset, "1h", limit=50, use_cache=False)
        assert fallback.stale is True
        assert len(fallback.candles) == 49
        assert fallback.candles[-1].close == series.closed()[-1].close


async def test_upstream_error_without_history_is_502(app, client) -> None:  # type: ignore[no-untyped-def]
    from app.market_data.providers.registry import register_provider
    from tests.conftest import register

    failing = FakeRealProvider()
    failing.name = "sample"  # replace the configured provider for this test
    failing.fail = True
    register_provider(failing)
    await register(client)
    resp = await client.get("/api/v1/market/assets/BTC-USD/candles", params={"timeframe": "1d"})
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"


def _coinbase(handler) -> CoinbaseProvider:  # type: ignore[no-untyped-def]
    p = CoinbaseProvider()
    p._client = httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler))
    return p


async def test_coinbase_candle_parsing_and_pagination() -> None:
    calls: list[dict] = []
    base = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp())

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        start = int(datetime.fromisoformat(request.url.params["start"]).timestamp())
        end = int(datetime.fromisoformat(request.url.params["end"]).timestamp())
        # Coinbase returns newest-first rows: [time, low, high, open, close, volume]
        rows = [[t, 1.0, 3.0, 2.0, 2.5, 7.0] for t in range(end - 3600, start - 1, -3600) if t >= base]
        return httpx.Response(200, json=rows)

    p = _coinbase(handler)
    candles = await p.get_candles("BTC-USD", "1h", limit=450, end=datetime.fromtimestamp(base + 450 * 3600, tz=UTC))
    assert len(calls) == 2  # 300 + 150
    assert len(candles) == 450
    assert candles == sorted(candles, key=lambda c: c.ts)
    c = candles[0]
    assert (c.open, c.high, c.low, c.close, c.volume) == (2.0, 3.0, 1.0, 2.5, 7.0)


async def test_coinbase_ticker_and_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "NOPE" in request.url.path:
            return httpx.Response(404, json={"message": "NotFound"})
        return httpx.Response(200, json={"open": "100", "high": "120", "low": "90", "last": "110", "volume": "5"})

    p = _coinbase(handler)
    t = await p.get_ticker("BTC-USD")
    assert isinstance(t, Ticker) and t.price == 110 and t.change_pct_24h == pytest.approx(10.0)
    with pytest.raises(ProviderError):
        await p.get_ticker("NOPE-USD")


async def test_non_crypto_assets_route_to_their_own_provider(app, auth_client) -> None:  # type: ignore[no-untyped-def]
    from app.market_data.providers.registry import register_provider
    from app.models.enums import AssetClass

    stocks = FakeRealProvider()
    stocks.name = "fakestocks"
    register_provider(stocks)
    async with get_sessionmaker()() as s:
        s.add(Asset(symbol="AAPL", name="Apple", asset_class=AssetClass.STOCK, base_currency="AAPL",
                    quote_currency="USD", provider="fakestocks", provider_symbol="AAPL"))  # fmt: skip
        await s.commit()
    resp = await auth_client.get("/api/v1/market/assets/AAPL/candles", params={"timeframe": "1h", "limit": 30})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["source"] == "fakestocks" and body["meta"]["is_sample"] is False
    assert body["candles"][0]["open"] >= 100  # FakeRealProvider's series, not the crypto sample provider
