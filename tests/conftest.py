from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pinendar.config import Settings
from pinendar.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        database_path=tmp_path / "pinendar.sqlite",
        auth_database_path=tmp_path / "auth.sqlite",
        environments_dir=tmp_path / "environments",
        hospital_catalog_dir=Path("data/hospitals").resolve(),
        static_dir=Path("public").resolve(),
        bootstrap_username="admin",
        bootstrap_password="test-password",
        session_secret="test-session-secret-with-enough-entropy",
        run_job_dispatcher=False,
        scheduler_process_pool=False,
        scheduler_time_limit_seconds=5,
        scheduler_workers=1,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def authenticated_client(client: TestClient) -> TestClient:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-password"},
    )
    assert response.status_code == 200
    return client
