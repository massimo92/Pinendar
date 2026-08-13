from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from pinendar.infrastructure.models import Assignment, Vacancy


def create_member(
    client: TestClient,
    *,
    name: str,
    allowed_types: list[str],
) -> dict:
    response = client.post(
        "/api/v1/members",
        json={
            "name": name,
            "email": f"{name.casefold().replace(' ', '-')}@deferred.test",
            "workPattern": {
                "weeks": [
                    {
                        "workingDays": [1, 2, 3, 4, 5],
                        "teleDays": [],
                    }
                ]
            },
            "allowedTypes": allowed_types,
            "managementQuota": 0,
            "fixedRules": [],
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()


def full_agendas(client: TestClient) -> tuple[dict, list[dict]]:
    agendas = [
        item
        for item in client.get("/api/v1/bootstrap").json()["agendas"]
        if item["loadPercentage"] == 100
    ]
    telematic = next(item for item in agendas if item["telematic"])
    others = [item for item in agendas if item["id"] != telematic["id"]]
    return telematic, others


def test_deferred_vacancy_uses_origin_plus_six_and_persists_origin(
    authenticated_client: TestClient,
) -> None:
    deferred_agenda, _others = full_agendas(authenticated_client)
    member = create_member(
        authenticated_client,
        name="Direct Deferred",
        allowed_types=[deferred_agenda["id"]],
    )
    database = authenticated_client.app.state.database
    origin = date(2026, 8, 11)
    last_valid = origin + timedelta(days=6)
    too_late = origin + timedelta(days=7)
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="direct-free-valid",
                    date=last_valid,
                    member_id=member["id"],
                    kind="no_assignment",
                    load_percentage=0,
                ),
                Assignment(
                    id="direct-free-too-late",
                    date=too_late,
                    member_id=member["id"],
                    kind="no_assignment",
                    load_percentage=0,
                ),
            ]
        )
        vacancy = Vacancy(date=origin, agenda_id=deferred_agenda["id"])
        session.add(vacancy)
        session.flush()
        vacancy_id = vacancy.id

    preview = authenticated_client.get(
        f"/api/v1/calendar/vacancies/{vacancy_id}/assignment-options"
    )

    assert preview.status_code == 200, preview.json()
    assert [item["targetDate"] for item in preview.json()["deferredOptions"]] == [
        last_valid.isoformat()
    ]
    proposal = preview.json()["deferredOptions"][0]
    assert proposal["deferredMemberId"] == member["id"]
    assert proposal["movements"] == []

    applied = authenticated_client.post(
        f"/api/v1/calendar/vacancies/{vacancy_id}/defer",
        json={
            "targetDate": last_valid.isoformat(),
            "expectedRevision": preview.json()["planningRevision"],
        },
    )

    assert applied.status_code == 201, applied.json()
    assert applied.json()["originDate"] == origin.isoformat()
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    deferred = next(item for item in calendar["events"] if item["id"] == applied.json()["id"])
    assert deferred["date"] == last_valid.isoformat()
    assert deferred["deferredOriginDate"] == origin.isoformat()
    assert all(item["id"] != "direct-free-valid" for item in calendar["events"])
    assert all(item["id"] != vacancy_id for item in calendar["vacancies"])


def test_deferred_vacancy_can_suggest_and_apply_a_multi_person_chain(
    authenticated_client: TestClient,
) -> None:
    deferred_agenda, others = full_agendas(authenticated_client)
    first_agenda, second_agenda = others[:2]
    free = create_member(
        authenticated_client,
        name="Chain Free",
        allowed_types=[first_agenda["id"]],
    )
    middle = create_member(
        authenticated_client,
        name="Chain Middle",
        allowed_types=[first_agenda["id"], second_agenda["id"]],
    )
    destination = create_member(
        authenticated_client,
        name="Chain Destination",
        allowed_types=[second_agenda["id"], deferred_agenda["id"]],
    )
    database = authenticated_client.app.state.database
    origin = date(2026, 8, 11)
    target = date(2026, 8, 14)
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="chain-free",
                    date=target,
                    member_id=free["id"],
                    kind="no_assignment",
                    load_percentage=0,
                ),
                Assignment(
                    id="chain-first",
                    date=target,
                    member_id=middle["id"],
                    agenda_id=first_agenda["id"],
                    load_percentage=100,
                ),
                Assignment(
                    id="chain-second",
                    date=target,
                    member_id=destination["id"],
                    agenda_id=second_agenda["id"],
                    load_percentage=100,
                ),
            ]
        )
        vacancy = Vacancy(date=origin, agenda_id=deferred_agenda["id"])
        session.add(vacancy)
        session.flush()
        vacancy_id = vacancy.id

    preview = authenticated_client.get(
        f"/api/v1/calendar/vacancies/{vacancy_id}/assignment-options"
    )

    assert preview.status_code == 200, preview.json()
    proposal = preview.json()["deferredOptions"][0]
    assert proposal["targetDate"] == target.isoformat()
    assert proposal["deferredMemberId"] == destination["id"]
    assert proposal["changeCount"] == 2
    assert {
        (item["agendaId"], item["fromMemberId"], item["toMemberId"])
        for item in proposal["movements"]
    } == {
        (first_agenda["id"], middle["id"], free["id"]),
        (second_agenda["id"], destination["id"], middle["id"]),
    }

    applied = authenticated_client.post(
        f"/api/v1/calendar/vacancies/{vacancy_id}/defer",
        json={
            "targetDate": target.isoformat(),
            "expectedRevision": preview.json()["planningRevision"],
        },
    )

    assert applied.status_code == 201, applied.json()
    with database.session_factory() as session:
        rows = list(
            session.scalars(
                select(Assignment)
                .where(Assignment.date == target)
                .order_by(Assignment.member_id)
            )
        )
        assert {
            (item.member_id, item.agenda_id, item.deferred_origin_date)
            for item in rows
        } == {
            (free["id"], first_agenda["id"], None),
            (middle["id"], second_agenda["id"], None),
            (destination["id"], deferred_agenda["id"], origin),
        }
        assert session.get(Vacancy, vacancy_id) is None


def test_deferred_vacancy_minimizes_movements_before_fairness(
    authenticated_client: TestClient,
) -> None:
    deferred_agenda, others = full_agendas(authenticated_client)
    ordinary_agenda = others[0]
    free = create_member(
        authenticated_client,
        name="Minimal Free",
        allowed_types=[deferred_agenda["id"], ordinary_agenda["id"]],
    )
    assigned = create_member(
        authenticated_client,
        name="Minimal Assigned",
        allowed_types=[deferred_agenda["id"], ordinary_agenda["id"]],
    )
    database = authenticated_client.app.state.database
    origin = date(2026, 8, 11)
    target = date(2026, 8, 14)
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id=f"minimal-free-history-{index}",
                    date=date(2026, 7, index + 1),
                    member_id=free["id"],
                    agenda_id=deferred_agenda["id"],
                    load_percentage=100,
                )
                for index in range(5)
            ]
            + [
                Assignment(
                    id=f"minimal-assigned-history-{index}",
                    date=date(2026, 7, index + 1),
                    member_id=assigned["id"],
                    agenda_id=ordinary_agenda["id"],
                    load_percentage=100,
                )
                for index in range(5)
            ]
            + [
                Assignment(
                    id="minimal-free-target",
                    date=target,
                    member_id=free["id"],
                    kind="no_assignment",
                    load_percentage=0,
                ),
                Assignment(
                    id="minimal-assigned-target",
                    date=target,
                    member_id=assigned["id"],
                    agenda_id=ordinary_agenda["id"],
                    load_percentage=100,
                ),
            ]
        )
        vacancy = Vacancy(date=origin, agenda_id=deferred_agenda["id"])
        session.add(vacancy)
        session.flush()
        vacancy_id = vacancy.id

    preview = authenticated_client.get(
        f"/api/v1/calendar/vacancies/{vacancy_id}/assignment-options"
    )

    assert preview.status_code == 200, preview.json()
    proposal = preview.json()["deferredOptions"][0]
    assert proposal["targetDate"] == target.isoformat()
    assert proposal["deferredMemberId"] == free["id"]
    assert proposal["changeCount"] == 0
    assert proposal["movements"] == []


def test_non_telematic_vacancy_has_no_deferred_options(
    authenticated_client: TestClient,
) -> None:
    _deferred_agenda, others = full_agendas(authenticated_client)
    onsite = next(item for item in others if not item["telematic"])
    member = create_member(
        authenticated_client,
        name="Onsite Free",
        allowed_types=[onsite["id"]],
    )
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add(
            Assignment(
                id="onsite-free",
                date=date(2026, 8, 14),
                member_id=member["id"],
                kind="no_assignment",
                load_percentage=0,
            )
        )
        vacancy = Vacancy(date=date(2026, 8, 11), agenda_id=onsite["id"])
        session.add(vacancy)
        session.flush()
        vacancy_id = vacancy.id

    preview = authenticated_client.get(
        f"/api/v1/calendar/vacancies/{vacancy_id}/assignment-options"
    )

    assert preview.status_code == 200
    assert preview.json()["deferredOptions"] == []
