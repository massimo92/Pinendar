"""planning event deferred origin

Revision ID: p6e10f4a5b23
Revises: o5d09e3f4a12
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p6e10f4a5b23"
down_revision: str | Sequence[str] | None = "o5d09e3f4a12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("planning_events") as batch_op:
        batch_op.add_column(sa.Column("deferred_origin_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("planning_events") as batch_op:
        batch_op.drop_column("deferred_origin_date")
