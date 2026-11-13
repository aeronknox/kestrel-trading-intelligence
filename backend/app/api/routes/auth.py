from datetime import timedelta

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentSession, CurrentUser, DbSession, auth_rate_limit, client_ip
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, NotFoundError, PermissionDeniedError, RateLimitedError, ValidationFailedError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.common import Message
from app.schemas.user import (
    ChangePasswordRequest,
    EmailRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
    UserOut,
)
from app.services import auth as auth_service
from app.services.audit import audit
from app.services.demo import DemoCapacityError, create_demo_user, ensure_capacity
from app.services.email import password_reset_email, send_email, verification_email

router = APIRouter(prefix="/auth", tags=["auth"])

EMAIL_COOLDOWN_SECONDS = 60  # per address, so the endpoints can't be used to flood someone's inbox
FORGOT_MESSAGE = "If an account exists for that email, we sent a link to reset the password."


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.session_cookie_name,
        value=token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(s.session_cookie_name, path="/", httponly=True, secure=s.cookie_secure, samesite="lax")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=[auth_rate_limit()])
async def register(body: RegisterRequest, request: Request, response: Response, db: DbSession) -> object:
    user = await auth_service.register_user(db, body.email, body.password, body.full_name)
    token, _ = await auth_service.create_session(
        db, user, ip_address=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    await audit(db, "user.register", user_id=user.id, entity_type="user", entity_id=user.id, ip_address=client_ip(request))
    await _send_verification(db, user)
    _set_session_cookie(response, token)
    return user


@router.get("/config")
async def auth_config() -> dict:
    """Public sign-in options for the auth pages. `email_delivery` is "console" when emails (reset and
    verification links) are only written to the server log, so the pages can say so instead of
    telling people to check an inbox that will stay empty."""
    settings = get_settings()
    return {"demo_enabled": settings.demo_mode, "email_delivery": settings.email_backend}


@router.post("/demo", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=[auth_rate_limit()])
async def start_demo(request: Request, response: Response, db: DbSession) -> object:
    """Create a throwaway, pre-loaded sandbox account and sign in to it (DEMO_MODE only)."""
    if not get_settings().demo_mode:
        raise NotFoundError("The demo is not enabled on this server")
    try:
        await ensure_capacity(db)
    except DemoCapacityError as exc:
        raise RateLimitedError("The demo is at capacity right now. Try again later, or create a free account.") from exc
    user = await create_demo_user(db)
    token, _ = await auth_service.create_session(db, user, ip_address=client_ip(request), user_agent=request.headers.get("user-agent"))
    await audit(db, "user.demo_started", user_id=user.id, ip_address=client_ip(request))
    _set_session_cookie(response, token)
    return user


def _no_demo(user: User) -> None:
    if user.is_demo:
        raise PermissionDeniedError("Not available in the demo. Create a free account to use this.")


async def _cooldown(key: str) -> bool:
    """True if `key` was used within the cooldown window (and starts a new window otherwise)."""
    return await get_cache().incr_window(key, EMAIL_COOLDOWN_SECONDS) > 1


async def _send_verification(db, user: User) -> bool:  # type: ignore[no-untyped-def]
    ttl = timedelta(hours=get_settings().email_verification_ttl_hours)
    token = await auth_service.issue_token(db, user, auth_service.VERIFY_EMAIL, ttl)
    return await send_email(verification_email(user.email, user.full_name, token))


@router.post("/verify-email/resend", response_model=Message, dependencies=[auth_rate_limit()])
async def resend_verification(user: CurrentUser, db: DbSession) -> Message:
    _no_demo(user)
    if user.email_verified:
        return Message(message="Your email address is already verified")
    if await _cooldown(f"email-cooldown:verify:{user.id}"):
        raise RateLimitedError("A verification email was just sent; wait a minute before asking again")
    if not await _send_verification(db, user):
        raise ValidationFailedError("We could not send the email right now; try again later")
    return Message(message=f"Verification email sent to {user.email}")


@router.post("/verify-email", response_model=Message, dependencies=[auth_rate_limit()])
async def verify_email(body: TokenRequest, request: Request, db: DbSession) -> Message:
    """Works without a session, so the link can be opened in any browser."""
    user = await auth_service.consume_token(db, body.token, auth_service.VERIFY_EMAIL)
    promoted = auth_service.mark_email_verified(user)
    await audit(db, "user.email_verified", user_id=user.id, ip_address=client_ip(request), details={"granted_admin": promoted})
    return Message(message="Email address verified")


@router.post("/forgot-password", response_model=Message, status_code=status.HTTP_202_ACCEPTED, dependencies=[auth_rate_limit()])
async def forgot_password(body: EmailRequest, request: Request, db: DbSession) -> Message:
    """Same response whether or not the account exists, so it can't be used to discover accounts."""
    email = body.email.lower()
    user = await db.scalar(select(User).where(User.email == email))
    if user is not None and user.is_active and not user.is_demo and not await _cooldown(f"email-cooldown:reset:{email}"):
        ttl = timedelta(minutes=get_settings().password_reset_ttl_minutes)
        token = await auth_service.issue_token(db, user, auth_service.RESET_PASSWORD, ttl)
        await send_email(password_reset_email(user.email, user.full_name, token))
        await audit(db, "auth.password_reset_requested", user_id=user.id, ip_address=client_ip(request))
    return Message(message=FORGOT_MESSAGE)


@router.post("/reset-password", response_model=Message, dependencies=[auth_rate_limit()])
async def reset_password(body: ResetPasswordRequest, request: Request, db: DbSession) -> Message:
    user = await auth_service.consume_token(db, body.token, auth_service.RESET_PASSWORD)
    user.hashed_password = hash_password(body.new_password)
    auth_service.mark_email_verified(user)  # the link proves the user controls the address
    await auth_service.revoke_all_sessions(db, user.id)
    await get_cache().delete(f"login-fail:{user.email}")
    await audit(db, "auth.password_reset", user_id=user.id, ip_address=client_ip(request))
    return Message(message="Password updated. Sign in with your new password.")


@router.post("/login", response_model=UserOut, dependencies=[auth_rate_limit()])
async def login(body: LoginRequest, request: Request, response: Response, db: DbSession) -> object:
    ip = client_ip(request)
    settings = get_settings()
    fail_key = f"login-fail:{body.email.lower()}"
    cache = get_cache()
    # Per-account lockout complements the per-IP limiter (defeats distributed guessing).
    if int(await cache.get_json(fail_key) or 0) >= settings.login_max_failures:
        raise RateLimitedError(
            f"Too many failed sign-in attempts for this account; try again in {settings.login_lockout_minutes} minutes"
        )
    try:
        user = await auth_service.authenticate(db, body.email, body.password)
    except AuthenticationError:
        await cache.incr_window(fail_key, settings.login_lockout_minutes * 60)
        await audit(db, "auth.login_failed", ip_address=ip, details={"email": body.email.lower()})
        await db.commit()  # persist the audit record even though we raise
        raise
    await cache.delete(fail_key)
    token, _ = await auth_service.create_session(db, user, ip_address=ip, user_agent=request.headers.get("user-agent"))
    await audit(db, "auth.login", user_id=user.id, ip_address=ip)
    _set_session_cookie(response, token)
    return user


@router.post("/logout", response_model=Message)
async def logout(ctx: CurrentSession, request: Request, response: Response, db: DbSession) -> Message:
    user, record = ctx
    await auth_service.revoke_session(db, record)
    await audit(db, "auth.logout", user_id=user.id, ip_address=client_ip(request))
    _clear_session_cookie(response)
    return Message(message="Logged out")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> object:
    return user


@router.post("/change-password", response_model=Message, dependencies=[auth_rate_limit()])
async def change_password(body: ChangePasswordRequest, ctx: CurrentSession, request: Request, db: DbSession) -> Message:
    user, record = ctx
    _no_demo(user)
    if not verify_password(body.current_password, user.hashed_password):
        # 422, not 401: the session is valid; clients must not treat this as a logout.
        raise ValidationFailedError("Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    await auth_service.revoke_all_sessions(db, user.id, except_id=record.id)
    await audit(db, "auth.password_changed", user_id=user.id, ip_address=client_ip(request))
    return Message(message="Password updated; other sessions were signed out")
