"""exact generation dates

Revision ID: k1f65b8a2e54
Revises: j0e54a7f1d43
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k1f65b8a2e54"
down_revision: str | Sequence[str] | None = "j0e54a7f1d43"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("proposals", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("proposals", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("generation_jobs", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("generation_jobs", sa.Column("end_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_jobs", "end_date")
    op.drop_column("generation_jobs", "start_date")
    op.drop_column("proposals", "end_date")
    op.drop_column("proposals", "start_date")
