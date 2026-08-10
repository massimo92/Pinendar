from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from pinendar.config import Settings
from pinendar.infrastructure.auth_store import AccountActivity, AuthStore
from pinendar.main import cleanup_inactive_accounts, create_app, subtract_calendar_months


def isolated_client(tmp_path: Path, *, signup_enabled: bool = True) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                database_path=tmp_path / "legacy.sqlite",
                auth_database_path=tmp_path / "auth.sqlite",
                environments_dir=tmp_path / "environments",
                backups_dir=tmp_path / "backups",
                hospital_catalog_dir=Path("data/hospitals").resolve(),
                static_dir=Path("public").resolve(),
                bootstrap_username="admin",
                bootstrap_password="admin-password",
                session_secret="test-session-secret-with-enough-entropy",
                signup_enabled=signup_enabled,
                run_job_dispatcher=False,
                scheduler_process_pool=False,
            )
        )
    )


def request_and_approve(client: TestClient, username: str, password: str) -> dict[str, str]:
    requested = client.post(
        "/api/v1/auth/signup",
        json={"username": username, "password": password},
    )
    assert requested.status_code == 202
    assert requested.json()["status"] == "pending"
    assert client.post(
        "/api/v1/admin/auth/login",
        json={"username": "admin", "password": "admin-password"},
    ).status_code == 200
    pending = client.get("/api/v1/admin").json()["signupRequests"]
    normalized = requested.json()["username"]
    request_id = next(item["id"] for item in pending if item["username"] == normalized)
    assert client.post(f"/api/v1/admin/signup-requests/{request_id}/approve").status_code == 200
    client.post("/api/v1/admin/auth/logout")
    return requested.json()


def test_signup_can_be_disabled_for_public_deployments(tmp_path: Path) -> None:
    with isolated_client(tmp_path, signup_enabled=False) as client:
        assert client.get("/api/v1/auth/config").json() == {"signupEnabled": False}

        response = client.post(
            "/api/v1/auth/signup",
            json={"username": "alice", "password": "alice-password"},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "SIGNUP_DISABLED"


def test_accounts_have_independent_sqlite_environments(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        alice = request_and_approve(client, "alice", "alice-password")
        assert alice["recoveryCode"]
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        ).status_code == 200
        assert client.post("/api/v1/holidays", json={"date": "2030-01-02"}).status_code == 201

        client.post("/api/v1/auth/logout")
        request_and_approve(client, "bob", "bob-password")
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "bob", "password": "bob-password"},
        ).status_code == 200
        assert "2030-01-02" not in client.get("/api/v1/bootstrap").json()["holidays"]

        client.post("/api/v1/auth/logout")
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        ).status_code == 200
        assert "2030-01-02" in client.get("/api/v1/bootstrap").json()["holidays"]
        assert len(list((tmp_path / "environments").glob("*.sqlite"))) == 2


def test_recovery_rotates_code_password_and_sessions(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        created = request_and_approve(client, "alice", "alice-password")
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        old_cookie = client.cookies.get("pinendar_session")
        client.post("/api/v1/auth/logout")

        recovered = client.post(
            "/api/v1/auth/recover",
            json={
                "username": "alice",
                "recoveryCode": created["recoveryCode"],
                "newPassword": "new-password",
            },
        )
        assert recovered.status_code == 200
        assert recovered.json()["recoveryCode"] != created["recoveryCode"]

        client.cookies.set("pinendar_session", old_cookie)
        assert client.get("/api/v1/bootstrap").status_code == 401
        client.cookies.clear()
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "new-password"},
        ).status_code == 200

        client.post("/api/v1/auth/logout")
        reused = client.post(
            "/api/v1/auth/recover",
            json={
                "username": "alice",
                "recoveryCode": created["recoveryCode"],
                "newPassword": "third-password",
            },
        )
        assert reused.status_code == 401


def test_duplicate_username_is_rejected(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        payload = {"username": "Alice", "password": "alice-password"}
        request_and_approve(client, "Alice", "alice-password")
        duplicate = client.post("/api/v1/auth/signup", json=payload)
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "USERNAME_EXISTS"


def test_logged_in_account_can_rotate_recovery_code(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        created = request_and_approve(client, "alice", "alice-password")
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )

        rotated = client.post("/api/v1/auth/recovery-code")
        assert rotated.status_code == 200
        assert rotated.json()["recoveryCode"] != created["recoveryCode"]

        client.post("/api/v1/auth/logout")
        old_code = client.post(
            "/api/v1/auth/recover",
            json={
                "username": "alice",
                "recoveryCode": created["recoveryCode"],
                "newPassword": "new-password",
            },
        )
        assert old_code.status_code == 401
        new_code = client.post(
            "/api/v1/auth/recover",
            json={
                "username": "alice",
                "recoveryCode": rotated.json()["recoveryCode"],
                "newPassword": "new-password",
            },
        )
        assert new_code.status_code == 200


def test_guide_onboarding_is_only_pending_until_acknowledged(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        request_and_approve(client, "alice", "alice-password")
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        assert client.get("/api/v1/bootstrap").json()["account"]["guideOnboardingPending"] is True

        acknowledged = client.post("/api/v1/auth/guide-onboarding-seen")
        assert acknowledged.status_code == 200
        assert client.get("/api/v1/bootstrap").json()["account"]["guideOnboardingPending"] is False

        client.post("/api/v1/auth/logout")
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        assert client.get("/api/v1/bootstrap").json()["account"]["guideOnboardingPending"] is False


def test_existing_account_activity_starts_when_retention_is_enabled(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.sqlite")
    store.create_schema()
    account, _ = store.create_account("alice", "alice-password", tmp_path / "alice.sqlite")
    with store.session_factory.begin() as session:
        session.delete(session.get(AccountActivity, account.id))

    store.initialize_missing_activity()

    with store.session_factory() as session:
        assert session.get(AccountActivity, account.id) is not None
    store.engine.dispose()


def test_cleanup_deletes_only_accounts_older_than_six_calendar_months(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            database_path=tmp_path / "legacy.sqlite",
            auth_database_path=tmp_path / "auth.sqlite",
            environments_dir=tmp_path / "environments",
            backups_dir=tmp_path / "backups",
            hospital_catalog_dir=Path("data/hospitals").resolve(),
            static_dir=Path("public").resolve(),
            bootstrap_username="admin",
            bootstrap_password="admin-password",
            session_secret="test-session-secret-with-enough-entropy",
            run_job_dispatcher=False,
            scheduler_process_pool=False,
        )
    )
    now = datetime(2030, 8, 31, 12)
    cutoff = subtract_calendar_months(now, 6)
    with TestClient(app) as client:
        expired = client.post(
            "/api/v1/admin/auth/login",
            json={"username": "admin", "password": "admin-password"},
        )
        assert expired.status_code == 200
        client.post(
            "/api/v1/admin/accounts",
            json={"username": "expired", "password": "expired-password"},
        )
        expired_account = app.state.auth_store.get_account_by_username("expired")
        assert expired_account is not None
        expired_path = expired_account.environment_path

        current = client.post(
            "/api/v1/admin/accounts",
            json={"username": "current", "password": "current-password"},
        )
        assert current.status_code == 201
        current_account = app.state.auth_store.get_account_by_username("current")
        assert current_account is not None

        with app.state.auth_store.session_factory.begin() as session:
            session.get(AccountActivity, expired_account.id).last_active_at = datetime(2030, 2, 27)
            session.get(AccountActivity, current_account.id).last_active_at = cutoff

        assert cleanup_inactive_accounts(app, now=now) == 1
        assert app.state.auth_store.get_account(expired_account.id) is None
        assert not expired_path.exists()
        assert app.state.auth_store.get_account(current_account.id) is not None


def test_authenticated_request_refreshes_account_activity(tmp_path: Path) -> None:
    with isolated_client(tmp_path) as client:
        request_and_approve(client, "alice", "alice-password")
        client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "alice-password"},
        )
        account = client.app.state.auth_store.get_account_by_username("alice")
        assert account is not None
        old_activity = datetime(2020, 1, 1)
        with client.app.state.auth_store.session_factory.begin() as session:
            session.get(AccountActivity, account.id).last_active_at = old_activity

        assert client.get("/api/v1/bootstrap").status_code == 200

        with client.app.state.auth_store.session_factory() as session:
            refreshed = session.scalar(
                select(AccountActivity.last_active_at).where(
                    AccountActivity.account_id == account.id
                )
            )
        assert refreshed is not None and refreshed > old_activity
