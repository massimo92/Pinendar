"""member aliases for guard import matching

Revision ID: bf1e2d3c4a5b
Revises: c8e2ab146f90
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bf1e2d3c4a5b"
down_revision: str | Sequence[str] | None = "i9d43f6e0c32"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "member_aliases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("alias", sa.String(), nullable=False),
        sa.Column("normalized_alias", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "normalized_alias"),
    )
    op.create_index("ix_member_aliases_normalized_alias", "member_aliases", ["normalized_alias"])


def downgrade() -> None:
    op.drop_index("ix_member_aliases_normalized_alias", table_name="member_aliases")
    op.drop_table("member_aliases")
