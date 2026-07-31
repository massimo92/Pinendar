"""planning event peonada

Revision ID: o5d09e3f4a12
Revises: n4c98d2e3f01
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "o5d09e3f4a12"
down_revision: str | Sequence[str] | None = "n4c98d2e3f01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("planning_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "peonada",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("planning_events") as batch_op:
        batch_op.drop_column("peonada")
