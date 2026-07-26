"""manual hospitals and agenda load

Revision ID: f6a09cbe8142
Revises: e5217ac934d1
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a09cbe8142"
down_revision: str | Sequence[str] | None = "e5217ac934d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hospitals") as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("address", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("location_known", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    with op.batch_alter_table("agendas") as batch_op:
        batch_op.add_column(
            sa.Column("load_percentage", sa.Integer(), nullable=False, server_default="100")
        )
        batch_op.create_check_constraint(
            "ck_agendas_load_percentage", "load_percentage IN (50, 100)"
        )

    naming = {
        "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s_%(column_2_name)s"
    }
    with op.batch_alter_table(
        "assignments", recreate="always", naming_convention=naming
    ) as batch_op:
        batch_op.drop_constraint(
            "uq_assignments_proposal_id_date_member_id", type_="unique"
        )


def downgrade() -> None:
    with op.batch_alter_table("assignments") as batch_op:
        batch_op.create_unique_constraint(
            "uq_assignments_proposal_id_date_member_id",
            ["proposal_id", "date", "member_id"],
        )
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.drop_constraint("ck_agendas_load_percentage", type_="check")
        batch_op.drop_column("load_percentage")
    with op.batch_alter_table("hospitals") as batch_op:
        batch_op.drop_column("location_known")
        batch_op.drop_column("address")
        batch_op.drop_column("name")
