"""Live prices from Coinbase Exchange's public WebSocket feed.

One shared connection subscribes to the `ticker` channel for every tracked Coinbase
product (public data, no API key). Each update:

  * refreshes the ticker cache that REST endpoints and paper-trading fills read, so
    the whole app sees the same price; the cache entry expires quickly, so if the
    feed stops, everything falls back to REST polling on its own;
  * is handed to the WebSocket broadcaster, which forwards it to browsers (throttled).

The connection reconnects with exponential backoff and re-syncs its subscriptions
when assets are tracked or untracked.
"""

import asyncio
import contextlib
import json
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.cache import get_cache
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.market_data.providers.base import Ticker
from app.models.enums import AssetClass
from app.models.market import Asset

logger = get_logger(__name__)

PROVIDER = "coinbase"
CACHE_TTL_SECONDS = 15  # long enough to bridge quiet markets, short enough to fall back quickly
RESYNC_SECONDS = 60  # how often tracked assets are re-read
HEALTHY_WITHIN_SECONDS = 30
MAX_BACKOFF_SECONDS = 60


def parse_ticker(msg: object) -> Ticker | None:
    """A Ticker from a Coinbase `ticker` message, or None for anything else or malformed data."""
    if not isinstance(msg, dict) or msg.get("type") != "ticker":
        return None
    try:
        price = float(msg["price"])
        ts = datetime.fromisoformat(str(msg.get("time", "")).replace("Z", "+00:00")) if msg.get("time") else datetime.now(UTC)
        return Ticker(
            symbol=str(msg["product_id"]),
            price=price,
            open_24h=float(msg.get("open_24h") or price),
            high_24h=float(msg.get("high_24h") or price),
            low_24h=float(msg.get("low_24h") or price),
            volume_24h=float(msg.get("volume_24h") or 0.0),
            ts=ts if ts.tzinfo else ts.replace(tzinfo=UTC),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def tracked_products() -> dict[str, str]:
    """Coinbase product id -> app symbol for every active tracked crypto asset."""
    async with get_sessionmaker()() as session:
        rows = (
            await session.scalars(select(Asset).where(Asset.is_active.is_(True), Asset.asset_class == AssetClass.CRYPTO))
        ).all()
        return {a.provider_symbol: a.symbol for a in rows}


class CoinbaseTickerStream:
    def __init__(
        self,
        url: str,
        on_ticker: Callable[[str, Ticker], Awaitable[None]],
        products: Callable[[], Awaitable[dict[str, str]]] = tracked_products,
        initial_backoff: float = 1.0,
    ) -> None:
        self.url = url
        self.initial_backoff = initial_backoff
        self.on_ticker = on_ticker
        self.products = products
        self.connected = False
        self.last_message_at: float | None = None
        self.messages = 0
        self.reconnects = 0
        self._task: asyncio.Task | None = None

    # ---------------------------------------------------------------- status
    @property
    def healthy(self) -> bool:
        return self.connected and self.last_message_at is not None and time.monotonic() - self.last_message_at < HEALTHY_WITHIN_SECONDS

    def status(self) -> dict:
        age = None if self.last_message_at is None else round(time.monotonic() - self.last_message_at, 1)
        return {"enabled": True, "connected": self.connected, "healthy": self.healthy, "last_message_age_s": age,
                "messages": self.messages, "reconnects": self.reconnects}  # fmt: skip

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="coinbase-ticker-stream")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.connected = False

    async def _run(self) -> None:
        backoff = self.initial_backoff
        while True:
            try:
                await self._session()
                backoff = self.initial_backoff  # a clean session resets the backoff
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - network errors are expected; keep retrying
                logger.warning("market_stream_disconnected", error=f"{type(exc).__name__}: {exc}", retry_in_s=round(backoff, 1))
            self.connected = False
            self.reconnects += 1
            await asyncio.sleep(backoff * (0.8 + 0.4 * random.random()))  # jitter avoids reconnect storms
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def _session(self) -> None:
        from websockets.asyncio.client import connect

        products = await self.products()
        if not products:
            await asyncio.sleep(RESYNC_SECONDS)
            return
        async with connect(self.url, open_timeout=15, ping_interval=20, max_size=2**20) as ws:
            await ws.send(json.dumps({"type": "subscribe", "product_ids": sorted(products), "channels": ["ticker"]}))
            self.connected = True
            logger.info("market_stream_connected", products=len(products))
            next_resync = time.monotonic() + RESYNC_SECONDS
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, next_resync - time.monotonic()))
                except TimeoutError:
                    raw = None
                if time.monotonic() >= next_resync:
                    products = await self._resync(ws, products)
                    next_resync = time.monotonic() + RESYNC_SECONDS
                if raw is None:
                    continue
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(msg, dict) and msg.get("type") == "error":
                    raise ConnectionError(f"Coinbase stream error: {msg.get('message')} {msg.get('reason', '')}".strip())
                ticker = parse_ticker(msg)
                if ticker is None or ticker.symbol not in products:
                    continue
                self.messages += 1
                self.last_message_at = time.monotonic()
                symbol = products[ticker.symbol]
                await get_cache().set_json(f"ticker:{PROVIDER}:{ticker.symbol}", ticker.to_dict(), ttl=CACHE_TTL_SECONDS)
                await self.on_ticker(symbol, ticker)

    async def _resync(self, ws, current: dict[str, str]) -> dict[str, str]:  # type: ignore[no-untyped-def]
        latest = await self.products()
        added, removed = sorted(set(latest) - set(current)), sorted(set(current) - set(latest))
        if added:
            await ws.send(json.dumps({"type": "subscribe", "product_ids": added, "channels": ["ticker"]}))
        if removed:
            await ws.send(json.dumps({"type": "unsubscribe", "product_ids": removed, "channels": ["ticker"]}))
        if added or removed:
            logger.info("market_stream_resubscribed", added=added, removed=removed)
        return latest
