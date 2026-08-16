import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import pinendar.application.jobs as jobs_module
from pinendar.application.jobs import JobDispatcher, enqueue_job
from pinendar.application.state import DomainError, job_payload
from pinendar.infrastructure.models import (
    AppSettings,
    Assignment,
    GenerationJob,
    Guard,
    Member,
)


def wait_for_job(client: TestClient, job_id: str) -> dict:
    for _ in range(2000):
        body = client.get(f"/api/v1/generation-jobs/{job_id}").json()
        if body["status"] in {"succeeded", "failed", "stale"}:
            return body
        time.sleep(0.02)
    raise AssertionError("Generation job did not finish")


def test_generation_job_creates_calendar_events(authenticated_client: TestClient) -> None:
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
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    assert calendar["events"]
    assert all(item["date"].startswith("2027-01") for item in calendar["events"])

    overlap = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-01", "endMonth": "2027-02", "guards": [], "absences": []},
    )
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "PERIOD_TOO_LONG"


def test_empty_period_does_not_block_generation(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-02", "endMonth": "2027-02", "guards": [], "absences": []},
    )

    assert response.status_code == 202


def test_generation_with_excess_people_succeeds_with_no_assignment_events(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.settings.scheduler_time_limit_seconds = 30
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
    january = [
        item["id"]
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
    ]

    second = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={"startMonth": "2027-02", "endMonth": "2027-02", "guards": [], "absences": []},
    )
    completed = wait_for_job(authenticated_client, second.json()["id"])
    events = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]

    assert completed["status"] == "succeeded"
    assert set(january).issubset({item["id"] for item in events})
    assert any(item["type"] == "no_assignment" for item in events)
    assert any(item["date"].startswith("2027-02") for item in events)


def test_regeneration_requires_confirmation_and_preserves_manual_events(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    payload = {
        "startMonth": "2032-01",
        "endMonth": "2032-01",
        "guards": [],
        "absences": [],
    }
    first = authenticated_client.post("/api/v1/generation-jobs", json=payload)
    assert wait_for_job(authenticated_client, first.json()["id"])["status"] == "succeeded"
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    event = next(
        item
        for item in calendar["events"]
        if item["date"].startswith("2032-01")
        and item["type"] not in {"management", "no_assignment"}
    )
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        stored = session.get(Assignment, event["id"])
        assert stored is not None
        stored.locked = True
        stored.manually_modified = True
    unchanged_ids = {
        item["id"]
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
        if item["date"].startswith("2032-01")
    }

    conflict = authenticated_client.post("/api/v1/generation-jobs", json=payload)

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "PERIOD_OVERLAP"
    assert conflict.json()["error"]["details"]["canReplace"] is True
    assert conflict.json()["error"]["details"]["preservedManualEvents"] == 1
    after_conflict_ids = {
        item["id"]
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
        if item["date"].startswith("2032-01")
    }
    assert after_conflict_ids == unchanged_ids

    replacement = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={**payload, "replaceExisting": True},
    )
    assert replacement.status_code == 202
    completed = wait_for_job(authenticated_client, replacement.json()["id"])
    assert completed["status"] == "succeeded", completed
    regenerated = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
    preserved = next(item for item in regenerated if item["id"] == event["id"])
    assert preserved["locked"] is True
    assert preserved["manuallyModified"] is True
    assert preserved["date"] == event["date"]
    assert preserved["memberId"] == event["memberId"]
    assert preserved["type"] == event["type"]


def test_impossible_preserved_change_fails_without_modifying_the_range(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    payload = {
        "startMonth": "2032-02",
        "endMonth": "2032-02",
        "guards": [],
        "absences": [],
    }
    first = authenticated_client.post("/api/v1/generation-jobs", json=payload)
    assert wait_for_job(authenticated_client, first.json()["id"])["status"] == "succeeded"
    database = authenticated_client.app.state.database
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    clinical = next(
        item
        for item in calendar["events"]
        if item["date"].startswith("2032-02")
        and item["type"] not in {"management", "no_assignment"}
    )
    with database.session_factory.begin() as session:
        for row in session.scalars(
            select(Assignment).where(
                Assignment.date == date.fromisoformat(clinical["date"]),
                Assignment.member_id == clinical["memberId"],
            )
        ):
            row.locked = True
            row.manually_modified = True
        session.add(
            Assignment(
                id="impossible-locked-unassigned",
                date=date.fromisoformat(clinical["date"]),
                member_id=clinical["memberId"],
                kind="no_assignment",
                load_percentage=0,
                locked=True,
                manually_modified=True,
            )
        )
    before = {
        item["id"]: item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
        if item["date"].startswith("2032-02")
    }

    replacement = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={**payload, "replaceExisting": True},
    )
    completed = wait_for_job(authenticated_client, replacement.json()["id"])

    assert completed["status"] == "failed"
    after = {
        item["id"]: item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
        if item["date"].startswith("2032-02")
    }
    assert after == before


def test_partial_regeneration_changes_only_the_confirmed_dates(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    base = {
        "startMonth": "2033-01",
        "endMonth": "2033-01",
        "guards": [],
        "absences": [],
    }
    for start, end in (("2033-01-01", "2033-01-10"), ("2033-01-11", "2033-01-20")):
        queued = authenticated_client.post(
            "/api/v1/generation-jobs",
            json={**base, "startDate": start, "endDate": end},
        )
        assert queued.status_code == 202
        assert wait_for_job(authenticated_client, queued.json()["id"])["status"] == "succeeded"
    before = {
        item["id"]: item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
        if item["date"].startswith("2033-01")
    }
    outside_before = {
        item_id: item
        for item_id, item in before.items()
        if not "2033-01-05" <= item["date"] <= "2033-01-07"
    }

    replacement = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            **base,
            "startDate": "2033-01-05",
            "endDate": "2033-01-07",
            "replaceExisting": True,
        },
    )
    assert replacement.status_code == 202
    assert wait_for_job(authenticated_client, replacement.json()["id"])["status"] == "succeeded"
    after = {
        item["id"]: item
        for item in authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
        if item["date"].startswith("2033-01")
    }
    outside_after = {
        item_id: item
        for item_id, item in after.items()
        if not "2033-01-05" <= item["date"] <= "2033-01-07"
    }

    assert outside_after == outside_before
    assert any("2033-01-05" <= item["date"] <= "2033-01-07" for item in after.values())


def test_guard_does_not_reserve_period(
    authenticated_client: TestClient,
) -> None:
    authenticated_client.app.state.job_dispatcher.start()
    state = authenticated_client.get("/api/v1/bootstrap").json()
    database = authenticated_client.app.state.database
    with database.session_factory.begin() as session:
        session.add(
            Guard(
                id="guard-only-period",
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
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    assert [(item["memberId"], item["date"]) for item in calendar["guards"]] == [
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
    calendar = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]
    generated_dates = [
        item["date"]
        for item in [*calendar["events"], *calendar["vacancies"]]
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
    assert response.json()["timeLimitSeconds"] == 20
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


def test_generation_job_accepts_a_user_time_limit_between_one_and_thirty_minutes(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2029-04",
            "endMonth": "2029-04",
            "guards": [],
            "absences": [],
            "timeLimitMinutes": 30,
        },
    )

    assert response.status_code == 202
    assert response.json()["timeLimitSeconds"] == 1800
    database = authenticated_client.app.state.database
    with database.session_factory() as session:
        stored = session.get(GenerationJob, response.json()["id"])
        snapshot = json.loads(stored.input_snapshot)
    assert snapshot["solver_config"]["timeLimitSeconds"] == 1800

    for invalid_minutes in (0, 31):
        invalid = authenticated_client.post(
            "/api/v1/generation-jobs",
            json={
                "startMonth": "2029-05",
                "endMonth": "2029-05",
                "guards": [],
                "absences": [],
                "timeLimitMinutes": invalid_minutes,
            },
        )
        assert invalid.status_code == 422


def test_successful_first_generation_consumes_new_member_equity_exception(
    authenticated_client: TestClient,
) -> None:
    state = authenticated_client.get("/api/v1/bootstrap").json()
    template = state["team"][0]
    created = authenticated_client.post(
        "/api/v1/members",
        json={
            "name": "New Generation Member",
            "email": "new-generation@hospital.test",
            "workPattern": template["workPattern"],
            "allowedTypes": template["allowedTypes"],
            "managementQuota": 0,
            "fixedRules": [],
        },
    )
    assert created.status_code == 201
    member_id = created.json()["id"]
    database = authenticated_client.app.state.database
    with database.session_factory() as session:
        member_row = session.get(Member, member_id)
        assert member_row is not None
        assert member_row.has_completed_generation is False

    authenticated_client.app.state.job_dispatcher.start()
    queued = authenticated_client.post(
        "/api/v1/generation-jobs",
        json={
            "startMonth": "2027-01",
            "endMonth": "2027-01",
            "startDate": "2027-01-02",
            "endDate": "2027-01-02",
            "guards": [],
            "absences": [],
        },
    )
    assert queued.status_code == 202
    with database.session_factory() as session:
        stored = session.get(GenerationJob, queued.json()["id"])
        assert stored is not None
        snapshot = json.loads(stored.input_snapshot)
        assert snapshot["first_generation_member_ids"] == [member_id]

    completed = wait_for_job(authenticated_client, queued.json()["id"])

    assert completed["status"] == "succeeded"
    with database.session_factory() as session:
        member_row = session.get(Member, member_id)
        assert member_row is not None
        assert member_row.has_completed_generation is True


def test_failed_generation_does_not_consume_new_member_equity_exception(
    client: TestClient,
) -> None:
    database = client.app.state.database
    with database.session_factory.begin() as session:
        member_row = session.scalar(select(Member).limit(1))
        assert member_row is not None
        member_row.has_completed_generation = False
    job = enqueue_job(
        database,
        client.app.state.catalog,
        {
            "startMonth": "2029-05",
            "endMonth": "2029-05",
            "guards": [],
            "absences": [],
        },
    )

    JobDispatcher(database, process_pool=False)._complete(
        job["id"],
        {
            "outcome": "infeasible",
            "error": {"code": "TEST_FAILURE", "message": "expected"},
        },
    )

    with database.session_factory() as session:
        member_row = session.scalar(select(Member).limit(1))
        assert member_row is not None
        assert member_row.has_completed_generation is False


def test_guard_before_period_creates_post_guard_absence(authenticated_client: TestClient) -> None:
    database = authenticated_client.app.state.database
    team = authenticated_client.get("/api/v1/bootstrap").json()["team"]
    with database.session_factory.begin() as session:
        session.add(
            Guard(
                id="prior-guard",
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
    assignments = authenticated_client.get("/api/v1/bootstrap").json()["calendar"]["events"]
    assert not any(item["memberId"] == team[0]["id"] and item["date"] == "2027-01-01" for item in assignments)


def test_generation_reuses_guard_already_stored(authenticated_client: TestClient) -> None:
    database = authenticated_client.app.state.database
    member_id = authenticated_client.get("/api/v1/bootstrap").json()["team"][0]["id"]
    with database.session_factory.begin() as session:
        session.add(
            Guard(
                id="stored-guard",
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

    assert response.status_code == 202


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
