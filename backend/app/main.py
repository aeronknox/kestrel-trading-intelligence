"""FastAPI application factory."""

import hmac
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import (
    alerts,
    analysis,
    assistant,
    auth,
    backtests,
    dashboard,
    journal,
    market,
    notifications,
    paper,
    price_alerts,
    research,
    strategies,
    users,
    watchlists,
    ws,
)
from app.core.cache import close_cache, get_cache, init_cache
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.metrics import CONTENT_TYPE, HTTP_LATENCY, HTTP_REQUESTS, render
from app.database.session import dispose_engine, get_sessionmaker, init_engine
from app.market_data.providers.registry import close_providers, get_provider
from app.market_data.service import MarketDataService
from app.services.background import jobs

logger = get_logger(__name__)


def _route_template(request: Request) -> str:
    """The route template, e.g. /api/v1/strategies/{strategy_id} for /api/v1/strategies/42, so metric labels stay a small set."""
    if request.scope.get("route") is None:
        return "unmatched"
    params = {str(v): k for k, v in request.path_params.items()}
    return "/".join(f"{{{params[seg]}}}" if seg in params else seg for seg in request.url.path.split("/"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_engine()
    await init_cache(settings.redis_url)
    try:
        async with get_sessionmaker()() as session:
            await MarketDataService(session).ensure_default_assets()
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - e.g. migrations not applied yet
        logger.error("asset_seed_failed", error=str(exc), hint="Run `alembic upgrade head`")
    if app.state.background:
        ws.broadcaster.start()  # live prices are per instance: each serves its own browsers
        if settings.run_background_jobs:
            jobs.start()
    if settings.is_production and not settings.cookie_secure:
        logger.warning("insecure_cookies_in_production", hint="Serve over HTTPS and set COOKIE_SECURE=true")
    if settings.is_production and settings.email_backend == "console":
        logger.warning("email_console_backend_in_production", hint="Set EMAIL_BACKEND=smtp so verification and reset emails are delivered")
    provider = get_provider()
    logger.info(
        "startup_complete",
        environment=settings.environment,
        market_data=provider.name,
        sample_data=provider.is_sample,
        ai_enabled=settings.ai_enabled,
        cache=get_cache().backend,
    )
    yield
    await ws.broadcaster.stop()
    await jobs.stop()
    await close_providers()
    await close_cache()
    await dispose_engine()


def create_app(*, background: bool = True) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "AI trading intelligence API — research and SIMULATED paper trading only. "
            "No real-money brokerage execution is supported."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.background = background

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        duration_ms = round(elapsed * 1000, 1)
        if request.url.path != "/metrics":
            route = _route_template(request)
            HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
            HTTP_LATENCY.labels(request.method, route).observe(elapsed)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith(settings.api_prefix):
            response.headers["Cache-Control"] = "no-store"
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path not in ("/health", "/health/ready"):
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                user_id=getattr(request.state, "user_id", None),
            )
        return response

    register_exception_handlers(app)

    api = APIRouter(prefix=settings.api_prefix)
    for module in (auth, users, market, watchlists, analysis, strategies, backtests, research, alerts, price_alerts, notifications, journal, paper, dashboard, assistant, ws):
        api.include_router(module.router)
    app.include_router(api)

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", tags=["health"], include_in_schema=False)
    async def metrics(request: Request) -> Response:
        """Prometheus scrape endpoint. Not routed publicly by the Caddy deployment."""
        if not settings.metrics_enabled:
            return Response(status_code=404)
        if settings.metrics_token:
            sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not hmac.compare_digest(sent.encode(), settings.metrics_token.encode()):
                return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return Response(render(), media_type=CONTENT_TYPE)

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict:
        checks: dict[str, str] = {}
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {type(exc).__name__}"
        checks["cache"] = get_cache().backend
        provider = get_provider()
        stream = ws.broadcaster.stream
        return {
            "status": "ok" if checks["database"] == "ok" else "degraded",
            "checks": checks,
            "market_data": {
                "provider": provider.name,
                "is_sample": provider.is_sample,
                "stream": stream.status() if stream else {"enabled": False},
            },
            "ai_enabled": settings.ai_enabled,
            "background_jobs": jobs.status(),
        }

    return app


app = create_app()
