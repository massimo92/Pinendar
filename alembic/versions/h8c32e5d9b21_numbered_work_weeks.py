"""numbered work weeks and per-week telework

Revision ID: h8c32e5d9b21
Revises: g7b21d4c8a10
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h8c32e5d9b21"
down_revision: str | Sequence[str] | None = "g7b21d4c8a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM member_available_days WHERE week_index >= 5"))
    connection.execute(
        sa.text("UPDATE members SET work_pattern_weeks = 5 WHERE work_pattern_weeks > 5")
    )
    with op.batch_alter_table("members") as batch_op:
        batch_op.drop_constraint("ck_members_work_pattern_weeks", type_="check")
        batch_op.create_check_constraint(
            "ck_members_work_pattern_weeks", "work_pattern_weeks BETWEEN 1 AND 5"
        )
        batch_op.drop_column("work_pattern_anchor")

    with op.batch_alter_table("member_available_days") as batch_op:
        batch_op.drop_constraint(
            "ck_member_available_days_week_index", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_member_available_days_week_index", "week_index BETWEEN 0 AND 4"
        )

    naming = {"uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s"}
    with op.batch_alter_table(
        "member_tele_days", recreate="always", naming_convention=naming
    ) as batch_op:
        batch_op.add_column(
            sa.Column("week_index", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.drop_constraint("uq_member_tele_days_member_id_weekday", type_="unique")
        batch_op.create_unique_constraint(
            "uq_member_tele_days_member_week_weekday",
            ["member_id", "week_index", "weekday"],
        )
        batch_op.create_check_constraint(
            "ck_member_tele_days_week_index", "week_index BETWEEN 0 AND 4"
        )

    # Existing global telework days apply to every pattern week in which that
    # person works the same weekday.
    connection.execute(
        sa.text(
            "INSERT INTO member_tele_days (member_id, week_index, weekday) "
            "SELECT t.member_id, a.week_index, t.weekday "
            "FROM member_tele_days t "
            "JOIN member_available_days a "
            "ON a.member_id = t.member_id AND a.weekday = t.weekday "
            "WHERE t.week_index = 0 AND a.week_index > 0"
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM member_tele_days WHERE id NOT IN ("
            "SELECT MIN(id) FROM member_tele_days GROUP BY member_id, weekday)"
        )
    )
    with op.batch_alter_table("member_tele_days", recreate="always") as batch_op:
        batch_op.drop_constraint("ck_member_tele_days_week_index", type_="check")
        batch_op.drop_constraint(
            "uq_member_tele_days_member_week_weekday", type_="unique"
        )
        batch_op.drop_column("week_index")
        batch_op.create_unique_constraint(
            "uq_member_tele_days_member_id_weekday", ["member_id", "weekday"]
        )
    with op.batch_alter_table("member_available_days") as batch_op:
        batch_op.drop_constraint(
            "ck_member_available_days_week_index", type_="check"
        )
        batch_op.create_check_constraint(
            "ck_member_available_days_week_index", "week_index BETWEEN 0 AND 7"
        )
    with op.batch_alter_table("members") as batch_op:
        batch_op.drop_constraint("ck_members_work_pattern_weeks", type_="check")
        batch_op.add_column(
            sa.Column("work_pattern_anchor", sa.Date(), nullable=False, server_default="2024-01-01")
        )
        batch_op.create_check_constraint(
            "ck_members_work_pattern_weeks", "work_pattern_weeks BETWEEN 1 AND 8"
        )
