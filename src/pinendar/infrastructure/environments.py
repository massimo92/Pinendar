from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from pinendar.application.jobs import JobDispatcher
from pinendar.application.state import initialize_database
from pinendar.config import Settings
from pinendar.infrastructure.catalog import HospitalCatalog
from pinendar.infrastructure.database import Database
from pinendar.infrastructure.migrations import migrate


@dataclass
class Environment:
    database: Database
    dispatcher: JobDispatcher


class EnvironmentRegistry:
    def __init__(self, settings: Settings, catalog: HospitalCatalog):
        self.settings = settings
        self.catalog = catalog
        self._environments: dict[Path, Environment] = {}
        self._lock = threading.Lock()

    def get(self, path: Path) -> Environment:
        resolved = path.resolve()
        with self._lock:
            existing = self._environments.get(resolved)
            if existing:
                return existing
            if self.settings.migrate_on_startup:
                migrate(resolved)
            database = Database(resolved)
            initialize_database(
                database,
                self.catalog,
                seed_example_data=resolved == self.settings.database_path.resolve(),
            )
            dispatcher = JobDispatcher(database, process_pool=self.settings.scheduler_process_pool)
            if self.settings.run_job_dispatcher:
                dispatcher.start()
            environment = Environment(database=database, dispatcher=dispatcher)
            self._environments[resolved] = environment
            return environment

    def create(self, path: Path) -> Environment:
        resolved = path.resolve()
        if not self.manages(resolved) or resolved == self.settings.database_path.resolve():
            raise ValueError("Account environments must be inside the configured environments directory")
        migrate(resolved)
        return self.get(resolved)

    def manages(self, path: Path) -> bool:
        resolved = path.resolve()
        return resolved == self.settings.database_path.resolve() or resolved.is_relative_to(
            self.settings.environments_dir.resolve()
        )

    def stop_all(self) -> None:
        with self._lock:
            environments = list(self._environments.values())
            self._environments.clear()
        for environment in environments:
            environment.dispatcher.stop()
            environment.database.engine.dispose()

    def delete(self, path: Path) -> bool:
        resolved = path.resolve()
        if not self.manages(resolved):
            return False

        with self._lock:
            environment = self._environments.pop(resolved, None)
        if environment:
            environment.dispatcher.stop()
            environment.database.engine.dispose()

        for candidate in (resolved, Path(f"{resolved}-wal"), Path(f"{resolved}-shm")):
            candidate.unlink(missing_ok=True)
        return True
