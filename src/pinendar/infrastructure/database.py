from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from pinendar.infrastructure.models import Base


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False}, future=True)
        event.listen(self.engine, "connect", self._configure_sqlite)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    @staticmethod
    def _configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def sessions(self) -> Iterator[Session]:
        with self.session_factory() as session:
            yield session

    def ready(self) -> bool:
        with self.engine.connect() as connection:
            result = connection.execute(text("SELECT 1")).scalar_one()
            return bool(result == 1)


def table_exists(engine: Engine, name: str) -> bool:
    with engine.connect() as connection:
        result = connection.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"), {"name": name}
        ).first()
    return result is not None
