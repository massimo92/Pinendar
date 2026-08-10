import sqlite3
from pathlib import Path

import pytest

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
