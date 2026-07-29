"""expressive fixed rules

Revision ID: m3b87c1d2e90
Revises: l2a76c9e4f10
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m3b87c1d2e90"
down_revision: str | Sequence[str] | None = "l2a76c9e4f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.rename_table("fixed_rules", "fixed_rules_legacy")
    op.create_table(
        "fixed_rules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("required_mode", sa.String(length=3), nullable=False, server_default="all"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("member_id", "weekday"),
        sa.CheckConstraint("required_mode IN ('all', 'one')", name="ck_fixed_rules_required_mode"),
    )
    op.create_table(
        "fixed_rule_agendas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_id", sa.String(), nullable=False),
        sa.Column("agenda_id", sa.String(), nullable=False),
        sa.Column("effect", sa.String(length=9), nullable=False),
        sa.ForeignKeyConstraint(["rule_id"], ["fixed_rules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agenda_id"], ["agendas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("rule_id", "agenda_id"),
        sa.CheckConstraint(
            "effect IN ('required', 'forbidden')",
            name="ck_fixed_rule_agendas_effect",
        ),
    )
    op.execute(
        """
        INSERT INTO fixed_rules (id, member_id, weekday, required_mode)
        SELECT id, member_id, weekday, 'all'
        FROM fixed_rules_legacy
        """
    )
    op.execute(
        """
        INSERT INTO fixed_rule_agendas (rule_id, agenda_id, effect)
        SELECT id, agenda_id, 'required'
        FROM fixed_rules_legacy
        """
    )
    op.drop_table("fixed_rules_legacy")


def downgrade() -> None:
    op.create_table(
        "fixed_rules_legacy",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("agenda_id", sa.String(), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agenda_id"], ["agendas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("member_id", "weekday"),
    )
    op.execute(
        """
        INSERT INTO fixed_rules_legacy (id, member_id, agenda_id, weekday)
        SELECT fixed_rules.id, fixed_rules.member_id, MIN(fixed_rule_agendas.agenda_id),
               fixed_rules.weekday
        FROM fixed_rules
        JOIN fixed_rule_agendas
          ON fixed_rule_agendas.rule_id = fixed_rules.id
         AND fixed_rule_agendas.effect = 'required'
        GROUP BY fixed_rules.id, fixed_rules.member_id, fixed_rules.weekday
        """
    )
    op.drop_table("fixed_rule_agendas")
    op.drop_table("fixed_rules")
    op.rename_table("fixed_rules_legacy", "fixed_rules")
