"""WebSocket market stream.

Clients connect to /api/v1/ws/market and may send:
    {"action": "subscribe", "symbols": ["BTC-USD", "ETH-USD"]}
They receive periodic messages:
    {"type": "tickers", "data": [...], "meta": {...}}
The stream carries public market data only (no user data).
"""

import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.market_data.service import MarketDataService

router = APIRouter(tags=["websocket"])
logger = get_logger(__name__)

MAX_CLIENTS = 500
MAX_SYMBOLS_PER_CLIENT = 25


class MarketBroadcaster:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, set[str]] = {}
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

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
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-broadcaster")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        interval = get_settings().market_ws_poll_seconds
        while True:
            try:
                if self.clients:
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
            meta = {"source": market.provider.name, "is_sample": market.provider.is_sample, "attribution": market.provider.attribution}
        payload = {sym: t.to_dict() for sym, t in tickers.items() if t}
        for ws, subs in list(self.clients.items()):
            data = [v for k, v in payload.items() if not subs or k in subs]
            try:
                await ws.send_text(json.dumps({"type": "tickers", "data": data, "meta": meta}))
            except Exception:  # noqa: BLE001
                await self.disconnect(ws)


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
