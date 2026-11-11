import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Configure the app for tests *before* importing it.
_tmp = Path(tempfile.mkdtemp(prefix="ti-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        # TEST_DATABASE_URL runs the suite against another database (CI uses PostgreSQL).
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}",
        "REDIS_URL": "",
        "OPENAI_API_KEY": "",
        "MARKET_DATA_PROVIDER": "sample",
        "RATE_LIMIT_PER_MINUTE": "100000",
        "AUTH_RATE_LIMIT_PER_MINUTE": "100000",
        "COMPUTE_RATE_LIMIT_PER_MINUTE": "100000",
        "ADMIN_EMAILS": "admin@example.com",
        "SECRET_KEY": "test-secret-key-that-is-long-enough",
        "WORKER_METRICS_PORT": "0",  # tests that need it pick a free port
    }
)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.database.base import Base  # noqa: E402
from app.database.session import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.market_data.providers.base import Ticker  # noqa: E402
from app.market_data.providers.registry import register_provider  # noqa: E402
from app.market_data.providers.sample import SampleProvider  # noqa: E402


class ControllableProvider(SampleProvider):
    """Sample provider whose live price can be pinned by tests."""

    def __init__(self) -> None:
        self.prices: dict[str, float] = {}

    async def set_price(self, symbol: str, price: float) -> None:
        """Pin the live price and invalidate the cached ticker."""
        from app.core.cache import get_cache

        self.prices[symbol] = price
        await get_cache().delete(f"ticker:{self.name}:{symbol}")

    async def get_ticker(self, provider_symbol: str) -> Ticker:
        if provider_symbol in self.prices:
            p = self.prices[provider_symbol]
            return Ticker(provider_symbol, p, p, p, p, 0.0, datetime.now(UTC))
        return await super().get_ticker(provider_symbol)


@pytest.fixture
def provider() -> ControllableProvider:
    p = ControllableProvider()
    register_provider(p)
    return p


@pytest.fixture
async def app(provider):  # type: ignore[no-untyped-def]
    application = create_app(background=False)
    async with application.router.lifespan_context(application):
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # Re-seed assets now that tables exist.
        from app.database.session import get_sessionmaker
        from app.market_data.service import MarketDataService

        async with get_sessionmaker()() as s:
            await MarketDataService(s, provider).ensure_default_assets()
            await s.commit()
        from app.core.cache import get_cache

        cache = get_cache()
        if hasattr(cache, "_data"):
            cache._data.clear()
        yield application


@pytest.fixture
async def client(app):  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def register(client: AsyncClient, email: str = "user@example.com", password: str = "s3cure-passw0rd") -> dict:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password, "full_name": "Test User"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def auth_client(client):  # type: ignore[no-untyped-def]
    await register(client)
    return client


def make_frame(closes: list[float], start: datetime | None = None, step: timedelta = timedelta(hours=1)) -> pd.DataFrame:
    """OHLCV frame where open = previous close and high/low bracket the bar."""
    start = start or datetime(2024, 1, 1, tzinfo=UTC)
    closes_arr = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes_arr[0]], closes_arr[:-1]])
    return pd.DataFrame(
        {
            "ts": [start + i * step for i in range(len(closes_arr))],
            "open": opens,
            "high": np.maximum(opens, closes_arr) * 1.001,
            "low": np.minimum(opens, closes_arr) * 0.999,
            "close": closes_arr,
            "volume": np.full(len(closes_arr), 100.0),
        }
    )
