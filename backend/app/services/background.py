"""Background jobs: limit-order matching, equity snapshots, history backfill and strategy alerts."""

import asyncio
import contextlib

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_sessionmaker
from app.market_data.service import HISTORY_MAX_BARS, MarketDataService
from app.models.enums import OrderStatus
from app.models.market import Asset
from app.models.paper import PaperPortfolio, SimulatedOrder
from app.paper_trading.service import PaperTradingService
from app.services.alerts import evaluate_alerts
from app.services.demo import purge_expired_demo_users

logger = get_logger(__name__)

ORDER_INTERVAL_SECONDS = 15
SNAPSHOT_INTERVAL_SECONDS = 300
BACKFILL_INTERVAL_SECONDS = 60
ALERT_INTERVAL_SECONDS = 60
DEMO_PURGE_INTERVAL_SECONDS = 900
BACKFILL_TIMEFRAMES = ("1h", "6h", "1d")


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


async def backfill_history(budget: int | None = None) -> int:
    """Download up to `budget` missing bars across tracked assets; returns bars still missing after this tick.

    Rate-limited by the budget, so a full backfill spreads over hours instead of bursting the provider.
    """
    budget = get_settings().history_backfill_bars_per_minute if budget is None else budget
    async with get_sessionmaker()() as session:
        svc = MarketDataService(session)
        if svc.provider.is_sample:
            return 0
        assets = (await session.scalars(select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.id))).all()
        pending = 0
        for asset in assets:
            for tf in BACKFILL_TIMEFRAMES:
                if budget <= 0:
                    pending += 1
                    continue
                try:
                    series = await svc.get_history(asset, tf, HISTORY_MAX_BARS, fetch_budget=budget)
                    await session.commit()
                except Exception as exc:  # noqa: BLE001 - one asset failing must not stop the rest
                    await session.rollback()
                    logger.warning("history_backfill_failed", symbol=asset.symbol, timeframe=tf, error=str(exc))
                    continue
                budget -= series.fetched_bars
                pending += not series.complete
        return pending


class BackgroundJobs:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop(process_all_open_orders, ORDER_INTERVAL_SECONDS), name="paper-orders"),
            asyncio.create_task(self._loop(snapshot_all_portfolios, SNAPSHOT_INTERVAL_SECONDS), name="paper-snapshots"),
            asyncio.create_task(self._loop(evaluate_alerts, ALERT_INTERVAL_SECONDS), name="strategy-alerts"),
        ]
        if get_settings().demo_mode:
            self._tasks.append(
                asyncio.create_task(self._loop(purge_expired_demo_users, DEMO_PURGE_INTERVAL_SECONDS), name="demo-purge")
            )
        if get_settings().history_backfill_enabled:
            self._tasks.append(
                asyncio.create_task(self._loop(backfill_history, BACKFILL_INTERVAL_SECONDS), name="history-backfill")
            )

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
