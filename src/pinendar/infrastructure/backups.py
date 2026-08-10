from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from pinendar.infrastructure.auth_store import AccountSummary, AuthStore


@dataclass(frozen=True)
class BackupSummary:
    name: str
    size: int
    created_at: datetime


class BackupManager:
    def __init__(self, backup_dir: Path, auth_store: AuthStore):
        self.backup_dir = backup_dir.resolve()
        self.auth_store = auth_store

    def create(self) -> BackupSummary:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        name = f"pinendar-backup-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.zip"
        final_path = self.backup_dir / name
        temporary_archive = self.backup_dir / f".{name}.tmp"
        accounts = self.auth_store.list_accounts()

        try:
            with tempfile.TemporaryDirectory(dir=self.backup_dir) as temporary_dir:
                staging = Path(temporary_dir)
                self._copy_sqlite(self.auth_store.path, staging / "auth.sqlite")
                account_files: list[dict[str, object]] = []
                for account in accounts:
                    destination = staging / "accounts" / f"{account.username}-{account.id}.sqlite"
                    self._copy_sqlite(account.environment_path, destination)
                    account_files.append(self._account_metadata(account, destination.name))
                (staging / "metadata.json").write_text(
                    json.dumps(
                        {
                            "createdAt": now.isoformat(),
                            "accounts": account_files,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                with zipfile.ZipFile(temporary_archive, "w", zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(staging.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(staging))
            os.replace(temporary_archive, final_path)
        finally:
            temporary_archive.unlink(missing_ok=True)
        return self._summary(final_path)

    def list(self) -> list[BackupSummary]:
        if not self.backup_dir.exists():
            return []
        return sorted(
            (self._summary(path) for path in self.backup_dir.glob("pinendar-backup-*.zip")),
            key=lambda item: item.created_at,
            reverse=True,
        )

    def resolve(self, name: str) -> Path | None:
        if Path(name).name != name or not name.startswith("pinendar-backup-") or not name.endswith(".zip"):
            return None
        path = (self.backup_dir / name).resolve()
        if path.parent != self.backup_dir or not path.is_file():
            return None
        return path

    @staticmethod
    def _copy_sqlite(source: Path, destination: Path) -> None:
        if not source.is_file():
            raise FileNotFoundError(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_connection:
            with sqlite3.connect(destination) as destination_connection:
                source_connection.backup(destination_connection)

    @staticmethod
    def _account_metadata(account: AccountSummary, filename: str) -> dict[str, object]:
        values = asdict(account)
        return {
            "id": values["id"],
            "username": values["username"],
            "disabled": values["disabled"],
            "isAdmin": values["is_admin"],
            "createdAt": account.created_at.isoformat(),
            "lastActiveAt": account.last_active_at.isoformat() if account.last_active_at else None,
            "file": f"accounts/{filename}",
        }

    @staticmethod
    def _summary(path: Path) -> BackupSummary:
        stat = path.stat()
        return BackupSummary(
            name=path.name,
            size=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime, UTC),
        )
