import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import pinendar.application.jobs as jobs_module
from pinendar.application.jobs import JobDispatcher, enqueue_job
from pinendar.application.state import DomainError, job_payload
from pinendar.infrastructure.models import AppSettings, GenerationJob, Proposal, ProposalGuard


def wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(500):
        body = client.get(f"/api/v1/generation-jobs/{job_id}").json()
        if body["status"] in {"succeeded", "failed", "stale"}:
            return body
        time.sleep(0.02)
    raise AssertionError("Generation job did not finish")


def test_generation_job_creates_current_proposal(authenticated_client: TestClient) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    team = authenticated_client.get("/api/v1/bootstrap").json()["team"]
    absences = [
        {
            "memberId": team[0]["id"],
            "start": "2027-01-01",
            "end": "2027-01-31",
        },
        *[
            {
                "memberId": team[1]["id"],
                "start": value,
                "end": value,
            }
            for value in ("2027-01-01", "2027-01-08", "2027-01-15", "2027-01-22", "2027-01-29")
        ],
    ]
    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-01", "endMonth": "2027-01", "guards": [], "absences": absences},
    )

    assert response.status_code == 202
    job = wait_for_job(authenticated_client, response.json()["id"])
    assert job["status"] == "succeeded"
    proposal = authenticated_client.get("/api/v1/proposals/current").json()
    assert proposal["startMonth"] == "2027-01"
    assert proposal["assignments"]

    overlap = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-01", "endMonth": "2027-02", "guards": [], "absences": []},
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "PERIOD_TOO_LONG"


def test_empty_current_proposal_does_not_block_regeneration(authenticated_client: TestClient) -> None:
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add(
            Proposal(
                id="empty-current-proposal",
                status="current",
                start_month="2027-02",
                end_month="2027-02",
                generated_at=datetime.now(UTC).replace(tzinfo=None),
                input_revision=1,
            )
        )

    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-02", "endMonth": "2027-02", "guards": [], "absences": []},
    )

    assert response.status_code == 202
    with database.session_factory() as session:
        assert session.get(Proposal, "empty-current-proposal") is None


def test_generation_with_excess_people_succeeds_with_no_assignment_events(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    team = authenticated_client.get("/api/v1/bootstrap").json()["team"]
    absences = [
        {
            "memberId": team[0]["id"],
            "start": "2027-01-01",
            "end": "2027-01-31",
        },
        *[
            {
                "memberId": team[1]["id"],
                "start": value,
                "end": value,
            }
            for value in ("2027-01-01", "2027-01-08", "2027-01-15", "2027-01-22", "2027-01-29")
        ],
    ]
    first = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-01", "endMonth": "2027-01", "guards": [], "absences": absences},
    )
    first_job = wait_for_job(authenticated_client, first.json()["id"])
    assert first_job["status"] == "succeeded", first_job
    current_id = authenticated_client.get("/api/v1/proposals/current").json()["id"]

    second = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-02", "endMonth": "2027-02", "guards": [], "absences": []},
    )
    completed = wait_for_job(authenticated_client, second.json()["id"])
    current = authenticated_client.get("/api/v1/proposals/current").json()

    assert completed["status"] == "succeeded"
    assert current["id"] != current_id
    assert any(item["type"] == "no_assignment" for item in current["assignments"])


def test_guard_only_proposal_does_not_reserve_period(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    state = authenticated_client.get("/api/v1/bootstrap").json()
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        proposal = Proposal(
            id="proposal-guard-only-period",
            status="current",
            start_month="2027-03",
            end_month="2027-03",
            generated_at=datetime.now(),
            input_revision=1,
        )
        session.add(proposal)
        session.add(
            ProposalGuard(
                id="guard-only-period",
                proposal_id=proposal.id,
                member_id=state["team"][0]["id"],
                date=date(2027, 3, 12),
            )
        )

    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-03", "endMonth": "2027-03", "guards": [], "absences": []},
    )

    assert response.status_code == 202
    assert wait_for_job(authenticated_client, response.json()["id"])["status"] == "succeeded"
    current = authenticated_client.get("/api/v1/proposals/current").json()
    assert [(item["memberId"], item["date"]) for item in current["conditions"]["guards"]] == [
        (state["team"][0]["id"], "2027-03-12")
    ]


def test_generation_rejects_invalid_month_and_unknown_people(authenticated_client: TestClient) -> None:
    invalid_month = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-13", "endMonth": "2027-13", "guards": [], "absences": []},
    )
    assert invalid_month.status_code == 409
    assert invalid_month.json()["error"]["code"] == "INVALID_PERIOD"

    unknown_person = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "guards": [{"memberId": "missing", "date": "2027-01-01"}],
            "absences": [],
        },
    )
    assert unknown_person.status_code == 404
    assert unknown_person.json()["error"]["code"] == "MEMBER_NOT_FOUND"


def test_generation_accepts_custom_period_and_rejects_more_than_31_days(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2030-04",
            "endMonth": "2030-04",
            "startDate": "2030-04-10",
            "endDate": "2030-04-30",
            "guards": [],
            "absences": [],
        },
    )

    assert response.status_code == 202
    assert wait_for_job(authenticated_client, response.json()["id"])["status"] == "succeeded"
    proposal = authenticated_client.get("/api/v1/proposals/current").json()
    assert proposal["startDate"] == "2030-04-10"
    assert proposal["endDate"] == "2030-04-30"
    generated_dates = [
        item["date"]
        for item in [*proposal["assignments"], *proposal["unfilled"]]
    ]
    assert generated_dates
    assert all("2030-04-10" <= value <= "2030-04-30" for value in generated_dates)

    too_long = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2031-01",
            "endMonth": "2031-02",
            "startDate": "2031-01-01",
            "endDate": "2031-02-01",
            "guards": [],
            "absences": [],
        },
    )
    assert too_long.status_code == 409
    assert too_long.json()["error"]["code"] == "PERIOD_TOO_LONG"


def test_overlapping_jobs_are_admitted_atomically(client: TestClient) -> None:
    database = client.app.state.database
    catalog = client.app.state.catalog
    payload = {"startMonth": "2027-01", "endMonth": "2027-01", "guards": [], "absences": []}
    ready = threading.Barrier(2)

    def submit() -> str:
        ready.wait()
        try:
            enqueue_job(database, catalog, payload)
            return "queued"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))

    assert sorted(results) == ["PERIOD_OVERLAP", "queued"]
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(GenerationJob)) == 1


def test_generation_job_persists_its_reproducible_random_seed(client: TestClient) -> None:
    database = client.app.state.database
    job = enqueue_job(
        database,
        client.app.state.catalog,
        {"startMonth": "2029-01", "endMonth": "2029-01", "guards": [], "absences": []},
        {"randomSeed": 17},
    )

    with database.session_factory() as session:
        stored = session.get(GenerationJob, job["id"])
        snapshot = json.loads(stored.input_snapshot)

    expected = (int(job["id"][:8], 16) ^ 17) % 2_147_483_647 or 1
    assert snapshot["solver_config"]["randomSeed"] == expected


def test_generation_job_only_accepts_fairness_optimization_mode(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2029-02",
            "endMonth": "2029-02",
            "guards": [],
            "absences": [],
        },
    )

    assert response.status_code == 202
    assert response.json()["optimizationMode"] == "fairness"
    database = authenticated_client.app.state.database
    with database.session_factory() as session:
        stored = session.get(GenerationJob, response.json()["id"])
        snapshot = json.loads(stored.input_snapshot)
    assert snapshot["solver_config"]["optimizationMode"] == "fairness"

    invalid = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2029-03",
            "endMonth": "2029-03",
            "guards": [],
            "absences": [],
            "optimizationMode": "happiness",
        },
    )
    assert invalid.status_code == 422


def test_proposal_guard_before_period_creates_post_guard_absence(authenticated_client: TestClient) -> None:
    database = authenticated_client.app.state.database
    team = authenticated_client.get("/api/v1/bootstrap").json()["team"]
    with database.session_factory.begin() as session:
        proposal = Proposal(
            id="prior-proposal",
            status="historical",
            start_month="2026-12",
            end_month="2026-12",
            generated_at=datetime(2026, 12, 1, tzinfo=UTC).replace(tzinfo=None),
            archived_at=datetime(2026, 12, 31, tzinfo=UTC).replace(tzinfo=None),
            input_revision=1,
        )
        session.add(proposal)
        session.add(
            ProposalGuard(
                id="prior-guard",
                proposal_id=proposal.id,
                member_id=team[0]["id"],
                date=date(2026, 12, 31),
            )
        )

    authenticated_client.app.state.job_dispatcher.start()
    absences = [
        {
            "memberId": team[2]["id"],
            "start": "2027-01-01",
            "end": "2027-01-31",
        },
        *[
            {
                "memberId": team[0]["id"],
                "start": value,
                "end": value,
            }
            for value in ("2027-01-08", "2027-01-15", "2027-01-22", "2027-01-29")
        ],
    ]
    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-01", "endMonth": "2027-01", "guards": [], "absences": absences},
    )

    assert response.status_code == 202
    job = wait_for_job(authenticated_client, response.json()["id"])
    assert job["status"] == "succeeded", job
    assignments = authenticated_client.get("/api/v1/proposals/current").json()["assignments"]
    assert not any(item["memberId"] == team[0]["id"] and item["date"] == "2027-01-01" for item in assignments)


def test_generation_rejects_guard_already_stored_in_proposal(authenticated_client: TestClient) -> None:
    database = authenticated_client.app.state.database
    member_id = authenticated_client.get("/api/v1/bootstrap").json()["team"][0]["id"]
    with database.session_factory.begin() as session:
        proposal = Proposal(
            id="proposal-with-guard",
            status="historical",
            start_month="2027-01",
            end_month="2027-01",
            generated_at=datetime(2027, 1, 1, tzinfo=UTC).replace(tzinfo=None),
            archived_at=datetime(2027, 1, 31, tzinfo=UTC).replace(tzinfo=None),
            input_revision=1,
        )
        session.add(proposal)
        session.add(
            ProposalGuard(
                id="stored-guard",
                proposal_id=proposal.id,
                member_id=member_id,
                date=date(2027, 1, 4),
            )
        )

    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "guards": [{"memberId": member_id, "date": "2027-01-04"}],
            "absences": [],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "DUPLICATE_GUARD_DATE",
        "message": "Ja hi ha una guàrdia registrada el 2027-01-04",
        "field": "guards",
        "details": {"date": "2027-01-04"},
    }


def test_job_payload_tolerates_corrupt_result_json() -> None:
    job = GenerationJob(
        id="corrupt-job",
        status="failed",
        start_month="2027-01",
        end_month="2027-01",
        input_revision=1,
        input_snapshot="{}",
        result_json="{not-json",
        error_code="SCHEDULER_ERROR",
        error_message="Error controlat",
        created_at=datetime(2027, 1, 1),
    )

    assert job_payload(job)["error"] == {
        "code": "SCHEDULER_ERROR",
        "message": "Error controlat",
        "field": None,
        "details": {},
    }


def test_dispatcher_stop_waits_until_active_failure_is_persisted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = client.app.state.database
    started = threading.Event()
    release = threading.Event()
    stopped = threading.Event()

    def failing_solver(_snapshot: dict[str, Any]) -> dict[str, Any]:
        started.set()
        assert release.wait(timeout=2)
        raise RuntimeError("expected test failure")

    monkeypatch.setattr(jobs_module, "solve_snapshot", failing_solver)
    with database.session_factory.begin() as session:
        settings = session.get(AppSettings, 1)
        assert settings
        session.add(
            GenerationJob(
                id="active-on-stop",
                status="queued",
                start_month="2027-01",
                end_month="2027-01",
                input_revision=settings.planning_revision,
                input_snapshot="{}",
            )
        )

    dispatcher = JobDispatcher(database, process_pool=False)
    dispatcher.start()
    assert started.wait(timeout=2)

    def stop_dispatcher() -> None:
        dispatcher.stop()
        stopped.set()

    stopper = threading.Thread(target=stop_dispatcher)
    stopper.start()
    assert not stopped.wait(timeout=0.05)
    release.set()
    assert stopped.wait(timeout=2)
    stopper.join()

    with database.session_factory() as session:
        job = session.get(GenerationJob, "active-on-stop")
        assert job
        assert job.status == "failed"
        assert job.error_code == "SCHEDULER_ERROR"
        assert job.completed_at is not None
