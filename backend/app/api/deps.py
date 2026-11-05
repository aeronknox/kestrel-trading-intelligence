"""Shared FastAPI dependencies: DB session, current user, RBAC, rate limits."""

import hmac
import ipaddress
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError, RateLimitedError
from app.database.session import get_db
from app.models.enums import UserRole
from app.models.user import User, UserSession
from app.services.auth import resolve_session

# scope="function": the commit in get_db runs *before* the response is sent, so a failed
# commit becomes an error response instead of a false 200 (FastAPI's default runs yield
# teardown after the response has gone out).
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]


def _peer_is_trusted(request: Request) -> bool:
    settings = get_settings()
    secret = settings.proxy_shared_secret
    presented = request.headers.get("x-proxy-secret")
    if secret and presented and hmac.compare_digest(secret, presented):
        return True
    peer = request.client.host if request.client else None
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for cidr in settings.trusted_proxies:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request) -> str:
    """Client address for rate limiting/audit. X-Forwarded-For is only believed when the
    immediate peer is a trusted proxy; otherwise any client could spoof its identity."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _peer_is_trusted(request):
        return forwarded.split(",")[0].strip()[:64] or peer
    return peer


async def get_current_session(request: Request, db: DbSession) -> tuple[User, UserSession]:
    token = request.cookies.get(get_settings().session_cookie_name)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        raise AuthenticationError("Authentication required")
    resolved = await resolve_session(db, token)
    if resolved is None:
        raise AuthenticationError("Session expired or invalid")
    request.state.user_id = resolved[0].id
    return resolved


async def get_current_user(ctx: Annotated[tuple[User, UserSession], Depends(get_current_session)]) -> User:
    return ctx[0]


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSession = Annotated[tuple[User, UserSession], Depends(get_current_session)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Administrator role required")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def rate_limit(bucket: str, setting: str = "rate_limit_per_minute"):  # type: ignore[no-untyped-def]
    """Fixed-window limiter keyed by client IP (Redis-backed when available)."""

    async def _dep(request: Request) -> None:
        limit = int(getattr(get_settings(), setting))
        count = await get_cache().incr_window(f"rl:{bucket}:{client_ip(request)}", 60)
        if count > limit:
            raise RateLimitedError(f"Too many requests; limit is {limit}/minute")

    return Depends(_dep)


def auth_rate_limit():  # type: ignore[no-untyped-def]
    return rate_limit("auth", "auth_rate_limit_per_minute")
