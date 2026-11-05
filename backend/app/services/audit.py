from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def audit(
    session: AsyncSession,
    action: str,
    *,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: object | None = None,
    ip_address: str | None = None,
    details: dict | None = None,
) -> None:
    """Append an audit record within the caller's transaction."""
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            ip_address=ip_address,
            details=details or {},
        )
    )
