from fastapi import APIRouter, Request, Response, status

from app.api.deps import CurrentSession, CurrentUser, DbSession, auth_rate_limit, client_ip
from app.core.config import get_settings
from app.core.cache import get_cache
from app.core.exceptions import AuthenticationError, RateLimitedError, ValidationFailedError
from app.core.security import hash_password, verify_password
from app.schemas.common import Message
from app.schemas.user import ChangePasswordRequest, LoginRequest, RegisterRequest, UserOut
from app.services import auth as auth_service
from app.services.audit import audit

router = APIRouter(prefix="/auth", tags=["auth"])


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
    _set_session_cookie(response, token)
    return user


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
    if not verify_password(body.current_password, user.hashed_password):
        # 422, not 401: the session is valid; clients must not treat this as a logout.
        raise ValidationFailedError("Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    await auth_service.revoke_all_sessions(db, user.id, except_id=record.id)
    await audit(db, "auth.password_changed", user_id=user.id, ip_address=client_ip(request))
    return Message(message="Password updated; other sessions were signed out")
