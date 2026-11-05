from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    hash_password,
    hash_session_token,
    new_session_token,
    password_needs_rehash,
    verify_password,
)
from app.models.enums import UserRole
from app.models.market import Asset, Watchlist, WatchlistItem
from app.models.user import User, UserSession, UserSettings

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


async def register_user(session: AsyncSession, email: str, password: str, full_name: str) -> User:
    email = email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("An account with this email already exists")
    role = UserRole.ADMIN if email in get_settings().admin_emails else UserRole.USER
    user = User(email=email, hashed_password=hash_password(password), full_name=full_name, role=role)
    user.settings = UserSettings()
    session.add(user)
    await session.flush()

    # Starter watchlist with the first few tracked assets.
    watchlist = Watchlist(user_id=user.id, name="Default")
    session.add(watchlist)
    await session.flush()
    for pos, asset_id in enumerate((await session.scalars(select(Asset.id).order_by(Asset.id).limit(5))).all()):
        session.add(WatchlistItem(watchlist_id=watchlist.id, asset_id=asset_id, position=pos))
    await session.flush()
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        verify_password(password, DUMMY_PASSWORD_HASH)  # equalize timing
        raise AuthenticationError("Invalid email or password")
    if not verify_password(password, user.hashed_password):
        raise AuthenticationError("Invalid email or password")
    if not user.is_active:
        raise AuthenticationError("This account is disabled")
    if password_needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    return user


async def create_session(
    session: AsyncSession, user: User, *, ip_address: str | None, user_agent: str | None
) -> tuple[str, UserSession]:
    token = new_session_token()
    now = datetime.now(UTC)
    record = UserSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=get_settings().session_ttl_hours),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
    )
    session.add(record)
    await session.flush()
    return token, record


async def resolve_session(session: AsyncSession, token: str) -> tuple[User, UserSession] | None:
    record = await session.scalar(select(UserSession).where(UserSession.token_hash == hash_session_token(token)))
    now = datetime.now(UTC)
    if record is None or record.revoked_at is not None or record.expires_at <= now:
        return None
    user = await session.get(User, record.user_id)
    if user is None or not user.is_active:
        return None
    if now - record.last_seen_at > SESSION_TOUCH_INTERVAL:
        record.last_seen_at = now
    return user, record


async def revoke_session(session: AsyncSession, record: UserSession) -> None:
    record.revoked_at = datetime.now(UTC)


async def revoke_all_sessions(session: AsyncSession, user_id: int, *, except_id: int | None = None) -> None:
    stmt = update(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_id is not None:
        stmt = stmt.where(UserSession.id != except_id)
    await session.execute(stmt.values(revoked_at=datetime.now(UTC)))
