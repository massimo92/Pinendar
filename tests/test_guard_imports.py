from fastapi.testclient import TestClient


def test_guard_import_matches_surname_and_ignores_residents(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/guard-imports/preview",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "rows": [
                {
                    "rowNumber": 2,
                    "date": "2027-01-04",
                    "names": ["Resident no registrat", "Costa", "A. Costa"],
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    items = body["rows"][0]["items"]
    assert [item["status"] for item in items] == ["ignored", "accepted", "accepted"]
    assert items[1]["memberId"] == items[2]["memberId"]
    assert body["conflicts"] == []
    assert body["canConfirm"] is True


def test_guard_import_tolerates_a_typo_and_out_of_range_rows(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/guard-imports/preview",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "rows": [
                {"rowNumber": 2, "date": "2027-01-04", "names": ["Cotsa"]},
                {"rowNumber": 3, "date": "2027-02-01", "names": ["Costa"]},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][0]["items"][0]["status"] == "accepted"
    assert body["rows"][1]["status"] == "out_of_range"


def test_guard_import_requires_review_for_multiple_registered_members(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    members = [state["team"][0], state["team"][1]]
    response = authenticated_client.post(
        "/api/v1/guard-imports/preview",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "rows": [
                {
                    "rowNumber": 2,
                    "date": "2027-01-04",
                    "names": [members[0]["name"], members[1]["name"]],
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["canConfirm"] is False
    assert body["conflicts"][0]["date"] == "2027-01-04"


def test_confirmed_alias_is_used_on_later_import(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member = state["team"][0]
    alias = "Aina C."
    created = authenticated_client.post(
        "/api/v1/member-aliases",
        json={"memberId": member["id"], "alias": alias},
    )
    assert created.status_code == 201

    response = authenticated_client.post(
        "/api/v1/guard-imports/preview",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "rows": [{"rowNumber": 2, "date": "2027-01-04", "names": [alias]}],
        },
    )

    assert response.status_code == 200
    item = response.json()["rows"][0]["items"][0]
    assert item["status"] == "accepted"
    assert item["memberId"] == member["id"]
    assert item["reason"] == "alias confirmado"


def test_preview_does_not_create_guards_or_proposals(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member = state["team"][0]
    response = authenticated_client.post(
        "/api/v1/guard-imports/preview",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "rows": [{"rowNumber": 2, "date": "2027-01-04", "names": [member["name"]]}],
        },
    )

    assert response.status_code == 200
    after = authenticated_client.get("/api/v1/bootstrap").json()
    assert after["guards"] == []
    assert after["draft"] is None
