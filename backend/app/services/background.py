"""Background jobs: limit-order matching and periodic equity snapshots."""

import asyncio
import contextlib

from sqlalchemy import select

from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.models.enums import OrderStatus
from app.models.paper import PaperPortfolio, SimulatedOrder
from app.paper_trading.service import PaperTradingService

logger = get_logger(__name__)

ORDER_INTERVAL_SECONDS = 15
SNAPSHOT_INTERVAL_SECONDS = 300


async def process_all_open_orders() -> int:
    fills = 0
    async with get_sessionmaker()() as session:
        portfolio_ids = (
            await session.scalars(
                select(SimulatedOrder.portfolio_id).where(SimulatedOrder.status == OrderStatus.OPEN).distinct()
            )
        ).all()
        for pid in portfolio_ids:
            pf = await session.scalar(select(PaperPortfolio).where(PaperPortfolio.id == pid).with_for_update())
            if pf is None:
                continue
            try:
                fills += await PaperTradingService(session).process_open_orders(pf)
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("order_processing_failed", portfolio_id=pid, error=str(exc))
    return fills


async def snapshot_all_portfolios() -> None:
    async with get_sessionmaker()() as session:
        portfolios = (await session.scalars(select(PaperPortfolio).where(PaperPortfolio.is_active.is_(True)))).all()
        for pf in portfolios:
            if not pf.positions:
                continue  # cash-only equity doesn't change
            try:
                await PaperTradingService(session).record_snapshot(pf)
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.warning("snapshot_failed", portfolio_id=pf.id, error=str(exc))


class BackgroundJobs:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop(process_all_open_orders, ORDER_INTERVAL_SECONDS), name="paper-orders"),
            asyncio.create_task(self._loop(snapshot_all_portfolios, SNAPSHOT_INTERVAL_SECONDS), name="paper-snapshots"),
        ]

    @staticmethod
    async def _loop(fn, interval: int) -> None:  # type: ignore[no-untyped-def]
        while True:
            await asyncio.sleep(interval)
            try:
                await fn()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("background_job_failed", job=fn.__name__, error=str(exc))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks = []


jobs = BackgroundJobs()
