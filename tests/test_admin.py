import json
import sqlite3
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from test_auth_accounts import isolated_client, request_and_approve

from pinendar.config import Settings
from pinendar.infrastructure.auth_store import AuthStore
from pinendar.infrastructure.migrations import migrate
from pinendar.main import create_app


def login_admin(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin-password"},
    )
    assert response.status_code == 200


def test_signup_waits_for_admin_approval(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        requested = client.post(
            "/api/v1/auth/signup",
            json={"username": "alice", "password": "alice-password"},
        )
        assert requested.status_code == 202
        assert requested.json()["status"] == "pending"
        assert requested.json()["recoveryCode"]
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        ).status_code == 401

        login_admin(client)
        overview = client.get("/api/v1/admin")
        assert overview.status_code == 200
        assert overview.json()["accounts"][0]["isAdmin"] is True
        pending = overview.json()["signupRequests"][0]
        assert pending["username"] == "alice"
        assert client.post(
            f"/api/v1/admin/signup-requests/{pending['id']}/approve"
        ).status_code == 200

        client.post("/api/v1/auth/logout")
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        ).status_code == 200


def test_non_admin_cannot_use_admin_api(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        request_and_approve(client, "alice", "alice-password")
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        response = client.get("/api/v1/admin")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"


def test_rejected_signup_can_apply_again(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        first = client.post(
            "/api/v1/auth/signup",
            json={"username": "alice", "password": "alice-password"},
        ).json()
        login_admin(client)
        request_id = client.get("/api/v1/admin").json()["signupRequests"][0]["id"]
        assert client.post(
            f"/api/v1/admin/signup-requests/{request_id}/reject"
        ).status_code == 200
        client.post("/api/v1/auth/logout")

        second = client.post(
            "/api/v1/auth/signup",
            json={"username": "alice", "password": "different-password"},
        )
        assert second.status_code == 202
        assert second.json()["recoveryCode"] != first["recoveryCode"]


def test_signup_requests_are_rate_limited_by_client(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        for index in range(5):
            response = client.post(
                "/api/v1/auth/signup",
                headers={"cf-connecting-ip": "203.0.113.10"},
                json={"username": f"user-{index}", "password": "valid-password"},
            )
            assert response.status_code == 202
        limited = client.post(
            "/api/v1/auth/signup",
            headers={"cf-connecting-ip": "203.0.113.10"},
            json={"username": "user-final", "password": "valid-password"},
        )
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "SIGNUP_RATE_LIMITED"


def test_admin_cannot_create_an_account_over_a_pending_request(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        client.post(
            "/api/v1/auth/signup",
            json={"username": "alice", "password": "alice-password"},
        )
        login_admin(client)
        response = client.post(
            "/api/v1/admin/accounts",
            json={"username": "alice", "password": "other-password"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "USERNAME_RESERVED"


def test_admin_can_create_edit_disable_and_delete_accounts(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        login_admin(client)
        created = client.post(
            "/api/v1/admin/accounts",
            json={"username": "alice", "password": "alice-password"},
        )
        assert created.status_code == 201
        assert created.json()["recoveryCode"]
        account_id = created.json()["id"]
        environment_path = client.app.state.auth_store.get_account(account_id).environment_path

        updated = client.patch(
            f"/api/v1/admin/accounts/{account_id}",
            json={"username": "alicia", "password": "new-password", "disabled": True},
        )
        assert updated.status_code == 200
        client.post("/api/v1/auth/logout")
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alicia", "password": "new-password"},
        ).status_code == 401

        login_admin(client)
        assert client.patch(
            f"/api/v1/admin/accounts/{account_id}", json={"disabled": False}
        ).status_code == 200
        assert client.delete(f"/api/v1/admin/accounts/{account_id}").status_code == 204
        assert not environment_path.exists()


def test_admin_account_is_protected(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        login_admin(client)
        admin = next(
            item for item in client.get("/api/v1/admin").json()["accounts"] if item["isAdmin"]
        )
        assert client.delete(f"/api/v1/admin/accounts/{admin['id']}").status_code == 403
        assert client.patch(
            f"/api/v1/admin/accounts/{admin['id']}", json={"disabled": True}
        ).status_code == 403


def test_admin_backup_contains_auth_and_all_account_databases(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        login_admin(client)
        client.post(
            "/api/v1/admin/accounts",
            json={"username": "alice", "password": "alice-password"},
        )
        created = client.post("/api/v1/admin/backups")
        assert created.status_code == 201
        backup_path = tmp_path / "backups" / created.json()["name"]
        assert backup_path.is_file()

        with zipfile.ZipFile(backup_path) as archive:
            names = archive.namelist()
            assert "auth.sqlite" in names
            assert len([name for name in names if name.startswith("accounts/")]) == 2
            metadata = json.loads(archive.read("metadata.json"))
            assert {item["username"] for item in metadata["accounts"]} == {"admin", "alice"}

        downloaded = client.get(created.json()["downloadUrl"])
        assert downloaded.status_code == 200
        assert downloaded.headers["content-type"] == "application/zip"


def test_existing_auth_database_adds_admin_column(tmp_path: Path) -> None:
    path = tmp_path / "auth.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE accounts (
                id VARCHAR PRIMARY KEY,
                username VARCHAR(40) UNIQUE NOT NULL,
                password_hash VARCHAR NOT NULL,
                recovery_hash VARCHAR NOT NULL,
                environment_path VARCHAR UNIQUE NOT NULL,
                session_version INTEGER NOT NULL,
                disabled BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
    store = AuthStore(path)
    store.create_schema()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(accounts)")}
    assert "is_admin" in columns
    store.engine.dispose()


def test_admin_can_create_account_when_runtime_migrations_are_disabled(tmp_path: Path) -> None:
    database_path = tmp_path / "pinendar.sqlite"
    auth_path = tmp_path / "auth.sqlite"
    migrate(database_path)
    store = AuthStore(auth_path)
    store.create_schema()
    store.create_account(
        "admin", "admin-password", database_path, is_admin=True
    )
    store.engine.dispose()
    settings = Settings(
        database_path=database_path,
        auth_database_path=auth_path,
        environments_dir=tmp_path / "environments",
        backups_dir=tmp_path / "backups",
        hospital_catalog_dir=Path("data/hospitals").resolve(),
        static_dir=Path("public").resolve(),
        session_secret="test-session-secret-with-enough-entropy",
        migrate_on_startup=False,
        run_job_dispatcher=False,
        scheduler_process_pool=False,
    )
    with TestClient(create_app(settings)) as client:
        login_admin(client)
        created = client.post(
            "/api/v1/admin/accounts",
            json={"username": "alice", "password": "alice-password"},
        )
        assert created.status_code == 201
        client.post("/api/v1/auth/logout")
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        ).status_code == 200
        assert client.get("/api/v1/bootstrap").status_code == 200
