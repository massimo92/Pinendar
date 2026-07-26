"""member agenda preferences

Revision ID: i9d43f6e0c32
Revises: h8c32e5d9b21
Create Date: 2026-07-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i9d43f6e0c32"
down_revision: str | Sequence[str] | None = "h8c32e5d9b21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "member_agenda_preferences",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("agenda_id", sa.String(), nullable=False),
        sa.Column("preference", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "preference IN (-1, 1)", name="ck_member_agenda_preferences_value"
        ),
        sa.ForeignKeyConstraint(["agenda_id"], ["agendas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("member_id", "agenda_id"),
    )


def downgrade() -> None:
    op.drop_table("member_agenda_preferences")
