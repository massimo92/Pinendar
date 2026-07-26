"""event based calendar

Revision ID: l2a76c9e4f10
Revises: k1f65b8a2e54
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l2a76c9e4f10"
down_revision: str | Sequence[str] | None = "k1f65b8a2e54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the old proposal-to-job relation just long enough to attach migrated
    # events to their originating generation run.
    op.create_table(
        "_proposal_job_map",
        sa.Column("proposal_id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=False),
    )
    op.execute(
        """
        INSERT INTO _proposal_job_map (proposal_id, job_id)
        SELECT proposal_id, id
        FROM (
            SELECT proposal_id, id,
                   ROW_NUMBER() OVER (
                       PARTITION BY proposal_id
                       ORDER BY created_at DESC, id DESC
                   ) AS position
            FROM generation_jobs
            WHERE proposal_id IS NOT NULL
        )
        WHERE position = 1
        """
    )

    op.create_table(
        "generation_jobs_v2",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("start_month", sa.String(length=7), nullable=False),
        sa.Column("end_month", sa.String(length=7), nullable=False),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("input_revision", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("error_code", sa.String()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.execute(
        """
        INSERT INTO generation_jobs_v2
        SELECT id, status, start_month, end_month, start_date, end_date,
               input_revision, input_snapshot, result_json, error_code,
               error_message, created_at, started_at, completed_at
        FROM generation_jobs
        """
    )
    op.drop_index("ix_jobs_status", table_name="generation_jobs")
    op.drop_table("generation_jobs")
    op.rename_table("generation_jobs_v2", "generation_jobs")
    op.create_index("ix_jobs_status", "generation_jobs", ["status"])

    op.create_table(
        "planning_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("generation_job_id", sa.String()),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("agenda_id", sa.String()),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("load_percentage", sa.Integer(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("fixed", sa.Boolean(), nullable=False),
        sa.Column("extra", sa.Boolean(), nullable=False),
        sa.Column("manually_modified", sa.Boolean(), nullable=False),
        sa.Column("management", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agenda_id"], ["agendas.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("load_percentage IN (0, 50, 100)", name="ck_planning_events_load"),
    )
    op.create_index("ix_planning_events_date", "planning_events", ["date"])

    op.create_table(
        "vacancies_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("generation_job_id", sa.String()),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("agenda_id", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agenda_id"], ["agendas.id"], ondelete="RESTRICT"),
    )

    # A date belongs to the newest generated proposal that contains calendar
    # content for that date. This preserves disjoint historical months while
    # discarding superseded versions of an overlapping day.
    authoritative = """
        WITH content AS (
            SELECT proposal_id, date FROM assignments
            UNION
            SELECT proposal_id, date FROM vacancies
        ),
        ranked AS (
            SELECT content.date, content.proposal_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY content.date
                       ORDER BY proposals.generated_at DESC,
                                CASE proposals.status WHEN 'current' THEN 1 ELSE 0 END DESC,
                                proposals.id DESC
                   ) AS position
            FROM content
            JOIN proposals ON proposals.id = content.proposal_id
        )
    """
    op.execute(
        authoritative
        + """
        INSERT INTO planning_events (
            id, generation_job_id, date, member_id, agenda_id, kind, load_percentage,
            locked, fixed, extra, manually_modified, management
        )
        SELECT assignments.id, _proposal_job_map.job_id, assignments.date,
               assignments.member_id, assignments.agenda_id, assignments.kind,
               CASE
                   WHEN assignments.kind = 'no_assignment' THEN 0
                   WHEN assignments.kind = 'management' OR assignments.management = 1 THEN 100
                   ELSE COALESCE(agendas.load_percentage, 100)
               END,
               assignments.locked, assignments.fixed, assignments.extra,
               CASE WHEN assignments.locked = 1 AND assignments.fixed = 0 THEN 1 ELSE 0 END,
               assignments.management
        FROM assignments
        JOIN ranked ON ranked.date = assignments.date
                   AND ranked.proposal_id = assignments.proposal_id
                   AND ranked.position = 1
        LEFT JOIN _proposal_job_map
               ON _proposal_job_map.proposal_id = assignments.proposal_id
        LEFT JOIN agendas ON agendas.id = assignments.agenda_id
        """
    )
    op.execute(
        authoritative
        + """
        INSERT INTO vacancies_v2 (id, generation_job_id, date, agenda_id)
        SELECT vacancies.id, _proposal_job_map.job_id, vacancies.date,
               vacancies.agenda_id
        FROM vacancies
        JOIN ranked ON ranked.date = vacancies.date
                   AND ranked.proposal_id = vacancies.proposal_id
                   AND ranked.position = 1
        LEFT JOIN _proposal_job_map
               ON _proposal_job_map.proposal_id = vacancies.proposal_id
        """
    )

    op.create_table(
        "guards_v2",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("generation_job_id", sa.String()),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False, unique=True),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
    )
    op.execute(
        """
        INSERT INTO guards_v2 (id, generation_job_id, member_id, date)
        SELECT id, NULL, member_id, date FROM guards
        """
    )
    op.execute(
        """
        INSERT OR REPLACE INTO guards_v2 (id, generation_job_id, member_id, date)
        SELECT id, job_id, member_id, date
        FROM (
            SELECT proposal_guards.id, _proposal_job_map.job_id,
                   proposal_guards.member_id, proposal_guards.date,
                   ROW_NUMBER() OVER (
                       PARTITION BY proposal_guards.date
                       ORDER BY proposals.generated_at DESC,
                                CASE proposals.status WHEN 'current' THEN 1 ELSE 0 END DESC,
                                proposals.id DESC
                   ) AS position
            FROM proposal_guards
            JOIN proposals ON proposals.id = proposal_guards.proposal_id
            LEFT JOIN _proposal_job_map
                   ON _proposal_job_map.proposal_id = proposal_guards.proposal_id
        )
        WHERE position = 1
        """
    )

    op.create_table(
        "absences_v2",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("generation_job_id", sa.String()),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("end", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.CheckConstraint("category IN ('vacances', 'postguardia')", name="ck_absences_category"),
        sa.UniqueConstraint("member_id", "category", "start", "end"),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], ondelete="CASCADE"),
    )
    absence_islands = """
        WITH RECURSIVE sources AS (
            SELECT absences.id, NULL AS job_id, absences.member_id,
                   absences.category, absences.start, absences.end AS end_date,
                   absences.notes, 1 AS independent,
                   NULL AS generated_at, '' AS proposal_id
            FROM absences
            UNION ALL
            SELECT proposal_absences.id, _proposal_job_map.job_id,
                   proposal_absences.member_id, proposal_absences.category,
                   proposal_absences.start, proposal_absences.end AS end_date,
                   '' AS notes, 0 AS independent,
                   proposals.generated_at, proposals.id AS proposal_id
            FROM proposal_absences
            JOIN proposals ON proposals.id = proposal_absences.proposal_id
            LEFT JOIN _proposal_job_map
                   ON _proposal_job_map.proposal_id = proposal_absences.proposal_id
        ),
        expanded AS (
            SELECT id, job_id, member_id, category, start AS day, end_date,
                   notes, independent, generated_at, proposal_id
            FROM sources
            UNION ALL
            SELECT id, job_id, member_id, category, date(day, '+1 day'),
                   end_date, notes, independent, generated_at, proposal_id
            FROM expanded
            WHERE day < end_date
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY member_id, category, day
                       ORDER BY independent DESC, generated_at DESC,
                                proposal_id DESC, id DESC
                   ) AS position
            FROM expanded
        ),
        chosen AS (
            SELECT * FROM ranked WHERE position = 1
        ),
        grouped AS (
            SELECT *,
                   julianday(day) - ROW_NUMBER() OVER (
                       PARTITION BY member_id, category ORDER BY day
                   ) AS island
            FROM chosen
        )
    """
    op.execute(
        absence_islands
        + """
        INSERT INTO absences_v2 (
            id, generation_job_id, member_id, category, start, end, notes
        )
        SELECT MIN(id), MIN(job_id), member_id, category,
               MIN(day), MAX(day), MAX(notes)
        FROM grouped
        GROUP BY member_id, category, island
        """
    )

    op.create_table(
        "guard_transfers_v2",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("operation_kind", sa.String(), nullable=False),
        sa.Column("guard_date", sa.Date(), nullable=False),
        sa.Column("from_member_id", sa.String()),
        sa.Column("to_member_id", sa.String()),
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
        sa.ForeignKeyConstraint(["to_member_id"], ["members.id"], ondelete="RESTRICT"),
    )
    op.execute(
        """
        INSERT INTO guard_transfers_v2 (
            id, operation_id, operation_kind, guard_date, from_member_id,
            to_member_id, created_at, note, impact_json
        )
        SELECT id, operation_id, operation_kind, guard_date, from_member_id,
               to_member_id, created_at, note, impact_json
        FROM guard_transfers
        """
    )

    bind = op.get_bind()
    expected_events = bind.execute(
        sa.text(
            authoritative
            + """
            SELECT COUNT(*)
            FROM assignments
            JOIN ranked ON ranked.date = assignments.date
                       AND ranked.proposal_id = assignments.proposal_id
                       AND ranked.position = 1
            """
        )
    ).scalar_one()
    expected_vacancies = bind.execute(
        sa.text(
            authoritative
            + """
            SELECT COUNT(*)
            FROM vacancies
            JOIN ranked ON ranked.date = vacancies.date
                       AND ranked.proposal_id = vacancies.proposal_id
                       AND ranked.position = 1
            """
        )
    ).scalar_one()
    expected_guards = bind.execute(
        sa.text("SELECT COUNT(DISTINCT date) FROM (SELECT date FROM guards UNION ALL SELECT date FROM proposal_guards)")
    ).scalar_one()
    expected_absences = bind.execute(
        sa.text(
            absence_islands
            + """
            SELECT COUNT(*)
            FROM (
                SELECT 1
                FROM grouped
                GROUP BY member_id, category, island
            )
            """
        )
    ).scalar_one()
    expected_transfers = bind.execute(sa.text("SELECT COUNT(*) FROM guard_transfers")).scalar_one()
    migrated_counts = {
        "events": bind.execute(sa.text("SELECT COUNT(*) FROM planning_events")).scalar_one(),
        "vacancies": bind.execute(sa.text("SELECT COUNT(*) FROM vacancies_v2")).scalar_one(),
        "guards": bind.execute(sa.text("SELECT COUNT(*) FROM guards_v2")).scalar_one(),
        "absences": bind.execute(sa.text("SELECT COUNT(*) FROM absences_v2")).scalar_one(),
        "transfers": bind.execute(sa.text("SELECT COUNT(*) FROM guard_transfers_v2")).scalar_one(),
    }
    expected_counts = {
        "events": expected_events,
        "vacancies": expected_vacancies,
        "guards": expected_guards,
        "absences": expected_absences,
        "transfers": expected_transfers,
    }
    if migrated_counts != expected_counts:
        raise RuntimeError(
            f"Event calendar migration count mismatch: expected {expected_counts}, got {migrated_counts}"
        )

    op.drop_index("ix_guard_transfers_proposal_created", table_name="guard_transfers")
    op.drop_table("guard_transfers")
    op.drop_table("proposal_absences")
    op.drop_table("proposal_guards")
    op.drop_index("ix_assignments_date", table_name="assignments")
    op.drop_table("assignments")
    op.drop_table("vacancies")
    op.drop_table("guards")
    op.drop_table("absences")

    op.rename_table("vacancies_v2", "vacancies")
    op.rename_table("guards_v2", "guards")
    op.rename_table("absences_v2", "absences")
    op.rename_table("guard_transfers_v2", "guard_transfers")
    op.create_index("ix_guard_transfers_created", "guard_transfers", ["created_at"])

    op.drop_index("ix_proposals_status", table_name="proposals")
    op.drop_table("proposals")
    op.drop_table("_proposal_job_map")


def downgrade() -> None:
    raise RuntimeError(
        "The event-based calendar migration is intentionally irreversible; restore the automatic pre-migration backup."
    )
