import sqlite3
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from pinendar.infrastructure.migrations import migrate


def table_names(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with sqlite3.connect(path) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def test_migrate_uses_explicit_path_when_default_environment_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_database = tmp_path / "default.sqlite"
    account_database = tmp_path / "account.sqlite"
    monkeypatch.setenv("PINENDAR_DATABASE_PATH", str(default_database))

    migrate(account_database)

    assert "settings" in table_names(account_database)
    assert table_names(default_database) == set()


def test_multiple_guard_migration_preserves_rows_and_changes_the_unique_key(
    tmp_path: Path,
) -> None:
    database = tmp_path / "previous.sqlite"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "p6e10f4a5b23")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO guards (id, generation_job_id, member_id, date) VALUES (?, NULL, ?, ?)",
            ("existing-guard", "member-a", "2027-01-04"),
        )

    migrate(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT id, member_id, date FROM guards"
        ).fetchall() == [("existing-guard", "member-a", "2027-01-04")]
        connection.execute(
            "INSERT INTO guards (id, generation_job_id, member_id, date) VALUES (?, NULL, ?, ?)",
            ("second-guard", "member-b", "2027-01-04"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO guards (id, generation_job_id, member_id, date) VALUES (?, NULL, ?, ?)",
                ("duplicate-guard", "member-a", "2027-01-04"),
            )
