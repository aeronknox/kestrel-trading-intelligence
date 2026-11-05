"""Cache abstraction: Redis when configured and reachable, in-process otherwise."""

import asyncio
import json
import time
from typing import Any, Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


class Cache(Protocol):
    backend: str

    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl: float) -> None: ...
    async def incr_window(self, key: str, window_seconds: int) -> int: ...
    async def delete(self, key: str) -> None: ...
    async def close(self) -> None: ...


class MemoryCache:
    backend = "memory"

    def __init__(self, max_items: int = 5000) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self._max_items = max_items

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._data.items() if exp <= now]
        for k in expired:
            self._data.pop(k, None)
        if len(self._data) > self._max_items:
            for k in sorted(self._data, key=lambda k: self._data[k][0])[: len(self._data) - self._max_items]:
                self._data.pop(k, None)

    async def get_json(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        exp, value = item
        if exp <= time.monotonic():
            self._data.pop(key, None)
            return None
        return json.loads(value)

    async def set_json(self, key: str, value: Any, ttl: float) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic() + ttl, json.dumps(value, default=str))
            if len(self._data) > self._max_items:
                self._purge()

    async def incr_window(self, key: str, window_seconds: int) -> int:
        async with self._lock:
            now = time.monotonic()
            exp, value = self._data.get(key, (0.0, "0"))
            count = int(json.loads(value)) + 1 if exp > now else 1
            self._data[key] = (exp if exp > now else now + window_seconds, json.dumps(count))
            return count

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    backend = "redis"

    def __init__(self, client: Any) -> None:
        self._client = client

    async def get_json(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        return None if raw is None else json.loads(raw)

    async def set_json(self, key: str, value: Any, ttl: float) -> None:
        await self._client.set(key, json.dumps(value, default=str), px=max(1, int(ttl * 1000)))

    async def incr_window(self, key: str, window_seconds: int) -> int:
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, window_seconds, nx=True)
            count, _ = await pipe.execute()
        return int(count)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def close(self) -> None:
        await self._client.aclose()


_cache: Cache = MemoryCache()


async def init_cache(redis_url: str | None) -> Cache:
    global _cache
    if redis_url:
        try:
            import redis.asyncio as redis

            client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
            await client.ping()
            _cache = RedisCache(client)
            logger.info("cache_initialized", backend="redis")
            return _cache
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.warning("redis_unavailable_falling_back_to_memory", error=str(exc))
    _cache = MemoryCache()
    logger.info("cache_initialized", backend="memory")
    return _cache


def get_cache() -> Cache:
    return _cache


async def close_cache() -> None:
    await _cache.close()
