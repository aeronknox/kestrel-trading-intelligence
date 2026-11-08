"""Coinbase live ticker stream against a local fake feed, and broadcaster batching."""

import asyncio
import json

import pytest
from websockets.asyncio.server import serve

from app.core.cache import get_cache
from app.market_data import stream as stream_mod
from app.market_data.stream import CoinbaseTickerStream, parse_ticker

TICK = {
    "type": "ticker", "product_id": "BTC-USD", "price": "75000.50", "open_24h": "74000", "high_24h": "76000",
    "low_24h": "73000", "volume_24h": "1234.5", "time": "2026-11-07T12:00:00.123456Z",
}  # fmt: skip


def test_parse_ticker() -> None:
    t = parse_ticker(TICK)
    assert t is not None and t.symbol == "BTC-USD" and t.price == 75000.5 and t.open_24h == 74000
    assert t.ts.tzinfo is not None and t.ts.year == 2026
    assert parse_ticker({**TICK, "price": "not-a-number"}) is None
    assert parse_ticker({"type": "subscriptions", "channels": []}) is None
    assert parse_ticker("garbage") is None
    sparse = parse_ticker({"type": "ticker", "product_id": "ETH-USD", "price": "3000"})
    assert sparse is not None and sparse.high_24h == 3000 and sparse.volume_24h == 0


class FakeFeed:
    """A minimal stand-in for ws-feed.exchange.coinbase.com."""

    def __init__(self, script):  # type: ignore[no-untyped-def]
        self.script = script  # async fn(ws, connection_number)
        self.received: list[dict] = []
        self.connections = 0

    async def handler(self, ws):  # type: ignore[no-untyped-def]
        self.connections += 1
        n = self.connections

        async def reader() -> None:
            async for raw in ws:
                self.received.append(json.loads(raw))

        task = asyncio.create_task(reader())
        try:
            await self.script(ws, n)
        finally:
            task.cancel()


async def run_with(feed: FakeFeed, products, until, limit_s: float = 5.0):  # type: ignore[no-untyped-def]
    got: list[tuple[str, float]] = []

    async def on_ticker(symbol, ticker):  # type: ignore[no-untyped-def]
        got.append((symbol, ticker.price))

    async with serve(feed.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        s = CoinbaseTickerStream(f"ws://127.0.0.1:{port}", on_ticker, products=products, initial_backoff=0.05)
        s.start()
        try:
            async with asyncio.timeout(limit_s):
                while not until(s, got):  # noqa: ASYNC110 - state is written by the stream and the fake feed
                    await asyncio.sleep(0.02)
        finally:
            await s.stop()
    return s, got


async def test_stream_subscribes_forwards_tickers_and_refreshes_the_cache(app) -> None:  # type: ignore[no-untyped-def]
    async def script(ws, n):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        await ws.send(json.dumps({"type": "subscriptions", "channels": [{"name": "ticker"}]}))
        await ws.send("not json")
        await ws.send(json.dumps({**TICK, "product_id": "DOGE-EUR"}))  # not tracked: ignored
        await ws.send(json.dumps(TICK))
        await ws.wait_closed()

    async def products():  # type: ignore[no-untyped-def]
        return {"BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"}

    feed = FakeFeed(script)
    s, got = await run_with(feed, products, lambda s, got: len(got) >= 1)
    assert got == [("BTC-USD", 75000.5)]
    assert feed.received[0] == {"type": "subscribe", "product_ids": ["BTC-USD", "ETH-USD"], "channels": ["ticker"]}
    cached = await get_cache().get_json("ticker:coinbase:BTC-USD")
    assert cached["price"] == 75000.5  # REST endpoints and paper fills now see the streamed price
    assert s.messages == 1


async def test_stream_reconnects_after_disconnects_and_errors(app) -> None:  # type: ignore[no-untyped-def]
    async def script(ws, n):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        if n == 1:
            await ws.close()  # dropped connection
        elif n == 2:
            await ws.send(json.dumps({"type": "error", "message": "Failed to subscribe", "reason": "test"}))
            await asyncio.sleep(1)
        else:
            await ws.send(json.dumps({**TICK, "price": "75100"}))
            await ws.wait_closed()

    async def products():  # type: ignore[no-untyped-def]
        return {"BTC-USD": "BTC-USD"}

    feed = FakeFeed(script)
    s, got = await run_with(feed, products, lambda s, got: len(got) >= 1)
    assert got == [("BTC-USD", 75100.0)]
    assert feed.connections == 3 and s.reconnects >= 2


async def test_stream_resubscribes_when_tracked_assets_change(app, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(stream_mod, "RESYNC_SECONDS", 0.2)
    calls = 0

    async def products():  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return {"BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"} if calls == 1 else {"BTC-USD": "BTC-USD", "SOL-USD": "SOL-USD"}

    async def script(ws, n):  # type: ignore[no-untyped-def]
        await ws.wait_closed()

    feed = FakeFeed(script)
    await run_with(feed, products, lambda s, got: len(feed.received) >= 3)
    assert feed.received[1] == {"type": "subscribe", "product_ids": ["SOL-USD"], "channels": ["ticker"]}
    assert feed.received[2] == {"type": "unsubscribe", "product_ids": ["ETH-USD"], "channels": ["ticker"]}


def test_unreachable_feed_is_not_healthy() -> None:
    s = CoinbaseTickerStream("ws://127.0.0.1:9", lambda *a: asyncio.sleep(0))  # type: ignore[arg-type,return-value]
    assert s.healthy is False and s.status()["connected"] is False


@pytest.mark.parametrize("subscribed", [["BTC-USD"], []])
def test_broadcaster_batches_streamed_updates(subscribed) -> None:  # type: ignore[no-untyped-def]
    from starlette.testclient import TestClient

    from app.api.routes.ws import broadcaster
    from app.main import create_app
    from app.market_data.providers.base import Ticker
    from tests.test_websocket import ORIGIN

    t = parse_ticker(TICK)
    assert isinstance(t, Ticker)
    with TestClient(create_app(background=False)) as c, c.websocket_connect("/api/v1/ws/market", headers=ORIGIN) as ws:
        ws.send_json({"action": "subscribe", "symbols": subscribed})
        ws.send_json({"action": "ping"})
        assert ws.receive_json() == {"type": "pong"}

        async def burst() -> None:
            for price in (1.0, 2.0, 3.0):  # three updates for one symbol within a flush window
                await broadcaster.push("BTC-USD", Ticker("BTC-USD", price, 1, 3, 1, 10, t.ts))
            await broadcaster.push("ETH-USD", Ticker("ETH-USD", 3000, 3000, 3000, 3000, 1, t.ts))
            await broadcaster._flush()

        c.portal.call(burst)
        msg = ws.receive_json()
        by_symbol = {d["symbol"]: d["price"] for d in msg["data"]}
        assert by_symbol["BTC-USD"] == 3.0  # only the newest price is sent
        assert ("ETH-USD" in by_symbol) == (not subscribed)  # subscriptions are respected
        assert msg["meta"]["streaming"] is True
