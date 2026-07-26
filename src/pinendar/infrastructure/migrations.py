from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command


def tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def current_revisions(path: Path, existing: set[str]) -> set[str]:
    if "alembic_version" not in existing:
        return set()
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}


def backup_pending_migration(path: Path, config: Config) -> Path | None:
    existing = tables(path)
    if not existing:
        return None
    heads = set(ScriptDirectory.from_config(config).get_heads())
    if current_revisions(path, existing) == heads:
        return None
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    label = "pre-fastapi" if "app_state" in existing and "settings" not in existing else "pre-migration"
    backup_path = path.with_name(f"{path.stem}.{label}-{timestamp}{path.suffix}")
    with sqlite3.connect(path) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
    return backup_path


def migrate(path: Path) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    project_root = Path.cwd()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    backup = backup_pending_migration(path, config)
    command.upgrade(config, "head")
    return backup
