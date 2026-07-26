from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from pinendar.application.commands import color_hue, madrid_today, random_color
from pinendar.application.jobs import build_problem
from pinendar.application.state import import_calendar_record, serialize_calendar
from pinendar.infrastructure.models import (
    Absence,
    AgendaRecurrence,
    Assignment,
    Guard,
    MemberStatusChange,
    Vacancy,
)


def member_payload(member: dict, **overrides: object) -> dict:
    return {
        "name": member["name"],
        "email": member["email"],
        "active": member["active"],
        "vacationDates": member["vacationDates"],
        "availableDays": member["availableDays"],
        "workPattern": member["workPattern"],
        "teleDays": member["teleDays"],
        "allowedTypes": member["allowedTypes"],
        "agendaPreferences": member.get("agendaPreferences", {}),
        "managementQuota": member["managementQuota"],
        "fixedRules": member["fixedRules"],
        **overrides,
    }


def create_manual_planning_member(
    authenticated_client: TestClient,
    *,
    name: str,
    email: str,
    agenda_ids: list[str],
    telework: bool = False,
) -> dict:
    response = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": name,
            "email": email,
            "workPattern": {
                "weeks": [
                    {
                        "workingDays": [2],
                        "teleDays": [2] if telework else [],
                    }
                ]
            },
            "allowedTypes": agenda_ids,
            "managementQuota": 0,
            "fixedRules": [],
        },
    )
    assert response.status_code == 201
    return response.json()


def same_load_agendas(state: dict) -> tuple[dict, dict]:
    for index, agenda in enumerate(state["agendas"]):
        for candidate in state["agendas"][index + 1 :]:
            if agenda["loadPercentage"] == candidate["loadPercentage"]:
                return agenda, candidate
    raise AssertionError("The fixture needs two agendas with the same load")


def test_automatic_colors_choose_the_furthest_available_hue() -> None:
    color = random_color("agenda", ["hsl(0 90% 56%)", "hsl(180 90% 56%)"])

    assert color_hue(color) in {90, 270}


def test_member_commands_are_backend_authoritative(authenticated_client: TestClient) -> None:
    before = authenticated_client.get("/api/v1/bootstrap").json()
    agenda_ids = [item["id"] for item in before["agendas"][:2]]

    created = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Núria Prat",
            "email": "nuria@hospital.test",
            "color": "red",
            "availableDays": [1, 2, 3],
            "teleDays": [1],
            "allowedTypes": agenda_ids,
            "managementQuota": 0,
            "fixedRules": [],
        },
    )

    assert created.status_code == 201
    assert created.json()["color"].startswith("hsl(")
    assert created.json()["color"] != "red"
    duplicate = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Núria Prat",
            "email": "other@hospital.test",
            "availableDays": [1],
            "teleDays": [],
            "allowedTypes": agenda_ids,
            "managementQuota": 0,
            "fixedRules": [],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "MEMBER_NAME_EXISTS"


def test_member_work_pattern_persists_alternating_weeks(authenticated_client: TestClient) -> None:
    agenda_ids = [item["id"] for item in authenticated_client.get("/api/v1/bootstrap").json()["agendas"][:2]]

    response = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Persona alternant",
            "email": "alternant@hospital.test",
            "workPattern": {
                "weeks": [
                    {"workingDays": [1, 2, 3], "teleDays": [1]},
                    {"workingDays": [1, 2, 3, 4], "teleDays": [2, 4]},
                ],
            },
            "teleDays": [],
            "allowedTypes": agenda_ids,
            "managementQuota": 0,
            "fixedRules": [],
        },
    )

    assert response.status_code == 201
    assert response.json()["workPattern"] == {
        "weeks": [
            {"workingDays": [1, 2, 3], "teleDays": [1]},
            {"workingDays": [1, 2, 3, 4], "teleDays": [2, 4]},
        ],
    }
    assert response.json()["availableDays"] == [1, 2, 3, 4]
    assert response.json()["teleDays"] == [1, 2, 4]


def test_member_agenda_preferences_persist_and_neutral_is_implicit(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member = state["team"][0]
    liked, disliked, neutral = state["agendas"][:3]

    response = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(
            member,
            agendaPreferences={
                liked["id"]: 1,
                disliked["id"]: -1,
                neutral["id"]: 0,
            },
        ),
    )

    assert response.status_code == 200
    assert response.json()["agendaPreferences"] == {
        disliked["id"]: -1,
        liked["id"]: 1,
    }
    reloaded = authenticated_client.get("/api/v1/bootstrap").json()
    saved = next(item for item in reloaded["team"] if item["id"] == member["id"])
    assert saved["agendaPreferences"] == response.json()["agendaPreferences"]


def test_member_agenda_preferences_reject_unknown_agenda(
    authenticated_client: TestClient,
) -> None:
    member = authenticated_client.get("/api/v1/bootstrap").json()["team"][0]

    response = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(member, agendaPreferences={"missing-agenda": 1}),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_AGENDA_PREFERENCE"


def test_member_work_pattern_rejects_telework_outside_working_days(authenticated_client: TestClient) -> None:
    agenda_ids = [item["id"] for item in authenticated_client.get("/api/v1/bootstrap").json()["agendas"][:1]]

    response = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Patró invàlid",
            "email": "invalid-pattern@hospital.test",
            "workPattern": {
                "weeks": [{"workingDays": [1, 2, 3], "teleDays": [4]}]
            },
            "teleDays": [],
            "allowedTypes": agenda_ids,
            "managementQuota": 0,
            "fixedRules": [],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_WORK_PATTERN"


def test_management_is_enabled_independently_from_agenda_capabilities(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member = state["team"][0]
    assert "gestio" not in {item["id"] for item in state["agendas"]}

    enabled = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(member, managementQuota=3),
    )

    assert enabled.status_code == 200
    assert enabled.json()["managementQuota"] == 3
    assert enabled.json()["allowedTypes"] == member["allowedTypes"]

    disabled_payload = member_payload(enabled.json())
    disabled_payload.pop("managementQuota")
    disabled = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=disabled_payload,
    )
    assert disabled.status_code == 200
    assert disabled.json()["managementQuota"] == 0


def test_management_quota_rejects_more_than_five_days(
    authenticated_client: TestClient,
) -> None:
    member = authenticated_client.get("/api/v1/bootstrap").json()["team"][0]

    response = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(member, managementQuota=6),
    )

    assert response.status_code == 422


def test_management_assignment_persists_without_an_agenda(
    authenticated_client: TestClient,
) -> None:
    database = authenticated_client.app.state.database
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member_id = state["team"][0]["id"]
    with database.session_factory.begin() as session:
        import_calendar_record(
            session,
            {
                "startMonth": "2027-01",
                "endMonth": "2027-01",
                "generatedAt": "2027-01-01T00:00:00",
                "assignments": [
                    {
                        "id": "management-assignment",
                        "date": "2027-01-08",
                        "memberId": member_id,
                        "type": "management",
                        "management": True,
                    }
                ],
                "unfilled": [],
                "conditions": {"guards": [], "absences": []},
            },
            {member_id},
            {item["id"] for item in state["agendas"]},
        )
        session.flush()
        assignment = session.get(Assignment, "management-assignment")
        serialized = serialize_calendar(session)

        assert assignment is not None
        assert assignment.agenda_id is None
        assert assignment.kind == "management"
        assert serialized["events"][0]["type"] == "management"


def test_member_status_is_tracked_and_inactive_member_is_not_planned(authenticated_client: TestClient) -> None:
    member = authenticated_client.get("/api/v1/bootstrap").json()["team"][0]

    response = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(member, active=False),
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert response.json()["statusHistory"][-1]["active"] is False
    database = authenticated_client.app.state.database
    with database.session_factory() as session:
        changes = list(
            session.scalars(
                select(MemberStatusChange).where(MemberStatusChange.member_id == member["id"])
            )
        )
        problem = build_problem(
            session,
            authenticated_client.app.state.catalog,
            {"startMonth": "2099-01", "endMonth": "2099-01", "guards": [], "absences": []},
        )
    assert [item.active for item in changes] == [False]
    assert member["id"] not in {item["id"] for item in problem.team}


def test_member_vacations_are_saved_and_past_days_are_immutable(authenticated_client: TestClient) -> None:
    member = authenticated_client.get("/api/v1/bootstrap").json()["team"][0]
    today = madrid_today()
    future = [(today + timedelta(days=value)).isoformat() for value in (10, 11, 14)]
    saved = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(member, vacationDates=future),
    )
    assert saved.status_code == 200
    assert saved.json()["vacationDates"] == future

    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add(
            Absence(
                id="past-vacation",
                member_id=member["id"],
                category="vacances",
                start=today - timedelta(days=3),
                end=today - timedelta(days=2),
            )
        )
    rejected = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(saved.json(), vacationDates=future),
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "PAST_VACATIONS_IMMUTABLE"


def test_telework_day_rejects_an_onsite_fixed_rule(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Pau Ferrer",
            "email": "pau@hospital.test",
            "availableDays": [1],
            "teleDays": [1],
            "allowedTypes": ["eco_amb"],
            "managementQuota": 0,
            "fixedRules": [{"weekday": 1, "type": "eco_amb"}],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TELEWORK_AGENDA_REQUIRED"


def test_updating_a_profile_persists_a_valid_fixed_rule(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member = next(item for item in state["team"] if not item["fixedRules"])
    agenda_id = next(
        agenda_id
        for agenda_id in member["allowedTypes"]
        if state["coverage"]["1"].get(agenda_id, 0) > 0
    )

    response = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(member, fixedRules=[{"weekday": 1, "type": agenda_id}]),
    )

    assert response.status_code == 200
    assert response.json()["fixedRules"] == [
        {"id": response.json()["fixedRules"][0]["id"], "weekday": 1, "type": agenda_id}
    ]
    reloaded = authenticated_client.get("/api/v1/bootstrap").json()
    saved = next(item for item in reloaded["team"] if item["id"] == member["id"])
    assert saved["fixedRules"][0]["type"] == agenda_id


def test_fixed_rule_accepts_an_agenda_with_monthly_demand_on_that_weekday(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    hospital_id = state["hospitals"][0]["catalogId"]
    agenda = authenticated_client.post(
        "/api/v1/agendas",
        json={
            "name": "Comitè UNK",
            "hospitalId": hospital_id,
            "telematic": False,
            "shift": "morning",
            "priority": 3,
            "coverage": {str(day): 0 for day in range(1, 6)},
            "recurrences": [{"ordinal": 3, "weekday": 3, "slots": 1}],
        },
    ).json()

    response = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Queralt Recurrència",
            "email": "queralt-recurrencia@hospital.test",
            "availableDays": [3],
            "teleDays": [],
            "allowedTypes": [agenda["id"]],
            "managementQuota": 0,
            "fixedRules": [{"weekday": 3, "type": agenda["id"]}],
        },
    )

    assert response.status_code == 201
    assert response.json()["fixedRules"][0] | {"id": "ignored"} == {
        "id": "ignored",
        "weekday": 3,
        "type": agenda["id"],
    }


def test_adding_an_existing_fixed_rule_requires_confirmation(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    owner = next(member for member in state["team"] if member["fixedRules"])
    existing_rule = owner["fixedRules"][0]
    member = next(
        item
        for item in state["team"]
        if item["id"] != owner["id"]
        and existing_rule["weekday"] in item["availableDays"]
        and existing_rule["type"] in item["allowedTypes"]
        and not item["fixedRules"]
    )
    payload = member_payload(member, fixedRules=[{"weekday": existing_rule["weekday"], "type": existing_rule["type"]}])

    rejected = authenticated_client.put(f"/api/v1/members/{member['id']}", json=payload)

    assert rejected.status_code == 409
    error = rejected.json()["error"]
    assert error["code"] == "SHARED_FIXED_RULE_CONFIRMATION_REQUIRED"
    assert error["details"]["rules"][0]["people"] == [{"id": owner["id"], "name": owner["name"]}]

    confirmed = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json={**payload, "confirmSharedFixedRules": True},
    )

    assert confirmed.status_code == 200
    shared = [
        item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["team"]
        if any(
            rule["weekday"] == existing_rule["weekday"] and rule["type"] == existing_rule["type"]
            for rule in item["fixedRules"]
        )
    ]
    assert {item["id"] for item in shared} == {owner["id"], member["id"]}

    unchanged = authenticated_client.put(
        f"/api/v1/members/{member['id']}",
        json=member_payload(confirmed.json()),
    )
    assert unchanged.status_code == 200


def test_telework_fixed_rule_blocks_changing_agenda_to_onsite(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    agenda = next(item for item in state["agendas"] if item["id"] == "tac_amb")
    member = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "Pau Ferrer",
            "email": "pau@hospital.test",
            "availableDays": [1],
            "teleDays": [1],
            "allowedTypes": [agenda["id"]],
            "managementQuota": 0,
            "fixedRules": [{"weekday": 1, "type": agenda["id"]}],
        },
    )
    assert member.status_code == 201

    response = authenticated_client.put(
        f"/api/v1/agendas/{agenda['id']}",
        json={
            "name": agenda["name"],
            "hospitalId": agenda["hospitalId"],
            "telematic": False,
            "shift": agenda["shift"],
            "priority": agenda["priority"],
            "coverage": {
                str(day): state["coverage"][str(day)][agenda["id"]] for day in range(1, 6)
            },
            "recurrences": agenda["recurrences"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TELEWORK_AGENDA_REQUIRED"


def test_telework_day_rejects_manual_onsite_assignment(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member = next(item for item in state["team"] if 1 in item["teleDays"])
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add(
            Assignment(
                id="assignment-manual-telework",
                date=datetime(2026, 1, 5).date(),
                member_id=member["id"],
                agenda_id="tac_amb",
            )
        )

    response = authenticated_client.patch(
        "/api/v1/calendar/events/assignment-manual-telework",
        json={"type": "eco_amb"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TELEWORK_AGENDA_REQUIRED"


def test_assignment_exchange_is_ranked_by_equity_and_updates_both_people_atomically(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    first_agenda, second_agenda = same_load_agendas(state)
    allowed = [first_agenda["id"], second_agenda["id"]]
    first_member = create_manual_planning_member(
        authenticated_client,
        name="Intercanvi A",
        email="intercanvi-a@hospital.test",
        agenda_ids=allowed,
    )
    second_member = create_manual_planning_member(
        authenticated_client,
        name="Intercanvi B",
        email="intercanvi-b@hospital.test",
        agenda_ids=allowed,
    )
    database = authenticated_client.app.state.database
    planning_date = datetime(2026, 8, 11).date()
    with database.session_factory.begin() as session:
        for index in range(4):
            session.add_all(
                [
                    Assignment(
                        id=f"history-a-{index}",
                        date=datetime(2026, 1, index + 5).date(),
                        member_id=first_member["id"],
                        agenda_id=first_agenda["id"],
                    ),
                    Assignment(
                        id=f"history-b-{index}",
                        date=datetime(2026, 1, index + 5).date(),
                        member_id=second_member["id"],
                        agenda_id=second_agenda["id"],
                    ),
                ]
            )
        session.add_all(
            [
                Assignment(
                    id="exchange-source",
                    date=planning_date,
                    member_id=first_member["id"],
                    agenda_id=first_agenda["id"],
                ),
                Assignment(
                    id="exchange-target",
                    date=planning_date,
                    member_id=second_member["id"],
                    agenda_id=second_agenda["id"],
                ),
            ]
        )

    options = authenticated_client.get(
        "/api/v1/calendar/events/exchange-source/exchange-options"
    )

    assert options.status_code == 200
    assert options.json()["options"][0]["targetAssignmentId"] == "exchange-target"
    assert options.json()["options"][0]["fairnessEffect"] == "improves"
    assert options.json()["options"][0]["fairnessWorstDeltaBasisPoints"] > 0

    exchanged = authenticated_client.post(
        "/api/v1/calendar/events/exchange-source/exchange",
        json={"targetAssignmentId": "exchange-target"},
    )

    assert exchanged.status_code == 200
    assert exchanged.json()["source"]["type"] == second_agenda["id"]
    assert exchanged.json()["target"]["type"] == first_agenda["id"]
    with database.session_factory() as session:
        source = session.get(Assignment, "exchange-source")
        target = session.get(Assignment, "exchange-target")
        assert source and source.agenda_id == second_agenda["id"] and source.locked
        assert target and target.agenda_id == first_agenda["id"] and target.locked


def test_invalid_exchange_is_rejected_without_changing_either_assignment(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    first_agenda, second_agenda = same_load_agendas(state)
    first_member = create_manual_planning_member(
        authenticated_client,
        name="Intercanvi vàlid",
        email="intercanvi-valid@hospital.test",
        agenda_ids=[first_agenda["id"], second_agenda["id"]],
    )
    second_member = create_manual_planning_member(
        authenticated_client,
        name="Intercanvi restringit",
        email="intercanvi-restringit@hospital.test",
        agenda_ids=[second_agenda["id"]],
    )
    database = authenticated_client.app.state.database
    planning_date = datetime(2026, 8, 11).date()
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="invalid-exchange-source",
                    date=planning_date,
                    member_id=first_member["id"],
                    agenda_id=first_agenda["id"],
                ),
                Assignment(
                    id="invalid-exchange-target",
                    date=planning_date,
                    member_id=second_member["id"],
                    agenda_id=second_agenda["id"],
                ),
            ]
        )

    options = authenticated_client.get(
        "/api/v1/calendar/events/invalid-exchange-source/exchange-options"
    )
    rejected = authenticated_client.post(
        "/api/v1/calendar/events/invalid-exchange-source/exchange",
        json={"targetAssignmentId": "invalid-exchange-target"},
    )

    assert options.status_code == 200
    assert options.json()["options"] == []
    assert rejected.status_code == 409
    with database.session_factory() as session:
        source = session.get(Assignment, "invalid-exchange-source")
        target = session.get(Assignment, "invalid-exchange-target")
        assert source and source.agenda_id == first_agenda["id"]
        assert target and target.agenda_id == second_agenda["id"]


def test_fixed_assignment_exchange_requires_confirmation_and_unlocks_the_override(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    first_agenda, second_agenda = same_load_agendas(state)
    first_member = create_manual_planning_member(
        authenticated_client,
        name="Intercanvi fix",
        email="intercanvi-fix@hospital.test",
        agenda_ids=[first_agenda["id"], second_agenda["id"]],
    )
    second_member = create_manual_planning_member(
        authenticated_client,
        name="Intercanvi lliure",
        email="intercanvi-lliure@hospital.test",
        agenda_ids=[first_agenda["id"], second_agenda["id"]],
    )
    third_member = create_manual_planning_member(
        authenticated_client,
        name="Altra assignació fixa",
        email="altra-assignacio-fixa@hospital.test",
        agenda_ids=[first_agenda["id"], second_agenda["id"]],
    )
    database = authenticated_client.app.state.database
    planning_date = datetime(2026, 8, 11).date()
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="fixed-exchange-source",
                    date=planning_date,
                    member_id=first_member["id"],
                    agenda_id=first_agenda["id"],
                    fixed=True,
                ),
                Assignment(
                    id="fixed-exchange-target",
                    date=planning_date,
                    member_id=second_member["id"],
                    agenda_id=second_agenda["id"],
                ),
                Assignment(
                    id="other-fixed-exchange-target",
                    date=planning_date,
                    member_id=third_member["id"],
                    agenda_id=first_agenda["id"],
                    fixed=True,
                ),
            ]
        )

    warning = authenticated_client.get(
        "/api/v1/calendar/events/fixed-exchange-source/exchange-options"
    )
    options = authenticated_client.get(
        "/api/v1/calendar/events/fixed-exchange-source/exchange-options",
        params={"includeFixed": "true"},
    )
    rejected = authenticated_client.post(
        "/api/v1/calendar/events/fixed-exchange-source/exchange",
        json={"targetAssignmentId": "fixed-exchange-target"},
    )

    assert warning.status_code == 409
    assert warning.json()["error"]["code"] == "FIXED_ASSIGNMENT_CONFIRMATION_REQUIRED"
    assert options.status_code == 200
    assert options.json()["sourceFixed"] is True
    assert [item["targetAssignmentId"] for item in options.json()["options"]] == [
        "fixed-exchange-target"
    ]
    assert rejected.status_code == 409

    indirect_fixed_change = authenticated_client.post(
        "/api/v1/calendar/events/fixed-exchange-target/exchange",
        json={
            "targetAssignmentId": "other-fixed-exchange-target",
            "confirmFixed": True,
        },
    )
    assert indirect_fixed_change.status_code == 409

    exchanged = authenticated_client.post(
        "/api/v1/calendar/events/fixed-exchange-source/exchange",
        json={
            "targetAssignmentId": "fixed-exchange-target",
            "confirmFixed": True,
        },
    )

    assert exchanged.status_code == 200
    with database.session_factory() as session:
        source = session.get(Assignment, "fixed-exchange-source")
        target = session.get(Assignment, "fixed-exchange-target")
        assert source and source.agenda_id == second_agenda["id"] and source.locked
        assert target and target.agenda_id == first_agenda["id"] and target.locked
        assert source.fixed is False
        assert target.fixed is False


def test_extra_assignment_can_be_opened_for_an_inferred_unassigned_person(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    first_agenda, second_agenda = same_load_agendas(state)
    member = create_manual_planning_member(
        authenticated_client,
        name="Plaça extraordinària",
        email="placa-extra@hospital.test",
        agenda_ids=[first_agenda["id"], second_agenda["id"]],
    )
    planning_date = datetime(2026, 8, 11).date()

    options = authenticated_client.get(
        f"/api/v1/calendar/dates/{planning_date.isoformat()}/members/{member['id']}/extra-options"
    )

    assert options.status_code == 200
    assert {item["agendaId"] for item in options.json()["options"]} == {
        first_agenda["id"],
        second_agenda["id"],
    }
    deltas = [
        (item["fairnessWorstDeltaBasisPoints"], item["fairnessDeltaBasisPoints"])
        for item in options.json()["options"]
    ]
    assert deltas == sorted(deltas, reverse=True)

    created = authenticated_client.post(
        f"/api/v1/calendar/dates/{planning_date.isoformat()}/members/{member['id']}/extra-assignments",
        json={"agendaId": first_agenda["id"]},
    )

    assert created.status_code == 201
    assert created.json()["extra"] is True
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    saved = next(item for item in calendar["events"] if item["memberId"] == member["id"])
    assert saved["type"] == first_agenda["id"]
    assert saved["extra"] is True


def test_extra_assignment_options_respect_a_telematic_day(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    telematic = next(item for item in state["agendas"] if item["telematic"])
    onsite = next(item for item in state["agendas"] if not item["telematic"])
    member = create_manual_planning_member(
        authenticated_client,
        name="Extra telemàtica",
        email="extra-telematica@hospital.test",
        agenda_ids=[telematic["id"], onsite["id"]],
        telework=True,
    )
    planning_date = datetime(2026, 8, 11).date()

    options = authenticated_client.get(
        f"/api/v1/calendar/dates/{planning_date.isoformat()}/members/{member['id']}/extra-options"
    )

    assert options.status_code == 200
    agenda_ids = {item["agendaId"] for item in options.json()["options"]}
    assert telematic["id"] in agenda_ids
    assert onsite["id"] not in agenda_ids


def test_extra_assignment_rejects_a_profile_vacation(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    agenda = state["agendas"][0]
    member = create_manual_planning_member(
        authenticated_client,
        name="Extra de vacances",
        email="extra-vacances@hospital.test",
        agenda_ids=[agenda["id"]],
    )
    database = authenticated_client.app.state.database
    planning_date = datetime(2026, 8, 11).date()
    with database.session_factory.begin() as session:
        session.add(
            Absence(
                id="profile-vacation-extra",
                member_id=member["id"],
                category="vacances",
                start=planning_date,
                end=planning_date,
            )
        )

    options = authenticated_client.get(
        f"/api/v1/calendar/dates/{planning_date.isoformat()}/members/{member['id']}/extra-options"
    )

    assert options.status_code == 409
    assert options.json()["error"]["code"] == "MEMBER_NOT_PLANNABLE"


def test_invalid_agenda_hospital_is_rejected(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/agendas",
        json={
            "name": "Nova agenda",
            "hospitalId": "missing",
            "telematic": False,
            "shift": "morning",
            "coverage": {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1},
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HOSPITAL_NOT_SELECTED"


def test_agenda_priority_and_recurrences_are_backend_authoritative(authenticated_client: TestClient) -> None:
    hospital_id = authenticated_client.get("/api/v1/bootstrap").json()["hospitals"][0]["catalogId"]
    payload = {
        "name": "Agenda periòdica",
        "hospitalId": hospital_id,
        "telematic": False,
        "shift": "afternoon",
        "priority": 2,
        "coverage": {"1": 1, "2": 0, "3": 0, "4": 0, "5": 0},
        "recurrences": [{"ordinal": 2, "weekday": 3, "slots": 1}],
    }

    created = authenticated_client.post("/api/v1/agendas", json=payload)

    assert created.status_code == 201
    assert created.json()["shift"] == "afternoon"
    assert created.json()["priority"] == 2
    assert created.json()["recurrences"][0] | {"id": "ignored"} == {
        "id": "ignored",
        "ordinal": 2,
        "weekday": 3,
        "slots": 1,
    }
    persisted = next(
        item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["agendas"]
        if item["id"] == created.json()["id"]
    )
    assert persisted["priority"] == 2
    assert persisted["shift"] == "afternoon"
    assert persisted["recurrences"][0]["ordinal"] == 2

    duplicate = authenticated_client.put(
        f"/api/v1/agendas/{created.json()['id']}",
        json={
            **payload,
            "recurrences": [
                {"ordinal": 2, "weekday": 3, "slots": 1},
                {"ordinal": 2, "weekday": 3, "slots": 1},
            ],
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_AGENDA_RECURRENCE"

    database = authenticated_client.app.state.database
    with database.session_factory() as session:
        assert session.scalar(
            select(AgendaRecurrence).where(AgendaRecurrence.agenda_id == created.json()["id"])
        ) is not None


def test_agenda_priority_is_limited_to_four_levels(authenticated_client: TestClient) -> None:
    hospital_id = authenticated_client.get("/api/v1/bootstrap").json()["hospitals"][0]["catalogId"]

    response = authenticated_client.post(
        "/api/v1/agendas",
        json={
            "name": "Prioritat invàlida",
            "hospitalId": hospital_id,
            "telematic": False,
            "shift": "morning",
            "priority": 5,
            "coverage": {str(day): 0 for day in range(1, 6)},
            "recurrences": [],
        },
    )

    assert response.status_code == 422


def test_agenda_recurrence_always_represents_one_slot(authenticated_client: TestClient) -> None:
    hospital_id = authenticated_client.get("/api/v1/bootstrap").json()["hospitals"][0]["catalogId"]

    response = authenticated_client.post(
        "/api/v1/agendas",
        json={
            "name": "Recurrència invàlida",
            "hospitalId": hospital_id,
            "telematic": False,
            "shift": "morning",
            "priority": 3,
            "coverage": {str(day): 0 for day in range(1, 6)},
            "recurrences": [{"ordinal": 1, "weekday": 1, "slots": 2}],
        },
    )

    assert response.status_code == 422


def test_agenda_shift_is_required_and_limited_to_supported_shifts(
    authenticated_client: TestClient,
) -> None:
    hospital_id = authenticated_client.get("/api/v1/bootstrap").json()["hospitals"][0]["catalogId"]
    payload = {
        "name": "Agenda amb torn",
        "hospitalId": hospital_id,
        "telematic": False,
        "priority": 3,
        "coverage": {str(day): 0 for day in range(1, 6)},
        "recurrences": [],
    }

    assert authenticated_client.post("/api/v1/agendas", json=payload).status_code == 422
    assert (
        authenticated_client.post("/api/v1/agendas", json={**payload, "shift": "night"}).status_code
        == 422
    )


def test_agenda_coverage_cannot_invalidate_existing_fixed_rules(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    rule = next(member["fixedRules"][0] for member in state["team"] if member["fixedRules"])
    agenda = next(item for item in state["agendas"] if item["id"] == rule["type"])
    coverage = {str(day): state["coverage"][str(day)][agenda["id"]] for day in range(1, 6)}
    coverage[str(rule["weekday"])] = 0

    response = authenticated_client.put(
        f"/api/v1/agendas/{agenda['id']}",
        json={
            "name": agenda["name"],
            "hospitalId": agenda["hospitalId"],
            "telematic": agenda["telematic"],
            "shift": agenda["shift"],
            "priority": agenda["priority"],
            "coverage": coverage,
            "recurrences": agenda["recurrences"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FIXED_RULE_CAPACITY"
    affected = response.json()["error"]["details"]["rules"]
    assert affected == [
        {
            "id": rule["id"],
            "memberId": next(member["id"] for member in state["team"] if rule in member["fixedRules"]),
            "memberName": next(member["name"] for member in state["team"] if rule in member["fixedRules"]),
            "weekday": rule["weekday"],
            "agendaId": agenda["id"],
            "agendaName": agenda["name"],
        }
    ]

    confirmed = authenticated_client.put(
        f"/api/v1/agendas/{agenda['id']}",
        json={
            "name": f"{agenda['name']} actualitzada",
            "hospitalId": agenda["hospitalId"],
            "telematic": agenda["telematic"],
            "shift": agenda["shift"],
            "priority": agenda["priority"],
            "loadPercentage": agenda["loadPercentage"],
            "coverage": coverage,
            "recurrences": agenda["recurrences"],
            "deleteConflictingFixedRules": True,
        },
    )

    assert confirmed.status_code == 200
    updated = authenticated_client.get("/api/v1/bootstrap").json()
    assert next(item for item in updated["agendas"] if item["id"] == agenda["id"])["name"].endswith("actualitzada")
    assert not any(
        fixed_rule["id"] == rule["id"]
        for member in updated["team"]
        for fixed_rule in member["fixedRules"]
    )


def test_selected_hospital_response_uses_database_id_for_removal(authenticated_client: TestClient) -> None:
    created = authenticated_client.post("/api/v1/selected-hospitals", json={"catalogId": "170176"})

    assert created.status_code == 201
    hospital = created.json()
    assert hospital["id"] != hospital["catalogId"]
    selected = next(
        item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["hospitals"]
        if item["catalogId"] == "170176"
    )
    assert selected["id"] == hospital["id"]
    assert authenticated_client.delete(f"/api/v1/selected-hospitals/{hospital['id']}").status_code == 204


def test_manual_hospital_is_saved_without_map_location(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/selected-hospitals",
        json={"name": "Centre sanitari de prova"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Centre sanitari de prova"
    assert response.json()["locationKnown"] is False
    assert response.json()["catalogId"].startswith("manual_")
    selected = authenticated_client.get("/api/v1/bootstrap").json()["hospitals"]
    assert any(item["name"] == "Centre sanitari de prova" and item["locationKnown"] is False for item in selected)


def test_agenda_load_is_limited_to_half_or_full(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    agenda = state["agendas"][0]
    coverage = {str(day): state["coverage"][str(day)][agenda["id"]] for day in range(1, 6)}

    saved = authenticated_client.put(
        f"/api/v1/agendas/{agenda['id']}",
        json={
            "name": agenda["name"],
            "hospitalId": agenda["hospitalId"],
            "telematic": agenda["telematic"],
            "shift": agenda["shift"],
            "priority": agenda["priority"],
            "loadPercentage": 50,
            "coverage": coverage,
            "recurrences": agenda["recurrences"],
        },
    )

    assert saved.status_code == 200
    assert saved.json()["loadPercentage"] == 50
    assert next(item for item in authenticated_client.get("/api/v1/bootstrap").json()["agendas"] if item["id"] == agenda["id"])["loadPercentage"] == 50
    invalid = authenticated_client.put(
        f"/api/v1/agendas/{agenda['id']}",
        json={
            "name": agenda["name"],
            "hospitalId": agenda["hospitalId"],
            "telematic": agenda["telematic"],
            "shift": agenda["shift"],
            "priority": agenda["priority"],
            "loadPercentage": 75,
            "coverage": coverage,
            "recurrences": agenda["recurrences"],
        },
    )
    assert invalid.status_code == 422


def test_calendar_assignments_can_be_deleted_for_an_inclusive_range(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member_id = state["team"][0]["id"]
    agenda_id = state["agendas"][0]["id"]
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(id="before-range", date=datetime(2027, 1, 4).date(), member_id=member_id, agenda_id=agenda_id),
                Assignment(id="inside-range", date=datetime(2027, 1, 10).date(), member_id=member_id, agenda_id=agenda_id),
                Assignment(id="after-range", date=datetime(2027, 1, 20).date(), member_id=member_id, agenda_id=agenda_id),
                Vacancy(date=datetime(2027, 1, 11).date(), agenda_id=agenda_id),
                Guard(id="guard-inside-range", member_id=member_id, date=datetime(2027, 1, 10).date()),
                Absence(id="absence-spanning-range", member_id=member_id, category="vacances", start=datetime(2027, 1, 1).date(), end=datetime(2027, 1, 31).date()),
            ]
        )

    response = authenticated_client.delete(
        "/api/v1/calendar/assignments",
        params={"startDate": "2027-01-08", "endDate": "2027-01-15"},
    )

    assert response.status_code == 200
    assert response.json() == {"assignmentsDeleted": 1, "vacanciesDeleted": 1}
    with database.session_factory() as session:
        assert session.get(Assignment, "before-range") is not None
        assert session.get(Assignment, "inside-range") is None
        assert session.get(Assignment, "after-range") is not None
        assert session.get(Guard, "guard-inside-range") is not None
        absence = session.get(Absence, "absence-spanning-range")
        assert absence is not None
        assert (absence.start.isoformat(), absence.end.isoformat()) == (
            "2027-01-01",
            "2027-01-31",
        )


def test_guards_can_be_added_without_regenerating_calendar(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member_id = state["team"][0]["id"]
    database = authenticated_client.app.state.database

    response = authenticated_client.post(
        "/api/v1/guards",
        json={"guards": [{"memberId": member_id, "date": "2027-03-12"}]},
    )

    assert response.status_code == 201
    assert response.json()["added"] == 1
    with database.session_factory() as session:
        guard = session.scalar(select(Guard).where(Guard.date == datetime(2027, 3, 12).date()))
        assert guard is not None
        assert guard.member_id == member_id
        assert guard.date.isoformat() == "2027-03-12"

    replacement_member_id = state["team"][1]["id"]
    response = authenticated_client.put(
        "/api/v1/guards",
        json={"guards": [{"memberId": replacement_member_id, "date": "2027-03-12"}]},
    )

    assert response.status_code == 200
    assert [(item["memberId"], item["date"]) for item in response.json()["guards"]] == [
        (replacement_member_id, "2027-03-12")
    ]


def test_clearing_all_calendar_rows_leaves_no_planning_events(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member_id = state["team"][0]["id"]
    agenda_id = state["agendas"][0]["id"]
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="only-assignment",
                    date=datetime(2027, 2, 8).date(),
                    member_id=member_id,
                    agenda_id=agenda_id,
                ),
                Vacancy(
                    date=datetime(2027, 2, 9).date(),
                    agenda_id=agenda_id,
                ),
            ]
        )

    response = authenticated_client.delete(
        "/api/v1/calendar/assignments",
        params={"startDate": "2027-02-01", "endDate": "2027-02-28"},
    )

    assert response.status_code == 200
    assert response.json() == {"assignmentsDeleted": 1, "vacanciesDeleted": 1}
    with database.session_factory() as session:
        assert session.get(Assignment, "only-assignment") is None
        assert session.scalar(select(Vacancy).where(Vacancy.date == datetime(2027, 2, 9).date())) is None


def test_archiving_member_preserves_past_and_removes_future_assignments(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member_id = state["team"][0]["id"]
    agenda_id = state["agendas"][0]["id"]
    today = madrid_today()
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="past-assignment",
                    date=today - timedelta(days=1),
                    member_id=member_id,
                    agenda_id=agenda_id,
                ),
                Assignment(
                    id="future-assignment",
                    date=today + timedelta(days=1),
                    member_id=member_id,
                    agenda_id=agenda_id,
                ),
            ]
        )

    response = authenticated_client.delete(f"/api/v1/members/{member_id}")

    assert response.status_code == 204
    with database.session_factory() as session:
        assert session.get(Assignment, "past-assignment") is not None
        assert session.get(Assignment, "future-assignment") is None


def test_archiving_agenda_preserves_past_and_removes_future_events(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    member_id = state["team"][0]["id"]
    agenda_id = state["agendas"][0]["id"]
    today = madrid_today()
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add_all(
            [
                Assignment(
                    id="past-agenda-assignment",
                    date=today - timedelta(days=1),
                    member_id=member_id,
                    agenda_id=agenda_id,
                ),
                Assignment(
                    id="future-agenda-assignment",
                    date=today + timedelta(days=1),
                    member_id=member_id,
                    agenda_id=agenda_id,
                ),
                Vacancy(date=today + timedelta(days=2), agenda_id=agenda_id),
            ]
        )

    response = authenticated_client.delete(f"/api/v1/agendas/{agenda_id}")

    assert response.status_code == 204
    with database.session_factory() as session:
        assert session.get(Assignment, "past-agenda-assignment") is not None
        assert session.get(Assignment, "future-agenda-assignment") is None
        assert session.scalar(select(Vacancy).where(Vacancy.agenda_id == agenda_id)) is None
