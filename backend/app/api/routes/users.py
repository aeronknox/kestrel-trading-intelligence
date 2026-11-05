from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession, client_ip
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.models.audit import AuditLog
from app.models.user import User, UserSettings
from app.schemas.user import AdminUserUpdate, AuditLogOut, ProfileUpdate, UserOut, UserSettingsOut, UserSettingsUpdate
from app.services.audit import audit
from app.services.auth import revoke_all_sessions

router = APIRouter(tags=["users"])


@router.patch("/users/me", response_model=UserOut)
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DbSession) -> object:
    user.full_name = body.full_name.strip()
    await audit(db, "user.profile_updated", user_id=user.id)
    return user


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
