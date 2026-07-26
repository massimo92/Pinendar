from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from pinendar.infrastructure.models import Assignment, Proposal


def test_fairness_averages_person_profiles_without_tenure_weight(authenticated_client: TestClient) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    first, second = state["team"][:2]
    agenda_a, agenda_b = state["agendas"][:2]
    with authenticated_client.app.state.database.session_factory.begin() as session:
        proposal = Proposal(
            id="fairness-history",
            status="historical",
            start_month="2025-01",
            end_month="2025-01",
            generated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(proposal)
        session.flush()
        day = date(2025, 1, 1)
        profiles = {
            first["id"]: [agenda_a["id"]] * 6 + [agenda_b["id"]] * 4,
            second["id"]: [agenda_a["id"]] + [agenda_b["id"]] * 4,
        }
        for member_id, agenda_ids in profiles.items():
            for index, agenda_id in enumerate(agenda_ids):
                session.add(
                    Assignment(
                        id=f"{member_id}-{index}",
                        proposal_id=proposal.id,
                        date=day + timedelta(days=index),
                        member_id=member_id,
                        agenda_id=agenda_id,
                    )
                )
        session.add(
            Assignment(
                id="management-first",
                proposal_id=proposal.id,
                date=day + timedelta(days=20),
                member_id=first["id"],
                kind="management",
                management=True,
            )
        )

    response = authenticated_client.get("/api/v1/fairness")

    assert response.status_code == 200
    body = response.json()
    assert body["agendaMeanBasisPoints"][agenda_a["id"]] == 4000
    people = {item["memberId"]: item for item in body["people"]}
    assert people[first["id"]]["agendaPercentages"][agenda_a["id"]] == 0.6
    assert people[second["id"]]["agendaPercentages"][agenda_a["id"]] == 0.2
    assert people[first["id"]]["total"] == 10
    assert people[first["id"]]["managementDays"] == 1
    assert people[first["id"]]["activityCounts"]["management"] == 1
    assert people[first["id"]]["activityTotal"] == 11
    assert people[first["id"]]["activityPercentages"]["management"] == 1 / 11
