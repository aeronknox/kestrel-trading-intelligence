import json
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession, client_ip, rate_limit
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.models.audit import AuditLog
from app.models.user import User, UserSettings
from app.schemas.user import AdminUserUpdate, AuditLogOut, ProfileUpdate, UserOut, UserSettingsOut, UserSettingsUpdate
from app.services import account as account_service
from app.services import webhooks
from app.services.alerts import DISCLAIMER
from app.services.audit import audit
from app.services.auth import revoke_all_sessions

router = APIRouter(tags=["users"])


@router.patch("/users/me", response_model=UserOut)
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DbSession) -> object:
    user.full_name = body.full_name.strip()
    await audit(db, "user.profile_updated", user_id=user.id)
    return user


@router.get("/users/me/export", dependencies=[rate_limit("export", "compute_rate_limit_per_minute")])
async def export_my_data(user: CurrentUser, request: Request, db: DbSession) -> Response:
    """Download everything stored about the signed-in user, as one JSON file."""
    data = await account_service.export_user_data(db, user)
    await audit(db, "user.data_exported", user_id=user.id, ip_address=client_ip(request))
    filename = f"kestrel-data-{datetime.now(UTC):%Y%m%d}.json"
    return Response(
        content=json.dumps(data, indent=2, ensure_ascii=False, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/users/me/settings", response_model=UserSettingsOut)
async def get_settings_(user: CurrentUser, db: DbSession) -> object:
    if user.settings is None:
        user.settings = UserSettings()
        await db.flush()
    return user.settings


@router.patch("/users/me/settings", response_model=UserSettingsOut)
async def update_settings(body: UserSettingsUpdate, user: CurrentUser, db: DbSession) -> object:
    if user.settings is None:
        user.settings = UserSettings()
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(user.settings, key, value.upper() if key == "default_symbol" else value)
    await db.flush()
    return user.settings


# ----------------------------------------------------------------- alert webhook
class WebhookOut(BaseModel):
    url: str | None
    orders: bool = False  # also post simulated paper order fills, rejections and margin calls
    format: webhooks.WebhookFormat | None
    # Signs generic JSON deliveries (X-Kestrel-Signature); shown only to its owner.
    secret: str | None
    last_status: str | None
    last_at: datetime | None


class WebhookIn(BaseModel):
    url: str = Field(min_length=10, max_length=webhooks.MAX_URL_LENGTH)


class WebhookTestOut(BaseModel):
    ok: bool
    webhook: WebhookOut


def _webhook_out(s: UserSettings | None) -> WebhookOut:
    url = s.webhook_url if s else None
    return WebhookOut(url=url, orders=bool(s and s.webhook_orders), format=webhooks.webhook_format(url) if url else None,
                      secret=s.webhook_secret if s and url else None,
                      last_status=s.webhook_last_status if s else None, last_at=s.webhook_last_at if s else None)  # fmt: skip


async def _settings_for_webhook(user: User, db: DbSession) -> UserSettings:
    if user.is_demo:
        raise PermissionDeniedError("Webhooks are not available in the demo; create a free account to use them")
    if user.settings is None:
        user.settings = UserSettings()
        await db.flush()
    return user.settings


@router.get("/users/me/webhook", response_model=WebhookOut)
async def get_webhook(user: CurrentUser) -> WebhookOut:
    return _webhook_out(user.settings)


@router.put("/users/me/webhook", response_model=WebhookOut)
async def set_webhook(body: WebhookIn, user: CurrentUser, db: DbSession) -> WebhookOut:
    s = await _settings_for_webhook(user, db)
    try:
        target = await webhooks.check_url(body.url)
    except webhooks.WebhookError as exc:
        raise ValidationFailedError(str(exc)) from exc
    if target.url != s.webhook_url:
        s.webhook_last_status, s.webhook_last_at = None, None
    s.webhook_url = target.url
    s.webhook_secret = s.webhook_secret or webhooks.new_secret()
    await audit(db, "user.webhook_set", user_id=user.id, details={"host": target.host})
    return _webhook_out(s)


@router.delete("/users/me/webhook", response_model=WebhookOut)
async def delete_webhook(user: CurrentUser, db: DbSession) -> WebhookOut:
    s = await _settings_for_webhook(user, db)
    s.webhook_url = s.webhook_secret = s.webhook_last_status = None
    s.webhook_last_at = None
    await audit(db, "user.webhook_removed", user_id=user.id)
    return _webhook_out(s)


class WebhookOptions(BaseModel):
    orders: bool


@router.patch("/users/me/webhook", response_model=WebhookOut)
async def update_webhook_options(body: WebhookOptions, user: CurrentUser, db: DbSession) -> WebhookOut:
    s = await _settings_for_webhook(user, db)
    s.webhook_orders = body.orders
    return _webhook_out(s)


@router.post("/users/me/webhook/secret", response_model=WebhookOut)
async def rotate_webhook_secret(user: CurrentUser, db: DbSession) -> WebhookOut:
    s = await _settings_for_webhook(user, db)
    if not s.webhook_url:
        raise ValidationFailedError("Set a webhook URL first")
    s.webhook_secret = webhooks.new_secret()
    return _webhook_out(s)


@router.post("/users/me/webhook/test", response_model=WebhookTestOut,
             dependencies=[rate_limit("webhook-test", "auth_rate_limit_per_minute")])  # fmt: skip
async def test_webhook(user: CurrentUser, db: DbSession) -> WebhookTestOut:
    """Send a sample notification. The result is returned (and kept as the last status), not raised."""
    s = await _settings_for_webhook(user, db)
    if not s.webhook_url or not s.webhook_secret:
        raise ValidationFailedError("Set a webhook URL first")
    title = "Test notification from Kestrel Intelligence"
    lines = ["Strategy alerts with webhook delivery switched on will arrive here.", DISCLAIMER]
    payload = webhooks.build_payload(webhooks.webhook_format(s.webhook_url), title, lines, {"type": "test", "disclaimer": DISCLAIMER})
    ok = True
    try:
        s.webhook_last_status = await webhooks.deliver(s.webhook_url, s.webhook_secret, payload)
    except webhooks.WebhookError as exc:
        ok, s.webhook_last_status = False, f"Failed: {exc}"[:255]
    s.webhook_last_at = datetime.now(UTC)
    return WebhookTestOut(ok=ok, webhook=_webhook_out(s))


# ----------------------------------------------------------------- admin (RBAC)
@router.get("/admin/users", response_model=list[UserOut])
async def list_users(_: AdminUser, db: DbSession, limit: int = Query(100, le=500), offset: int = 0) -> object:
    return (await db.scalars(select(User).order_by(User.id).limit(limit).offset(offset))).all()


@router.patch("/admin/users/{user_id}", response_model=UserOut)
async def admin_update_user(user_id: int, body: AdminUserUpdate, admin: AdminUser, request: Request, db: DbSession) -> object:
    target = await db.get(User, user_id)
    if target is None:
        raise NotFoundError("User not found")
    if target.id == admin.id and (body.role is not None or body.is_active is False):
        raise ValidationFailedError("Administrators cannot change their own role or disable themselves")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(target, key, value)
    if body.is_active is False:
        await revoke_all_sessions(db, target.id)
    await audit(
        db, "admin.user_updated", user_id=admin.id, entity_type="user", entity_id=target.id,
        ip_address=client_ip(request), details={k: str(v) for k, v in changes.items()},
    )  # fmt: skip
    return target


@router.get("/admin/audit-logs", response_model=list[AuditLogOut])
async def audit_logs(
    _: AdminUser,
    db: DbSession,
    action: str | None = None,
    user_id: int | None = None,
    limit: int = Query(100, le=500),
) -> object:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    return (await db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(limit))).all()


@router.get("/admin/stats")
async def admin_stats(_: AdminUser, db: DbSession) -> dict:
    users = await db.scalar(select(func.count()).select_from(User))
    active = await db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
    return {"users": users, "active_users": active}
