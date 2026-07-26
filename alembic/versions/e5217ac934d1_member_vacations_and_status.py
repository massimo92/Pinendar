"""separate vacations from tracked member status

Revision ID: e5217ac934d1
Revises: d37f4c2a9b10
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5217ac934d1"
down_revision: str | Sequence[str] | None = "d37f4c2a9b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("members") as batch_op:
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        "member_status_changes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # A current legacy sick-leave period becomes an inactive profile. Historical
    # transitions are kept so the old information is not discarded.
    connection = op.get_bind()
    legacy_sick_leaves = connection.execute(
        sa.text("SELECT id, member_id, start, end FROM absences WHERE category = 'baixa'")
    ).mappings()
    for item in legacy_sick_leaves:
        connection.execute(
            sa.text(
                "INSERT INTO member_status_changes (id, member_id, active, changed_at) "
                "VALUES (:start_id, :member_id, 0, :start_at), (:end_id, :member_id, 1, :end_at)"
            ),
            {
                "start_id": f"legacy-status-start-{item['id']}",
                "end_id": f"legacy-status-end-{item['id']}",
                "member_id": item["member_id"],
                "start_at": f"{item['start']} 00:00:00",
                "end_at": f"{item['end']} 23:59:59",
            },
        )
    connection.execute(
        sa.text(
            "UPDATE members SET is_active = 0 WHERE id IN ("
            "SELECT member_id FROM absences WHERE category = 'baixa' "
            "AND date('now') BETWEEN start AND end)"
        )
    )
    connection.execute(sa.text("DELETE FROM absences WHERE category NOT IN ('vacances', 'postguardia')"))
    connection.execute(
        sa.text("DELETE FROM proposal_absences WHERE category NOT IN ('vacances', 'postguardia')")
    )
    with op.batch_alter_table("absences") as batch_op:
        batch_op.create_check_constraint(
            "ck_absences_category", "category IN ('vacances', 'postguardia')"
        )
    with op.batch_alter_table("proposal_absences") as batch_op:
        batch_op.create_check_constraint(
            "ck_proposal_absences_category", "category IN ('vacances', 'postguardia')"
        )


def downgrade() -> None:
    with op.batch_alter_table("proposal_absences") as batch_op:
        batch_op.drop_constraint("ck_proposal_absences_category", type_="check")
    with op.batch_alter_table("absences") as batch_op:
        batch_op.drop_constraint("ck_absences_category", type_="check")
    op.drop_table("member_status_changes")
    with op.batch_alter_table("members") as batch_op:
        batch_op.drop_column("is_active")
