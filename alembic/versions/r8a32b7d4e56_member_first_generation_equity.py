"""track member first generation equity

Revision ID: r8a32b7d4e56
Revises: q7f21a6c3d45
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r8a32b7d4e56"
down_revision: str | Sequence[str] | None = "q7f21a6c3d45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("members") as batch_op:
        batch_op.add_column(
            sa.Column(
                "has_completed_generation",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("members") as batch_op:
        batch_op.drop_column("has_completed_generation")
