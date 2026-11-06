"""one active paper portfolio per user

Revision ID: 7c2d9e4a1b3f
Revises: 4f41b2b201e9
Create Date: 2026-11-06 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '7c2d9e4a1b3f'
down_revision: str | None = '4f41b2b201e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A race could previously create duplicates; keep each user's oldest active portfolio.
    op.execute(
        """
        UPDATE paper_portfolios SET is_active = false
        WHERE is_active AND id NOT IN (
            SELECT min_id FROM (
                SELECT MIN(id) AS min_id FROM paper_portfolios WHERE is_active GROUP BY user_id
            ) AS keep
        )
        """
    )
    op.create_index(
        'uq_paper_portfolios_active_user',
        'paper_portfolios',
        ['user_id'],
        unique=True,
        sqlite_where=sa.text('is_active'),
        postgresql_where=sa.text('is_active'),
    )


def downgrade() -> None:
    op.drop_index('uq_paper_portfolios_active_user', table_name='paper_portfolios')
