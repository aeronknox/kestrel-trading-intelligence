"""Long history: stored candles, gap filling, listing floor, budgets and the backfill job."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.database.session import get_sessionmaker
from app.market_data.providers.base import Candle, MarketDataProvider, ProductInfo, ProviderError
from app.market_data.service import MarketDataService
from app.models.market import Asset, MarketData

H = 3600


class ScriptedExchange(MarketDataProvider):
    """Hourly candles from `listed_hours_ago` until now, optionally with an outage hole.

    Like Coinbase, a request returns candles in [end - limit, end] (both ends inclusive).
    """

    name = "scripted"
    is_sample = False
    attribution = "scripted"

    def __init__(self, listed_hours_ago: int, hole: tuple[int, int] | None = None) -> None:
        now_k = int(datetime.now(UTC).timestamp() // H)
        self.first_k = now_k - listed_hours_ago
        self.hole = (now_k - hole[0], now_k - hole[1]) if hole else None  # hours ago -> indices
        self.calls: list[int] = []
        self.fail = False

    def _exists(self, k: int) -> bool:
        now_k = int(datetime.now(UTC).timestamp() // H)
        in_hole = self.hole is not None and self.hole[0] <= k <= self.hole[1]
        return self.first_k <= k <= now_k and not in_hole

    async def get_candles(self, provider_symbol, timeframe, limit=300, end=None):  # type: ignore[no-untyped-def]
        if self.fail:
            raise ProviderError("down")
        self.calls.append(limit)
        end_k = int((end or datetime.now(UTC)).timestamp() // H)
        return [
            Candle(ts=datetime.fromtimestamp(k * H, tz=UTC), open=100 + k % 7, high=102 + k % 7, low=99 + k % 7, close=101 + k % 7, volume=5)
            for k in range(end_k - limit, end_k + 1)
            if self._exists(k)
        ]

    async def get_ticker(self, provider_symbol):  # type: ignore[no-untyped-def]
        raise ProviderError("not needed")

    async def list_products(self) -> list[ProductInfo]:
        return []


async def _stored(session, asset) -> int:  # type: ignore[no-untyped-def]
    return await session.scalar(
        select(func.count()).select_from(MarketData).where(MarketData.asset_id == asset.id, MarketData.timeframe == "1h")
    )


async def _btc(session):  # type: ignore[no-untyped-def]
    return await session.scalar(select(Asset).where(Asset.symbol == "BTC-USD"))


def _contiguous(candles: list[Candle]) -> bool:
    ks = [int(c.ts.timestamp()) // H for c in candles]
    return ks == list(range(ks[0], ks[0] + len(ks)))


async def test_history_is_fetched_once_then_served_from_storage(app) -> None:  # type: ignore[no-untyped-def]
    ex = ScriptedExchange(listed_hours_ago=10_000)
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        series = await svc.get_history(await _btc(s), "1h", 5000)
        await s.commit()
        assert len(series.candles) == 5000 and _contiguous(series.candles) and series.complete
        now_k = int(datetime.now(UTC).timestamp() // H)
        assert int(series.candles[-1].ts.timestamp()) // H == now_k - 1  # newest *closed* candle; the forming one is excluded
        assert await _stored(s, await _btc(s)) == 5000
        first_calls = len(ex.calls)

        again = await svc.get_history(await _btc(s), "1h", 5000)
        assert len(ex.calls) == first_calls  # nothing missing -> no provider traffic
        assert [c.close for c in again.candles] == [c.close for c in series.candles]


async def test_history_stops_at_listing_date_and_remembers_it(app) -> None:  # type: ignore[no-untyped-def]
    ex = ScriptedExchange(listed_hours_ago=1200)
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        series = await svc.get_history(await _btc(s), "1h", 5000)
        await s.commit()
        assert len(series.candles) == 1200 and series.complete  # all that exists
        calls = len(ex.calls)
        await svc.get_history(await _btc(s), "1h", 5000)
        assert len(ex.calls) == calls  # the pre-listing range is not re-requested


async def test_exchange_outage_gap_is_remembered_not_refetched(app) -> None:  # type: ignore[no-untyped-def]
    ex = ScriptedExchange(listed_hours_ago=3000, hole=(900, 800))  # 101 missing hours
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        series = await svc.get_history(await _btc(s), "1h", 2500)
        await s.commit()
        assert len(series.candles) == 2500 - 101
        calls = len(ex.calls)
        await svc.get_history(await _btc(s), "1h", 2500)
        assert len(ex.calls) == calls


async def test_fetch_budget_makes_partial_progress_and_resumes(app) -> None:  # type: ignore[no-untyped-def]
    ex = ScriptedExchange(listed_hours_ago=10_000)
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        first = await svc.get_history(await _btc(s), "1h", 6000, fetch_budget=2000)
        await s.commit()
        assert not first.complete and first.fetched_bars == 2000
        assert len(first.candles) == 2000 and _contiguous(first.candles)  # newest bars first
        rest = await svc.get_history(await _btc(s), "1h", 6000)
        await s.commit()
        assert rest.complete and len(rest.candles) == 6000 and _contiguous(rest.candles)
        assert rest.fetched_bars == 4000  # only the missing part was requested


async def test_provider_failure_serves_stored_history_as_stale(app) -> None:  # type: ignore[no-untyped-def]
    ex = ScriptedExchange(listed_hours_ago=10_000)
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        await svc.get_history(await _btc(s), "1h", 1000)
        await s.commit()
        ex.fail = True
        # The newest hour may have closed since; either way stored bars are still served.
        series = await svc.get_history(await _btc(s), "1h", 3000)
        assert series.stale or not series.complete
        assert len(series.candles) >= 999


async def test_backfill_job_spreads_downloads_over_ticks(app) -> None:  # type: ignore[no-untyped-def]
    from app.market_data.providers.registry import register_provider
    from app.services.background import backfill_history

    ex = ScriptedExchange(listed_hours_ago=500)
    ex.name = "sample"  # stand in for the configured provider, but report real (non-sample) data
    register_provider(ex)
    pending = await backfill_history(budget=1500)
    async with get_sessionmaker()() as s:
        btc = await _btc(s)
        assert await _stored(s, btc) == 500  # the first asset got its full 1h history
    assert pending > 0  # other assets/timeframes are left for later ticks
    assert sum(ex.calls) <= 1500 + 300  # budget respected (one chunk of slack)


async def test_history_api_and_long_backtest(auth_client) -> None:  # type: ignore[no-untyped-def]
    cov = (await auth_client.get("/api/v1/market/assets/BTC-USD/history", params={"timeframe": "1h"})).json()
    assert cov["is_sample"] is True and cov["max_bars"] == 20_000
    assert (await auth_client.get("/api/v1/market/assets/BTC-USD/history", params={"timeframe": "7m"})).status_code == 422

    from app.strategies.definition import TEMPLATES

    d = TEMPLATES[0]["definition"]
    sid = (await auth_client.post("/api/v1/strategies", json={"name": "Long", "config": {"symbol": "BTC-USD", "timeframe": "1h", **d}})).json()["id"]
    bt = (await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 8000})).json()
    assert bt["status"] == "completed", bt["error"]
    assert bt["metrics"]["bars"] == 8000 and bt["metrics"]["bars_requested"] == 8000
    assert (await auth_client.post("/api/v1/backtests", json={"strategy_id": sid, "bars": 20_001})).status_code == 422


async def test_research_compute_budget_is_enforced(auth_client) -> None:  # type: ignore[no-untyped-def]
    from app.strategies.definition import TEMPLATES

    d = TEMPLATES[0]["definition"]
    sid = (await auth_client.post("/api/v1/strategies", json={"name": "Big", "config": {"symbol": "BTC-USD", "timeframe": "1h", **d}})).json()["id"]
    grid = [{"path": "entry.conditions.0.right.value", "values": list(range(20, 30))},
            {"path": "risk.stop_loss_pct", "values": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]}]  # fmt: skip
    # 2 folds x 100 combinations x 15,000 tuning bars = 3,000,000 simulated bars.
    resp = await auth_client.post(
        "/api/v1/research/walk-forward",
        json={"strategy_id": sid, "bars": 20_000, "params": grid, "folds": 2, "is_ratio": 6},
    )
    assert resp.status_code == 422
    assert "limit 2,000,000" in resp.json()["error"]["message"]


@pytest.mark.parametrize("bars", [200, 20_000])
async def test_sample_history_is_generated_not_stored(app, bars) -> None:  # type: ignore[no-untyped-def]
    async with get_sessionmaker()() as s:
        series = await MarketDataService(s).get_history(await _btc(s), "1h", bars)
        assert len(series.candles) == bars and series.is_sample and _contiguous(series.candles)
        assert await _stored(s, await _btc(s)) == 0


async def test_one_empty_response_does_not_hide_history_for_a_day(app) -> None:  # type: ignore[no-untyped-def]
    """A transient empty reply for the newest range must not be mistaken for the listing date."""
    ex = ScriptedExchange(listed_hours_ago=5000)
    real = ex.get_candles
    glitches = 1

    async def flaky(provider_symbol, timeframe, limit=300, end=None):  # type: ignore[no-untyped-def]
        nonlocal glitches
        if glitches:
            glitches -= 1
            return []  # e.g. an upstream hiccup answering 200 with no rows
        return await real(provider_symbol, timeframe, limit, end)

    ex.get_candles = flaky  # type: ignore[method-assign]
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        from app.core.exceptions import UpstreamError

        with pytest.raises(UpstreamError):  # nothing stored and nothing fetched yet: an honest error
            await svc.get_history(await _btc(s), "1h", 2000)
    async with get_sessionmaker()() as s:
        svc = MarketDataService(s, ex)
        again = await svc.get_history(await _btc(s), "1h", 2000)
        await s.commit()
        assert len(again.candles) == 2000 and again.complete  # recovered on the next call
