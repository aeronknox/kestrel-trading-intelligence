"""Dedicated background-job worker.

    python -m app.worker

Runs order matching, equity snapshots, history backfill, strategy alerts and demo cleanup
outside the web server. Leadership is decided by a Redis lease, so it is safe to run this
alongside API instances; set RUN_BACKGROUND_JOBS=false on the API replicas to keep jobs
off the request path. Requires REDIS_URL when more than one process runs jobs.
"""

import asyncio
import contextlib
import signal

from app.core.cache import close_cache, get_cache, init_cache
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.database.session import dispose_engine, init_engine
from app.market_data.providers.registry import close_providers
from app.services.background import jobs

logger = get_logger(__name__)


async def run(stop: asyncio.Event | None = None) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    init_engine()
    await init_cache(settings.redis_url)
    if get_cache().backend != "redis":
        logger.warning("worker_without_redis", hint="Without REDIS_URL the lease is per process; run only one job runner")
    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # not available on Windows
            loop.add_signal_handler(sig, stop.set)
    jobs.start()
    logger.info("worker_started", instance=jobs.owner)
    try:
        await stop.wait()
    finally:
        await jobs.stop()
        await close_providers()
        await close_cache()
        await dispose_engine()
        logger.info("worker_stopped")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())
