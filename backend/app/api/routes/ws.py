"""WebSocket market stream.

Clients connect to /api/v1/ws/market and may send:
    {"action": "subscribe", "symbols": ["BTC-USD", "ETH-USD"]}
They receive messages:
    {"type": "tickers", "data": [...], "meta": {...}}
With the Coinbase live feed connected, updates arrive as trades happen (batched every
FLUSH_SECONDS, newest price per symbol); otherwise prices are polled every
MARKET_WS_POLL_SECONDS. The stream carries public market data only (no user data).
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.market_data.providers.base import Ticker
from app.market_data.providers.registry import get_provider
from app.market_data.service import MarketDataService
from app.market_data.stream import CoinbaseTickerStream

router = APIRouter(tags=["websocket"])
logger = get_logger(__name__)

MAX_CLIENTS = 500
MAX_SYMBOLS_PER_CLIENT = 25
FLUSH_SECONDS = 0.5  # streamed updates are batched so busy markets can't flood browsers


class MarketBroadcaster:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, set[str]] = {}
        self._task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.pending: dict[str, dict] = {}  # symbol -> newest streamed ticker, sent on the next flush
        self.stream: CoinbaseTickerStream | None = None

    async def connect(self, ws: WebSocket) -> bool:
        if len(self.clients) >= MAX_CLIENTS:
            return False
        await ws.accept()
        async with self._lock:
            self.clients[ws] = set()
        return True

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.clients.pop(ws, None)

    def subscribe(self, ws: WebSocket, symbols: list[str]) -> None:
        if ws in self.clients:
            self.clients[ws] = {s.upper()[:32] for s in symbols[:MAX_SYMBOLS_PER_CLIENT]}

    def start(self) -> None:
        settings = get_settings()
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-broadcaster")
        if self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop(), name="market-flush")
        if self.stream is None and settings.market_stream_enabled and get_provider().name == "coinbase":
            self.stream = CoinbaseTickerStream(settings.coinbase_ws_url, self.push)
            self.stream.start()

    async def stop(self) -> None:
        if self.stream:
            await self.stream.stop()
            self.stream = None
        for task in (self._task, self._flush_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = self._flush_task = None

    async def push(self, symbol: str, ticker: Ticker) -> None:
        """Queue a streamed ticker; only the newest per symbol is kept until the next flush."""
        self.pending[symbol] = {**ticker.to_dict(), "symbol": symbol}

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            try:
                await self._flush()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("broadcast_flush_failed", error=str(exc))

    async def _flush(self) -> None:
        if not self.pending:
            return
        payload, self.pending = self.pending, {}
        provider = get_provider()
        meta = {"source": provider.name, "is_sample": provider.is_sample, "attribution": provider.attribution, "streaming": True}
        await self._send(payload, meta)

    async def _send(self, payload: dict[str, dict], meta: dict) -> None:
        for ws, subs in list(self.clients.items()):
            data = [v for k, v in payload.items() if not subs or k in subs]
            if not data:
                continue
            try:
                await ws.send_text(json.dumps({"type": "tickers", "data": data, "meta": meta}))
            except Exception:  # noqa: BLE001
                await self.disconnect(ws)

    async def _run(self) -> None:
        interval = get_settings().market_ws_poll_seconds
        while True:
            try:
                # Polling is the fallback: skip it while the live feed is delivering.
                if self.clients and not (self.stream and self.stream.healthy):
                    await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - never let the loop die
                logger.warning("broadcast_tick_failed", error=str(exc))
            await asyncio.sleep(interval)

    async def _tick(self) -> None:
        async with get_sessionmaker()() as session:
            market = MarketDataService(session)
            assets = await market.list_assets()
            subscriptions = list(self.clients.values())
            if subscriptions and all(subscriptions):  # every client has an explicit symbol list
                wanted = set().union(*subscriptions)
                selected = [a for a in assets if a.symbol in wanted]
            else:  # at least one client wants everything
                selected = assets
            tickers = await market.get_tickers(selected)
            await session.commit()
            meta = {"source": market.provider.name, "is_sample": market.provider.is_sample,
                    "attribution": market.provider.attribution, "streaming": False}  # fmt: skip
        await self._send({sym: t.to_dict() for sym, t in tickers.items() if t}, meta)


broadcaster = MarketBroadcaster()


@router.websocket("/ws/market")
async def market_ws(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if origin and origin not in get_settings().cors_origins:
        await ws.close(code=1008)
        return
    if not await broadcaster.connect(ws):
        await ws.close(code=1013)
        return
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("action") == "subscribe" and isinstance(msg.get("symbols"), list):
                broadcaster.subscribe(ws, [str(s) for s in msg["symbols"]])
            elif isinstance(msg, dict) and msg.get("action") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    finally:
        await broadcaster.disconnect(ws)
