import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from pinendar.config import Settings
from pinendar.main import create_app


def test_legacy_app_state_is_imported_without_losing_identifiers(tmp_path: Path) -> None:
    database_path = tmp_path / "pinendar.sqlite"
    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT)")
    state = {
        "language": "es",
        "team": [
            {
                "id": "member-1",
                "name": "Persona Legacy",
                "email": "legacy@test.invalid",
                "color": "hsl(10 58% 78%)",
                "active": True,
                "availableDays": [1, 2],
                "teleDays": [],
                "allowedTypes": ["agenda-1"],
                "managementQuota": 0,
                "fixedRules": [],
                "absences": [],
            }
        ],
        "archivedTeam": [],
        "agendas": [
            {
                "id": "agenda-1",
                "name": "Agenda Legacy",
                "hospitalId": "170010",
                "telematic": False,
                "color": "hsl(20 90% 56%)",
            }
        ],
        "archivedAgendas": [],
        "coverage": {"1": {"agenda-1": 1}, "2": {"agenda-1": 1}, "3": {}, "4": {}, "5": {}},
        "hospitals": [{"id": "hospital-1", "catalogId": "170010"}],
        "holidays": ["2027-01-06"],
        "guards": [],
        "published": [],
        "draft": {
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "generatedAt": "2026-12-01T10:00:00Z",
            "assignments": [{"id": "assignment-1", "date": "2027-01-04", "memberId": "member-1", "type": "agenda-1"}],
            "unfilled": [],
            "conditions": {"guards": [], "absences": []},
        },
    }
    connection.execute("INSERT INTO app_state VALUES (?, ?, CURRENT_TIMESTAMP)", ("state", json.dumps(state)))
    connection.commit()
    connection.close()

    settings = Settings(
        database_path=database_path,
        auth_database_path=tmp_path / "auth.sqlite",
        environments_dir=tmp_path / "environments",
        hospital_catalog_dir=Path("data/hospitals").resolve(),
        static_dir=Path("public").resolve(),
        bootstrap_username="admin",
        bootstrap_password="test-password",
        session_secret="test-session-secret-with-enough-entropy",
        run_job_dispatcher=False,
        scheduler_process_pool=False,
    )
    with TestClient(create_app(settings)) as client:
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "test-password"},
        ).status_code == 200
        migrated = client.get("/api/v1/bootstrap").json()

    assert migrated["language"] == "es"
    assert migrated["team"][0]["id"] == "member-1"
    assert migrated["agendas"][0]["id"] == "agenda-1"
    assert migrated["agendas"][0]["shift"] == "morning"
    assert migrated["draft"]["assignments"][0]["id"] == "assignment-1"
    assert len(list(tmp_path.glob("pinendar.pre-fastapi-*.sqlite"))) == 1

    with TestClient(create_app(settings)):
        pass
    assert len(list(tmp_path.glob("pinendar.pre-*.sqlite"))) == 1
