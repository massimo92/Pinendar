from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from pinendar.infrastructure.models import (
    Agenda,
    AgendaRecurrence,
    Assignment,
    Coverage,
    Guard,
    GuardTransfer,
    Member,
    MemberAvailableDay,
    MemberCapability,
)


def _guard_fixture(authenticated_client: TestClient) -> dict[str, str]:
    database = authenticated_client.app.state.database
    hospital_id = authenticated_client.get("/api/v1/bootstrap").json()["hospitals"][0][
        "catalogId"
    ]
    with database.session_factory.begin() as session:
        session.execute(update(Coverage).where(Coverage.weekday == 2).values(slots=0))
        session.execute(delete(AgendaRecurrence).where(AgendaRecurrence.weekday == 2))
        session.add_all(
            [
                Agenda(
                    id="guard-base",
                    name="Guard base",
                    hospital_catalog_id=hospital_id,
                    telematic=False,
                    shift="morning",
                    color="hsl(10 90% 56%)",
                    priority=1,
                    load_percentage=100,
                ),
                Agenda(
                    id="guard-extra",
                    name="Guard extra",
                    hospital_catalog_id=hospital_id,
                    telematic=False,
                    shift="morning",
                    color="hsl(20 90% 56%)",
                    priority=4,
                    load_percentage=100,
                ),
                Coverage(agenda_id="guard-base", weekday=2, slots=1),
            ]
        )
        for member_id, name in (("guard-owner", "Guard owner"), ("guard-backup", "Guard backup")):
            session.add(
                Member(
                    id=member_id,
                    name=name,
                    normalized_name=member_id,
                    email=f"{member_id}@test.invalid",
                    normalized_email=f"{member_id}@test.invalid",
                    color="hsl(30 58% 78%)",
                    management_quota=0,
                    is_active=True,
                    work_pattern_weeks=1,
                )
            )
            session.add(
                MemberAvailableDay(member_id=member_id, week_index=0, weekday=2)
            )
            session.add_all(
                [
                    MemberCapability(member_id=member_id, agenda_id="guard-base"),
                    MemberCapability(member_id=member_id, agenda_id="guard-extra"),
                ]
            )
        session.add_all(
            [
                Assignment(
                    id="guard-owner-base",
                    date=date(2026, 8, 11),
                    member_id="guard-owner",
                    agenda_id="guard-base",
                ),
                Assignment(
                    id="guard-backup-extra",
                    date=date(2026, 8, 11),
                    member_id="guard-backup",
                    agenda_id="guard-extra",
                    extra=True,
                    locked=True,
                ),
            ]
        )
    revision = authenticated_client.get("/api/v1/bootstrap").json()["planningRevision"]
    return {"revision": str(revision)}


def test_external_guard_cession_repairs_base_before_extra_and_records_history(
    authenticated_client: TestClient,
) -> None:
    fixture = _guard_fixture(authenticated_client)
    payload = {
        "date": "2026-08-10",
        "toMemberId": "guard-owner",
        "expectedRevision": int(fixture["revision"]),
    }

    preview = authenticated_client.post(
        "/api/v1/guard-cessions/preview", json=payload
    )
    applied = authenticated_client.post(
        "/api/v1/guard-cessions", json=payload
    )

    assert preview.status_code == 200
    assert applied.status_code == 201
    assert applied.json()["impact"] == preview.json()["impact"]
    database = authenticated_client.app.state.database
    with database.session_factory() as session:
        guard = session.scalar(
            select(Guard)
        )
        assert guard and guard.member_id == "guard-owner"
        owner_rows = list(
            session.scalars(
                select(Assignment).where(
                    Assignment.date == date(2026, 8, 11),
                    Assignment.member_id == "guard-owner",
                )
            )
        )
        assert owner_rows == []
        backup_rows = list(
            session.scalars(
                select(Assignment).where(
                    Assignment.date == date(2026, 8, 11),
                    Assignment.member_id == "guard-backup",
                )
            )
        )
        assert [(item.agenda_id, item.extra) for item in backup_rows] == [
            ("guard-base", False)
        ]
        transfer = session.scalar(select(GuardTransfer))
        assert transfer
        assert transfer.from_member_id is None
        assert transfer.to_member_id == "guard-owner"


def test_exchange_with_exterior_removes_internal_guard_without_a_new_date(
    authenticated_client: TestClient,
) -> None:
    fixture = _guard_fixture(authenticated_client)
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add(
            Guard(
                id="guard-to-move",
                member_id="guard-owner",
                date=date(2026, 8, 10),
            )
        )

    response = authenticated_client.post(
        "/api/v1/guard-exchanges",
        json={
            "firstGuardId": "guard-to-move",
            "firstDate": "2026-08-10",
            "expectedRevision": int(fixture["revision"]),
        },
    )

    assert response.status_code == 201
    with database.session_factory() as session:
        guard = session.get(Guard, "guard-to-move")
        assert guard is None
        transfers = list(
            session.scalars(
                select(GuardTransfer).order_by(GuardTransfer.guard_date)
            )
        )
        assert len(transfers) == 1
        assert [
            (item.from_member_id, item.to_member_id)
            for item in transfers
        ] == [("guard-owner", None)]


def test_guard_operation_rejects_a_stale_revision(
    authenticated_client: TestClient,
) -> None:
    _guard_fixture(authenticated_client)

    response = authenticated_client.post(
        "/api/v1/guard-cessions",
        json={
            "date": "2026-08-10",
            "toMemberId": "guard-owner",
            "expectedRevision": 999,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PLANNING_REVISION_CONFLICT"
