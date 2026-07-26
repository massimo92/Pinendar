"""add mandatory agenda shift

Revision ID: d37f4c2a9b10
Revises: c8e2ab146f90
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d37f4c2a9b10"
down_revision: str | Sequence[str] | None = "c8e2ab146f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.add_column(
            sa.Column("shift", sa.String(length=9), nullable=False, server_default="morning")
        )
        batch_op.create_check_constraint(
            "ck_agendas_shift", "shift IN ('morning', 'afternoon')"
        )


def downgrade() -> None:
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.drop_constraint("ck_agendas_shift", type_="check")
        batch_op.drop_column("shift")
