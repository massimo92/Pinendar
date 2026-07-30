"""hospital short names

Revision ID: n4c98d2e3f01
Revises: m3b87c1d2e90
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "n4c98d2e3f01"
down_revision: str | Sequence[str] | None = "m3b87c1d2e90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("hospitals") as batch_op:
        batch_op.add_column(sa.Column("short_name", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hospitals") as batch_op:
        batch_op.drop_column("short_name")
