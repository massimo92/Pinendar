from datetime import timedelta

from fastapi.testclient import TestClient

from pinendar.infrastructure.auth_store import (
    PUBLIC_LINK_REPLACED_GRACE,
    PublicShareLink,
    utc_now,
)


def public_token(client: TestClient) -> str:
    response = client.get("/api/v1/auth/public-link")
    assert response.status_code == 200
    path = response.json()["path"]
    assert path.startswith("/public/")
    token = path.removeprefix("/public/")
    assert len(token) == 64
    assert set(token) <= set("0123456789abcdef")
    return token


def test_every_account_has_a_stable_public_link(authenticated_client: TestClient) -> None:
    assert PUBLIC_LINK_REPLACED_GRACE == timedelta(days=7)
    first = public_token(authenticated_client)
    second = public_token(authenticated_client)

    assert first == second
    assert authenticated_client.get("/api/v1/auth/public-link").json()["graceDays"] == 7


def test_public_link_exposes_only_read_only_planning_views(
    authenticated_client: TestClient,
) -> None:
    token = public_token(authenticated_client)
    authenticated_client.cookies.clear()

    response = authenticated_client.get(f"/api/v1/public/{token}/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["publicAccess"] is True
    assert "account" not in body
    assert body["team"]
    assert all("email" not in member for member in body["team"])
    assert "guardTransfers" not in body["calendar"]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"

    protected_write = authenticated_client.post(
        "/api/v1/holidays", json={"date": "2031-01-02"}
    )
    assert protected_write.status_code == 401
    assert authenticated_client.post(
        f"/api/v1/public/{token}/holidays", json={"date": "2031-01-02"}
    ).status_code == 404


def test_regeneration_replaces_old_link_then_it_expires(
    authenticated_client: TestClient,
) -> None:
    old_token = public_token(authenticated_client)
    regenerated = authenticated_client.post("/api/v1/auth/public-link/regenerate")
    assert regenerated.status_code == 200
    new_token = regenerated.json()["path"].removeprefix("/public/")
    assert new_token != old_token

    authenticated_client.cookies.clear()
    replaced = authenticated_client.get(f"/api/v1/public/{old_token}/bootstrap")
    assert replaced.status_code == 410
    assert replaced.json()["error"]["code"] == "PUBLIC_LINK_REPLACED"
    assert authenticated_client.get(
        f"/api/v1/public/{new_token}/bootstrap"
    ).status_code == 200

    store = authenticated_client.app.state.auth_store
    with store.session_factory.begin() as session:
        old_link = session.get(PublicShareLink, old_token)
        assert old_link is not None
        old_link.replaced_at = utc_now() - PUBLIC_LINK_REPLACED_GRACE - timedelta(days=1)

    expired = authenticated_client.get(f"/api/v1/public/{old_token}/bootstrap")
    assert expired.status_code == 404
    assert expired.json()["error"]["code"] == "PUBLIC_LINK_NOT_FOUND"


def test_public_frontend_prevents_referrer_and_indexing(
    authenticated_client: TestClient,
) -> None:
    token = public_token(authenticated_client)

    response = authenticated_client.get(f"/public/{token}")

    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
