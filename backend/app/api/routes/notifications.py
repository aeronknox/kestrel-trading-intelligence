"""Notifications about simulated paper orders (fills, fill-time rejections, margin calls)."""

from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.api.deps import CurrentUser, DbSession
from app.models.notification import Notification
from app.schemas.common import ORMModel

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(ORMModel):
    id: int
    kind: str
    title: str
    message: str
    symbol: str | None
    order_id: int | None
    created_at: datetime
    read_at: datetime | None


class NotificationsPage(BaseModel):
    notifications: list[NotificationOut]
    unread: int


class MarkRead(BaseModel):
    ids: list[int] | None = Field(None, max_length=500, description="Omit to mark everything read")


@router.get("", response_model=NotificationsPage)
async def list_notifications(user: CurrentUser, db: DbSession, limit: int = Query(50, ge=1, le=500)) -> NotificationsPage:
    rows = (
        await db.scalars(
            select(Notification)
            .where(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(limit)
        )
    ).all()
    unread = await db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return NotificationsPage(notifications=[NotificationOut.model_validate(n) for n in rows], unread=int(unread or 0))


@router.post("/read", response_model=NotificationsPage)
async def mark_read(body: MarkRead, user: CurrentUser, db: DbSession) -> NotificationsPage:
    stmt = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if body.ids is not None:
        stmt = stmt.where(Notification.id.in_(body.ids))
    await db.execute(stmt.values(read_at=datetime.now(UTC)))
    return await list_notifications(user, db, limit=50)
