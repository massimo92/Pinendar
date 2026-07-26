"""member work patterns

Revision ID: g7b21d4c8a10
Revises: f6a09cbe8142
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g7b21d4c8a10"
down_revision: str | Sequence[str] | None = "f6a09cbe8142"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("members") as batch_op:
        batch_op.add_column(
            sa.Column("work_pattern_anchor", sa.Date(), nullable=False, server_default="2024-01-01")
        )
        batch_op.add_column(
            sa.Column("work_pattern_weeks", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.create_check_constraint(
            "ck_members_work_pattern_weeks", "work_pattern_weeks BETWEEN 1 AND 8"
        )

    naming = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}
    with op.batch_alter_table(
        "member_available_days", recreate="always", naming_convention=naming
    ) as batch_op:
        batch_op.add_column(
            sa.Column("week_index", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.drop_constraint(
            "uq_member_available_days_member_id_weekday", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_member_available_days_member_week_weekday",
            ["member_id", "week_index", "weekday"],
        )
        batch_op.create_check_constraint(
            "ck_member_available_days_week_index", "week_index BETWEEN 0 AND 7"
        )


def downgrade() -> None:
    # Older versions can only express one week. Preserve the union of all days.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM member_available_days WHERE id NOT IN ("
            "SELECT MIN(id) FROM member_available_days GROUP BY member_id, weekday)"
        )
    )
    with op.batch_alter_table("member_available_days", recreate="always") as batch_op:
        batch_op.drop_constraint(
            "ck_member_available_days_week_index", type_="check"
        )
        batch_op.drop_constraint(
            "uq_member_available_days_member_week_weekday", type_="unique"
        )
        batch_op.drop_column("week_index")
        batch_op.create_unique_constraint(
            "uq_member_available_days_member_id_weekday", ["member_id", "weekday"]
        )
    with op.batch_alter_table("members") as batch_op:
        batch_op.drop_constraint("ck_members_work_pattern_weeks", type_="check")
        batch_op.drop_column("work_pattern_weeks")
        batch_op.drop_column("work_pattern_anchor")
