import sqlite3
from pathlib import Path

from alembic.config import Config

from alembic import command
from pinendar.infrastructure.migrations import migrate


def upgrade_to_legacy_head(path: Path) -> None:
    root = Path.cwd()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "k1f65b8a2e54")


def test_event_migration_keeps_disjoint_months_and_latest_overlapping_date(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite"
    upgrade_to_legacy_head(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO hospitals (id, catalog_id, created_at, name, address, location_known)
            VALUES ('hospital', 'hospital', '2026-01-01', 'Hospital', '', 1)
            """
        )
        connection.execute(
            """
            INSERT INTO members (
                id, name, normalized_name, email, normalized_email, color,
                management_quota, is_active, work_pattern_weeks
            ) VALUES ('member', 'Member', 'member', 'member@test', 'member@test', '#000000', 0, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO agendas (
                id, name, hospital_catalog_id, telematic, color, priority,
                shift, load_percentage
            ) VALUES ('agenda', 'Agenda', 'hospital', 0, '#000000', 1, 'morning', 100)
            """
        )
        connection.execute(
            """
            INSERT INTO fixed_rules (id, member_id, agenda_id, weekday)
            VALUES ('legacy-rule', 'member', 'agenda', 1)
            """
        )
        proposals = [
            ("august", "historical", "2026-08", "2026-08", "2026-08-01 10:00:00"),
            ("september-old", "historical", "2026-09", "2026-09", "2026-09-01 10:00:00"),
            ("september-new", "current", "2026-09", "2026-09", "2026-09-02 10:00:00"),
        ]
        connection.executemany(
            """
            INSERT INTO proposals (
                id, status, start_month, end_month, generated_at,
                input_revision, engine, engine_version, metadata_json
            ) VALUES (?, ?, ?, ?, ?, 1, 'cp-sat', '1', '{}')
            """,
            proposals,
        )
        for proposal_id, *_ in proposals:
            connection.execute(
                """
                INSERT INTO generation_jobs (
                    id, status, start_month, end_month, input_revision,
                    input_snapshot, proposal_id, created_at
                )
                SELECT 'job-' || id, 'succeeded', start_month, end_month, 1, '{}', id, generated_at
                FROM proposals WHERE id = ?
                """,
                (proposal_id,),
            )
        connection.executemany(
            """
            INSERT INTO assignments (
                id, proposal_id, date, member_id, agenda_id, kind,
                locked, fixed, extra, management
            ) VALUES (?, ?, ?, 'member', 'agenda', 'assigned', ?, 0, 0, 0)
            """,
            [
                ("august-event", "august", "2026-08-04", 0),
                ("september-old-event", "september-old", "2026-09-08", 0),
                ("september-new-event", "september-new", "2026-09-08", 1),
            ],
        )
        connection.executemany(
            "INSERT INTO vacancies (proposal_id, date, agenda_id) VALUES (?, ?, 'agenda')",
            [
                ("august", "2026-08-05"),
                ("september-old", "2026-09-09"),
                ("september-new", "2026-09-09"),
            ],
        )
        connection.executemany(
            "INSERT INTO proposal_guards (id, proposal_id, member_id, date) VALUES (?, ?, 'member', ?)",
            [
                ("august-guard", "august", "2026-08-03"),
                ("old-guard", "september-old", "2026-09-07"),
                ("new-guard", "september-new", "2026-09-07"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO proposal_absences (
                id, proposal_id, member_id, category, start, end
            ) VALUES (?, ?, 'member', 'vacances', ?, ?)
            """,
            [
                ("absence-a", "august", "2026-08-10", "2026-08-10"),
                ("absence-b", "august", "2026-08-11", "2026-08-12"),
            ],
        )
        connection.execute(
            """
            INSERT INTO guard_transfers (
                id, operation_id, operation_kind, proposal_id, guard_date,
                from_member_id, to_member_id, created_at, note, impact_json
            ) VALUES (
                'transfer', 'operation', 'cession', 'august', '2026-08-03',
                'member', NULL, '2026-08-03 12:00:00', '', '{}'
            )
            """
        )

    backup = migrate(database_path)

    assert backup is not None and backup.exists()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "p6e10f4a5b23",
        )
        assert "deferred_origin_date" in {
            row[1] for row in connection.execute("PRAGMA table_info(planning_events)")
        }
        assert "short_name" in {
            row[1] for row in connection.execute("PRAGMA table_info(hospitals)")
        }
        assert connection.execute(
            "SELECT id FROM planning_events ORDER BY date"
        ).fetchall() == [("august-event",), ("september-new-event",)]
        assert connection.execute(
            "SELECT date FROM vacancies ORDER BY date"
        ).fetchall() == [("2026-08-05",), ("2026-09-09",)]
        assert connection.execute(
            "SELECT id, date FROM guards ORDER BY date"
        ).fetchall() == [
            ("august-guard", "2026-08-03"),
            ("new-guard", "2026-09-07"),
        ]
        assert connection.execute("SELECT id FROM guard_transfers").fetchall() == [
            ("transfer",)
        ]
        assert connection.execute(
            "SELECT id, start, end FROM absences"
        ).fetchall() == [("absence-a", "2026-08-10", "2026-08-12")]
        assert connection.execute(
            "SELECT id, member_id, weekday, required_mode FROM fixed_rules"
        ).fetchall() == [("legacy-rule", "member", 1, "all")]
        assert connection.execute(
            "SELECT rule_id, agenda_id, effect FROM fixed_rule_agendas"
        ).fetchall() == [("legacy-rule", "agenda", "required")]
        remaining_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "proposals" not in remaining_tables
        assert "proposal_guards" not in remaining_tables
        assert "proposal_absences" not in remaining_tables
