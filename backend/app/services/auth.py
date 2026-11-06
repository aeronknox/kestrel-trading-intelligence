from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, ConflictError, ValidationFailedError
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
from app.models.user import AuthToken, User, UserSession, UserSettings

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


async def register_user(session: AsyncSession, email: str, password: str, full_name: str) -> User:
    email = email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("An account with this email already exists")
    # ADMIN_EMAILS is applied only once the address is verified (see mark_email_verified).
    user = User(email=email, hashed_password=hash_password(password), full_name=full_name, role=UserRole.USER)
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


# ------------------------------------------------------------ emailed tokens
VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"
INVALID_LINK = "This link is invalid or has expired. Request a new one."


async def issue_token(session: AsyncSession, user: User, purpose: str, ttl: timedelta) -> str:
    """Create a single-use token; any earlier unused token for the same purpose stops working."""
    now = datetime.now(UTC)
    await session.execute(
        update(AuthToken)
        .where(AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = new_session_token()
    session.add(AuthToken(user_id=user.id, purpose=purpose, token_hash=hash_session_token(token), created_at=now,
                          expires_at=now + ttl))  # fmt: skip
    await session.flush()
    return token


async def consume_token(session: AsyncSession, token: str, purpose: str) -> User:
    """Atomically mark a valid token used and return its user; raises if invalid, expired or already used."""
    now = datetime.now(UTC)
    # A single conditional UPDATE makes the token single-use even under concurrent requests.
    user_id = await session.scalar(
        update(AuthToken)
        .where(
            AuthToken.token_hash == hash_session_token(token),
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthToken.user_id)
    )
    user = await session.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise ValidationFailedError(INVALID_LINK)
    return user


def mark_email_verified(user: User) -> bool:
    """Record verification and apply ADMIN_EMAILS. Returns True if the user was just granted admin."""
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(UTC)
    if user.role == UserRole.USER and user.email in get_settings().admin_emails:
        user.role = UserRole.ADMIN
        return True
    return False
