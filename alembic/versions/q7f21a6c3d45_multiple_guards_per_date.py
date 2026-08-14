"""allow multiple guards per date

Revision ID: q7f21a6c3d45
Revises: p6e10f4a5b23
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "q7f21a6c3d45"
down_revision: str | Sequence[str] | None = "p6e10f4a5b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "guards_multiple",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("generation_job_id", sa.String()),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_job_id"], ["generation_jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "date", "member_id", name="uq_guards_date_member_id"
        ),
    )
    op.execute(
        """
        INSERT INTO guards_multiple (id, generation_job_id, member_id, date)
        SELECT id, generation_job_id, member_id, date FROM guards
        """
    )
    op.drop_table("guards")
    op.rename_table("guards_multiple", "guards")


def downgrade() -> None:
    raise RuntimeError(
        "Multiple guards per date is intentionally irreversible; restore the automatic pre-migration backup."
    )
