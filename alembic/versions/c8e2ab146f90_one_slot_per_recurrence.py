"""one slot per agenda recurrence

Revision ID: c8e2ab146f90
Revises: b4d9f730c821
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c8e2ab146f90"
down_revision: str | Sequence[str] | None = "b4d9f730c821"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("UPDATE agenda_recurrences SET slots = 1"))
    with op.batch_alter_table("agenda_recurrences") as batch_op:
        batch_op.alter_column("slots", existing_type=sa.Integer(), nullable=False, server_default="1")
        batch_op.create_check_constraint("ck_agenda_recurrences_one_slot", "slots = 1")


def downgrade() -> None:
    with op.batch_alter_table("agenda_recurrences") as batch_op:
        batch_op.drop_constraint("ck_agenda_recurrences_one_slot", type_="check")
        batch_op.alter_column("slots", existing_type=sa.Integer(), nullable=False, server_default=None)
