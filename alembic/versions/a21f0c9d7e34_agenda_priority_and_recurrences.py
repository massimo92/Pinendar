"""agenda priority and recurring demand

Revision ID: a21f0c9d7e34
Revises: 803ac0e334e4
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a21f0c9d7e34"
down_revision: str | Sequence[str] | None = "803ac0e334e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="5"))

    priorities = {
        "tac_urg": 1,
        "eco_urg": 1,
        "tac_amb": 2,
        "reso": 2,
        "intervencio": 3,
        "general": 4,
        "telemando": 5,
        "gestio": 6,
        "eco_amb": 7,
        "eco_tec": 7,
    }
    for agenda_id, priority in priorities.items():
        op.execute(
            sa.text("UPDATE agendas SET priority = :priority WHERE id = :agenda_id").bindparams(
                priority=priority, agenda_id=agenda_id
            )
        )

    op.create_table(
        "agenda_recurrences",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("agenda_id", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("slots", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["agenda_id"], ["agendas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agenda_id", "ordinal", "weekday"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO agenda_recurrences (id, agenda_id, ordinal, weekday, slots)
            SELECT 'default-intervencio-third-monday', id, 3, 1, 1
            FROM agendas WHERE id = 'intervencio'
            """
        )
    )


def downgrade() -> None:
    op.drop_table("agenda_recurrences")
    with op.batch_alter_table("agendas") as batch_op:
        batch_op.drop_column("priority")
