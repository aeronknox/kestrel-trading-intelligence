"""Operational commands.

    python -m app.cli promote-admin user@example.com
    python -m app.cli demote-admin user@example.com

Prefer this over ADMIN_EMAILS on publicly reachable deployments: ADMIN_EMAILS grants the
role at registration and emails are not verified, so whoever registers first gets it.
"""

import asyncio
import sys

from sqlalchemy import select

from app.database.session import dispose_engine, get_sessionmaker
from app.models.enums import UserRole
from app.models.user import User
from app.services.audit import audit


async def set_role(email: str, role: UserRole) -> int:
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            print(f"No user with email {email}", file=sys.stderr)
            return 1
        user.role = role
        await audit(session, "admin.role_changed_cli", user_id=user.id, entity_type="user", entity_id=user.id, details={"role": role.value})
        await session.commit()
        print(f"{user.email} is now {role.value}")
    return 0


async def _run(email: str, role: UserRole) -> int:
    try:
        return await set_role(email, role)
    finally:
        await dispose_engine()


def main(argv: list[str]) -> int:
    commands = {"promote-admin": UserRole.ADMIN, "demote-admin": UserRole.USER}
    if len(argv) != 2 or argv[0] not in commands:
        print(__doc__)
        return 2
    return asyncio.run(_run(argv[1], commands[argv[0]]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
