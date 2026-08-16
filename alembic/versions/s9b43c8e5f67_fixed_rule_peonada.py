"""fixed rule peonada

Revision ID: s9b43c8e5f67
Revises: r8a32b7d4e56
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "s9b43c8e5f67"
down_revision: str | Sequence[str] | None = "r8a32b7d4e56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("fixed_rule_agendas") as batch_op:
        batch_op.add_column(
            sa.Column("peonada", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.create_check_constraint(
            "ck_fixed_rule_agendas_peonada_required",
            "peonada = 0 OR effect = 'required'",
        )


def downgrade() -> None:
    with op.batch_alter_table("fixed_rule_agendas") as batch_op:
        batch_op.drop_constraint("ck_fixed_rule_agendas_peonada_required", type_="check")
        batch_op.drop_column("peonada")
