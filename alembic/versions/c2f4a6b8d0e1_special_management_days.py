"""model management as special full-day assignments

Revision ID: c2f4a6b8d0e1
Revises: bf1e2d3c4a5b
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2f4a6b8d0e1"
down_revision: str | Sequence[str] | None = "bf1e2d3c4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE members SET management_quota = 0 WHERE management_quota < 0")
    op.execute("UPDATE members SET management_quota = 5 WHERE management_quota > 5")
    op.execute(
        """
        UPDATE assignments
        SET agenda_id = NULL, kind = 'management', management = 1
        WHERE agenda_id = 'gestio'
        """
    )
    op.execute("DELETE FROM fixed_rules WHERE agenda_id = 'gestio'")
    op.execute("DELETE FROM member_capabilities WHERE agenda_id = 'gestio'")
    op.execute("DELETE FROM coverage WHERE agenda_id = 'gestio'")
    op.execute("DELETE FROM agenda_recurrences WHERE agenda_id = 'gestio'")
    op.execute(
        """
        UPDATE agendas
        SET archived_at = COALESCE(archived_at, DATE('now'))
        WHERE id = 'gestio'
        """
    )
    with op.batch_alter_table("members") as batch:
        batch.create_check_constraint(
            "ck_members_management_quota",
            "management_quota BETWEEN 0 AND 5",
        )


def downgrade() -> None:
    with op.batch_alter_table("members") as batch:
        batch.drop_constraint("ck_members_management_quota", type_="check")
