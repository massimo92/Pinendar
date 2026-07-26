"""four agenda priority levels

Revision ID: b4d9f730c821
Revises: a21f0c9d7e34
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d9f730c821"
down_revision: str | Sequence[str] | None = "a21f0c9d7e34"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE agendas
            SET priority = CASE
                WHEN priority <= 1 THEN 1
                WHEN priority <= 3 THEN 2
                WHEN priority <= 5 THEN 3
                ELSE 4
            END
            """
        )
    )
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.alter_column(
            "priority", existing_type=sa.Integer(), nullable=False, server_default="3"
        )
        batch_op.create_check_constraint("ck_agendas_priority", "priority BETWEEN 1 AND 4")


def downgrade() -> None:
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.drop_constraint("ck_agendas_priority", type_="check")
        batch_op.alter_column(
            "priority", existing_type=sa.Integer(), nullable=False, server_default="5"
        )
    # The former exact numeric value cannot be reconstructed after grouping.
