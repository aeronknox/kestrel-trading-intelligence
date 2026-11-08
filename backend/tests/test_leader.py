"""Background-job leadership: one runner across instances, failover, and the worker entrypoint."""

import asyncio
import os

import pytest

from app.core.cache import MemoryCache
from app.services import background
from app.services.background import BackgroundJobs


async def test_memory_lease_semantics() -> None:
    cache = MemoryCache()
    assert await cache.acquire_lease("k", "a", ttl=0.2)
    assert not await cache.acquire_lease("k", "b", ttl=0.2)  # held by a
    assert await cache.acquire_lease("k", "a", ttl=0.2)  # a renews
    await cache.release_lease("k", "b")  # only the holder can release
    assert not await cache.acquire_lease("k", "b", ttl=0.2)
    await cache.release_lease("k", "a")
    assert await cache.acquire_lease("k", "b", ttl=0.05)
    await asyncio.sleep(0.08)  # b stops renewing: the lease expires
    assert await cache.acquire_lease("k", "a", ttl=0.2)


async def test_only_the_leader_runs_jobs_and_a_follower_takes_over(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cache = MemoryCache()
    monkeypatch.setattr(background, "get_cache", lambda: cache)
    monkeypatch.setattr(background, "LEASE_TTL_SECONDS", 0.3)
    monkeypatch.setattr(background, "LEASE_RENEW_SECONDS", 0.05)
    runs = {"a": 0, "b": 0}

    def job(name: str):  # type: ignore[no-untyped-def]
        async def fn() -> None:
            runs[name] += 1

        return fn

    a, b = BackgroundJobs(), BackgroundJobs()
    tasks = {
        "a": [asyncio.create_task(a._lead()), asyncio.create_task(a._loop(job("a"), 0.02))],
        "b": [asyncio.create_task(b._lead()), asyncio.create_task(b._loop(job("b"), 0.02))],
    }
    await asyncio.sleep(0.3)
    assert a.is_leader != b.is_leader  # exactly one leader
    leader, follower = ("a", "b") if a.is_leader else ("b", "a")
    assert runs[leader] > 0 and runs[follower] == 0

    # The leader shuts down cleanly and releases the lease: the follower takes over quickly.
    jobs_by_name = {"a": a, "b": b}
    for t in tasks[leader]:
        t.cancel()
    await asyncio.gather(*tasks[leader], return_exceptions=True)
    jobs_by_name[leader]._tasks = tasks[leader]
    await jobs_by_name[leader].stop()
    before = runs[follower]
    await asyncio.sleep(0.25)
    assert jobs_by_name[follower].is_leader and runs[follower] > before
    for t in tasks[follower]:
        t.cancel()
    await asyncio.gather(*tasks[follower], return_exceptions=True)


async def test_lease_errors_make_an_instance_stand_down(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class Broken(MemoryCache):
        async def acquire_lease(self, key, owner, ttl):  # type: ignore[no-untyped-def]
            raise ConnectionError("redis unreachable")

    monkeypatch.setattr(background, "get_cache", lambda: Broken())
    monkeypatch.setattr(background, "LEASE_RENEW_SECONDS", 0.05)
    j = BackgroundJobs()
    j.is_leader = True
    task = asyncio.create_task(j._lead())
    await asyncio.sleep(0.1)
    assert j.is_leader is False  # never run jobs without a confirmed lease
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="set TEST_REDIS_URL to test the Redis lease (CI does)")
async def test_redis_lease_semantics() -> None:
    import redis.asyncio as redis

    from app.core.cache import RedisCache

    client = redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    cache = RedisCache(client)
    key = "test:lease"
    await client.delete(key)
    try:
        assert await cache.acquire_lease(key, "a", ttl=0.5)
        assert not await cache.acquire_lease(key, "b", ttl=0.5)
        assert await cache.acquire_lease(key, "a", ttl=0.5)
        await cache.release_lease(key, "b")
        assert not await cache.acquire_lease(key, "b", ttl=0.5)
        await cache.release_lease(key, "a")
        assert await cache.acquire_lease(key, "b", ttl=0.1)
        await asyncio.sleep(0.2)
        assert await cache.acquire_lease(key, "a", ttl=0.5)
    finally:
        await client.delete(key)
        await cache.close()


async def test_worker_starts_and_stops_cleanly(app) -> None:  # type: ignore[no-untyped-def]
    from app import worker
    from app.services.background import jobs

    stop = asyncio.Event()

    async def stop_soon() -> None:
        await asyncio.sleep(0.3)
        assert jobs.status()["running"] is True
        stop.set()

    await asyncio.gather(worker.run(stop), stop_soon())
    assert jobs.status()["running"] is False and jobs.is_leader is False
