from fastapi.testclient import TestClient


def test_health_reports_application_and_database_ready(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok"}
    assert client.get("/health/ready").json() == {"status": "ready"}


def test_protected_api_returns_structured_error(client: TestClient) -> None:
    response = client.get("/api/v1/bootstrap")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "UNAUTHORIZED",
            "message": "No autoritzat",
            "field": None,
            "details": {},
        }
    }


def test_bootstrap_exposes_normalized_initial_state(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/v1/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["planningRevision"] == 1
    assert len(body["team"]) == 12
    assert len(body["agendas"]) == 9
    assert {agenda["shift"] for agenda in body["agendas"]} == {"morning"}
    assert {hospital["catalogId"] for hospital in body["hospitals"]} == {"170010", "170301"}
    assert body["draft"] is None
    assert body["published"] == []


def test_legacy_state_endpoint_is_removed(client: TestClient) -> None:
    assert "/api/state" not in client.get("/openapi.json").json()["paths"]
    response = client.put("/api/state", json={})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ENDPOINT_NOT_FOUND"


def test_frontend_es_modules_are_served(client: TestClient) -> None:
    assert "normalizeBootstrapState" in client.get("/state.js").text
    assert "shellTemplate" in client.get("/views.js").text
