"""guard transfer history

Revision ID: j0e54a7f1d43
Revises: c2f4a6b8d0e1
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j0e54a7f1d43"
down_revision: str | Sequence[str] | None = "c2f4a6b8d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guard_transfers",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("operation_kind", sa.String(), nullable=False),
        sa.Column("proposal_id", sa.String(), nullable=False),
        sa.Column("guard_date", sa.Date(), nullable=False),
        sa.Column("from_member_id", sa.String(), nullable=True),
        sa.Column("to_member_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("impact_json", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "from_member_id IS NOT NULL OR to_member_id IS NOT NULL",
            name="ck_guard_transfers_has_internal_party",
        ),
        sa.CheckConstraint(
            "operation_kind IN ('cession', 'exchange')",
            name="ck_guard_transfers_operation_kind",
        ),
        sa.ForeignKeyConstraint(["from_member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_guard_transfers_proposal_created",
        "guard_transfers",
        ["proposal_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_guard_transfers_proposal_created", table_name="guard_transfers")
    op.drop_table("guard_transfers")
