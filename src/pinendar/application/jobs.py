from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import UTC, date, datetime
from multiprocessing import get_context
from typing import Any

from sqlalchemy import delete, or_, select, update
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from pinendar.application.state import (
    DomainError,
    bootstrap,
    job_payload,
    month_end,
    uid,
)
from pinendar.domain.scheduler import ScheduleProblem
from pinendar.infrastructure.catalog import HospitalCatalog
from pinendar.infrastructure.cp_sat_scheduler import solve_snapshot, validate_solution
from pinendar.infrastructure.database import Database
from pinendar.infrastructure.models import (
    Absence,
    Agenda,
    AppSettings,
    Assignment,
    GenerationJob,
    Guard,
    Member,
    Vacancy,
)

TERMINAL_JOB_STATES = {"succeeded", "failed", "stale"}
logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def period_bounds(
    start_month: str,
    end_month: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[date, date]:
    return (
        date.fromisoformat(start_date or f"{start_month}-01"),
        date.fromisoformat(end_date) if end_date else month_end(end_month),
    )


def periods_overlap(
    left_start: str,
    left_end: str,
    right_start: str,
    right_end: str,
    left_start_date: str | None = None,
    left_end_date: str | None = None,
    right_start_date: str | None = None,
    right_end_date: str | None = None,
) -> bool:
    left_bounds = period_bounds(left_start, left_end, left_start_date, left_end_date)
    right_bounds = period_bounds(right_start, right_end, right_start_date, right_end_date)
    return left_bounds[0] <= right_bounds[1] and right_bounds[0] <= left_bounds[1]


def validate_generation_request(session: Session, payload: dict[str, Any]) -> None:
    start = payload["startMonth"]
    end = payload["endMonth"]
    requested_start_date = payload.get("startDate")
    requested_end_date = payload.get("endDate")
    optimization_mode = payload.get("optimizationMode", "fairness")
    if optimization_mode != "fairness":
        raise DomainError(
            "INVALID_OPTIMIZATION_MODE",
            "El mode d’optimització no és vàlid",
            field="optimizationMode",
        )
    try:
        date.fromisoformat(f"{start}-01")
        date.fromisoformat(f"{end}-01")
    except ValueError as error:
        raise DomainError("INVALID_PERIOD", "El període seleccionat no és vàlid", field="startMonth") from error
    if bool(requested_start_date) != bool(requested_end_date):
        raise DomainError("INVALID_PERIOD", "Cal indicar la data inicial i la final", field="startDate")
    start_date, end_date = period_bounds(start, end, requested_start_date, requested_end_date)
    if end_date < start_date:
        raise DomainError("INVALID_PERIOD", "La data final no pot ser anterior a la inicial", field="endDate")
    if start_date.strftime("%Y-%m") != start or end_date.strftime("%Y-%m") != end:
        raise DomainError("INVALID_PERIOD", "Les dates no coincideixen amb els mesos indicats", field="startDate")
    if start_date.strftime("%Y-%m") != end_date.strftime("%Y-%m"):
        raise DomainError(
            "PERIOD_TOO_LONG",
            "Les dues dates han de pertànyer al mateix mes",
            field="endDate",
        )
    if (end_date - start_date).days + 1 > 31:
        raise DomainError("PERIOD_TOO_LONG", "El període pot tenir un màxim de 31 dies", field="endDate")
    bounds_start = start_date.isoformat()
    bounds_end = end_date.isoformat()
    active_member_ids = set(
        session.scalars(select(Member.id).where(Member.archived_at.is_(None), Member.is_active.is_(True)))
    )
    persisted_guards = {
        item.date.isoformat(): item.member_id
        for item in session.scalars(
            select(Guard).where(Guard.date >= start_date, Guard.date <= end_date)
        )
    }
    guard_dates: set[str] = set()
    for guard in payload.get("guards", []):
        if guard["memberId"] not in active_member_ids:
            raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="guards")
        if guard["date"] < bounds_start or guard["date"] > bounds_end:
            raise DomainError(
                "GUARD_OUTSIDE_PERIOD", "Les guàrdies han d’estar dins del període del calendari", field="guards"
            )
        if guard["date"] in guard_dates:
            raise DomainError(
                "DUPLICATE_GUARD_DATE", f"Només hi pot haver una persona de guàrdia el {guard['date']}", field="guards"
            )
        if (
            guard["date"] in persisted_guards
            and persisted_guards[guard["date"]] != guard["memberId"]
        ):
            raise DomainError(
                "DUPLICATE_GUARD_DATE",
                f"Ja hi ha una guàrdia registrada el {guard['date']}",
                field="guards",
                details={"date": guard["date"]},
            )
        guard_dates.add(guard["date"])
    for absence in payload.get("absences", []):
        if absence["memberId"] not in active_member_ids:
            raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="absences")
        if absence["start"] < bounds_start or absence["end"] > bounds_end or absence["end"] < absence["start"]:
            raise DomainError(
                "ABSENCE_OUTSIDE_PERIOD", "Les vacances han d’estar dins del període del calendari", field="absences"
            )
    existing_events = int(
        session.scalar(
            select(sa_func.count())
            .select_from(Assignment)
            .where(Assignment.date >= start_date, Assignment.date <= end_date)
        )
        or 0
    )
    existing_vacancies = int(
        session.scalar(
            select(sa_func.count())
            .select_from(Vacancy)
            .where(Vacancy.date >= start_date, Vacancy.date <= end_date)
        )
        or 0
    )
    if (existing_events or existing_vacancies) and not payload.get("replaceExisting"):
        locked_events = int(
            session.scalar(
                select(sa_func.count())
                .select_from(Assignment)
                .where(
                    Assignment.date >= start_date,
                    Assignment.date <= end_date,
                    or_(
                        Assignment.locked.is_(True),
                        Assignment.extra.is_(True),
                        Assignment.manually_modified.is_(True),
                    ),
                )
            )
            or 0
        )
        raise DomainError(
            "PERIOD_OVERLAP",
            "El període ja conté esdeveniments",
            details={
                "startDate": bounds_start,
                "endDate": bounds_end,
                "events": existing_events,
                "vacancies": existing_vacancies,
                "preservedManualEvents": locked_events,
                "canReplace": True,
            },
        )
    for job in session.scalars(select(GenerationJob).where(GenerationJob.status.in_(["queued", "running"]))):
        if periods_overlap(
            start,
            end,
            job.start_month,
            job.end_month,
            bounds_start,
            bounds_end,
            job.start_date.isoformat() if job.start_date else None,
            job.end_date.isoformat() if job.end_date else None,
        ):
            raise DomainError("PERIOD_OVERLAP", "Ja hi ha una generació en curs per aquest període")


def build_problem(
    session: Session,
    catalog: HospitalCatalog,
    payload: dict[str, Any],
    solver_config: dict[str, Any] | None = None,
) -> ScheduleProblem:
    state = bootstrap(session, catalog)
    planning_team = [member for member in state["team"] if member.get("active", True)]
    calendar = state["calendar"]
    historical_guards = list(calendar["guards"])
    requested_start, requested_end = period_bounds(
        payload["startMonth"],
        payload["endMonth"],
        payload.get("startDate"),
        payload.get("endDate"),
    )
    historical_counts = {member["id"]: {agenda["id"]: 0 for agenda in state["agendas"]} for member in planning_team}
    load_units = {agenda["id"]: int(agenda.get("loadPercentage", 100)) // 50 for agenda in state["agendas"]}
    for event in calendar["events"]:
        event_date = date.fromisoformat(event["date"])
        if requested_start <= event_date <= requested_end:
            continue
        if (
            event["type"] != "no_assignment"
            and event["memberId"] in historical_counts
            and event["type"] in historical_counts[event["memberId"]]
        ):
            historical_counts[event["memberId"]][event["type"]] += (
                int(event.get("loadPercentage", load_units[event["type"]] * 50)) // 50
            )
    absences = [
        item
        for item in calendar["absences"]
        if item["start"] <= requested_end.isoformat()
        and item["end"] >= requested_start.isoformat()
    ]
    known_absences = {
        (item["memberId"], item.get("category", "vacances"), item["start"], item["end"])
        for item in absences
    }
    for item in payload.get("absences", []):
        key = (item["memberId"], item.get("category", "vacances"), item["start"], item["end"])
        if key not in known_absences:
            absences.append(item)
            known_absences.add(key)
    return ScheduleProblem(
        schema_version=8,
        planning_revision=state["planningRevision"],
        start_month=payload["startMonth"],
        end_month=payload["endMonth"],
        team=planning_team,
        agendas=state["agendas"],
        coverage=state["coverage"],
        holidays=state["holidays"],
        guards=historical_guards,
        conditions={"guards": payload.get("guards", []), "absences": absences},
        historical_counts=historical_counts,
        locked_assignments=payload.get("lockedAssignments", []),
        start_date=payload.get("startDate"),
        end_date=payload.get("endDate"),
        solver_config=solver_config or {},
    )


def enqueue_job(
    database: Database,
    catalog: HospitalCatalog,
    payload: dict[str, Any],
    solver_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # SQLite deployment is deliberately single-container, but requests can still
    # run in parallel threads. BEGIN IMMEDIATE reserves the writer before checking
    # overlaps, so two requests cannot both observe the same period as available.
    with database.engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        with Session(bind=connection, expire_on_commit=False) as session:
            try:
                validate_generation_request(session, payload)
                payload_start, payload_end = period_bounds(
                    payload["startMonth"],
                    payload["endMonth"],
                    payload.get("startDate"),
                    payload.get("endDate"),
                )
                locked_assignments = [
                    {
                        "id": item.id,
                        "date": item.date.isoformat(),
                        "memberId": item.member_id,
                        "type": (
                            item.agenda_id
                            or (
                                "management"
                                if item.kind == "management" or item.management
                                else "no_assignment"
                            )
                        ),
                        "locked": True,
                        **({"fixed": True} if item.fixed else {}),
                        **({"extra": True} if item.extra else {}),
                        **({"peonada": True} if item.peonada else {}),
                        **(
                            {"deferredOriginDate": item.deferred_origin_date.isoformat()}
                            if item.deferred_origin_date
                            else {}
                        ),
                        **({"manuallyModified": True} if item.manually_modified else {}),
                        **({"management": True} if item.management else {}),
                    }
                    for item in session.scalars(
                        select(Assignment).where(
                            Assignment.date >= payload_start,
                            Assignment.date <= payload_end,
                            or_(
                                Assignment.locked.is_(True),
                                Assignment.extra.is_(True),
                                Assignment.manually_modified.is_(True),
                            ),
                        )
                    )
                ]
                payload = {**payload, "lockedAssignments": locked_assignments}
                job_id = uid()
                effective_solver_config = dict(solver_config or {})
                effective_solver_config["optimizationMode"] = "fairness"
                effective_solver_config["replaceExisting"] = bool(payload.get("replaceExisting"))
                base_seed = int(effective_solver_config.get("randomSeed", 1))
                effective_solver_config["randomSeed"] = (int(job_id[:8], 16) ^ base_seed) % 2_147_483_647 or 1
                problem = build_problem(session, catalog, payload, effective_solver_config)
                job = GenerationJob(
                    id=job_id,
                    status="queued",
                    start_month=problem.start_month,
                    end_month=problem.end_month,
                    start_date=date.fromisoformat(problem.start_date) if problem.start_date else None,
                    end_date=date.fromisoformat(problem.end_date) if problem.end_date else None,
                    input_revision=problem.planning_revision,
                    input_snapshot=json.dumps(problem.to_dict(), ensure_ascii=False),
                )
                session.add(job)
                session.flush()
                response = job_payload(job)
                connection.commit()
                return response
            except Exception:
                connection.rollback()
                raise


class JobDispatcher:
    def __init__(self, database: Database, *, process_pool: bool = True):
        self.database = database
        self.process_pool = process_pool
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor: Executor | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        with self.database.session_factory.begin() as session:
            session.execute(
                update(GenerationJob).where(GenerationJob.status == "running").values(status="queued", started_at=None)
            )
        self._stop.clear()
        self._executor = self._new_executor()
        self._thread = threading.Thread(target=self._loop, name="pinendar-jobs", daemon=True)
        self._thread.start()
        self._wake.set()

    def notify(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        # The solver has its own deadline. Wait for the dispatcher to persist the
        # active result before stopping its executor; queued jobs remain durable.
        if thread and thread is not threading.current_thread():
            thread.join()
        executor = self._executor
        if executor:
            executor.shutdown(wait=True, cancel_futures=False)
        self._thread = None
        self._executor = None

    def is_alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _new_executor(self) -> Executor:
        if self.process_pool:
            return ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
        return ThreadPoolExecutor(max_workers=1)

    def _replace_broken_executor(self) -> None:
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = self._new_executor()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self._claim_next()
            if not job:
                self._wake.wait(timeout=1)
                self._wake.clear()
                continue
            try:
                assert self._executor is not None
                result = self._executor.submit(solve_snapshot, json.loads(job.input_snapshot)).result()
                self._complete(job.id, result)
            except BrokenProcessPool as error:  # pragma: no cover - operating-system boundary
                self._fail(job.id, error)
                self._replace_broken_executor()
            except Exception as error:  # pragma: no cover - defensive process boundary
                self._fail(job.id, error)

    def _claim_next(self) -> GenerationJob | None:
        with self.database.session_factory.begin() as session:
            job = session.scalar(
                select(GenerationJob).where(GenerationJob.status == "queued").order_by(GenerationJob.created_at)
            )
            if not job:
                return None
            job.status = "running"
            job.started_at = utc_now()
            session.flush()
            session.expunge(job)
            return job

    def _complete(self, job_id: str, result: dict[str, Any]) -> None:
        with self.database.session_factory.begin() as session:
            job = session.get(GenerationJob, job_id)
            settings = session.get(AppSettings, 1)
            if not job or not settings:
                return
            if settings.planning_revision != job.input_revision:
                job.status = "stale"
                job.error_code = "PLANNING_INPUT_CHANGED"
                job.error_message = "La configuració ha canviat durant la generació"
                job.completed_at = utc_now()
                return
            if result.get("outcome") != "solution":
                error = result.get("error") or {}
                job.status = "failed"
                job.error_code = str(error.get("code") or "NO_FEASIBLE_SCHEDULE")
                job.error_message = str(error.get("message") or "No s’ha pogut generar un calendari vàlid")
                job.result_json = json.dumps(
                    {
                        "outcome": result.get("outcome"),
                        "metrics": result.get("metrics", {}),
                        "diagnostics": result.get("diagnostics", []),
                        "error": error,
                    },
                    ensure_ascii=False,
                )
                job.completed_at = utc_now()
                return
            snapshot = json.loads(job.input_snapshot)
            violations = validate_solution(ScheduleProblem.from_dict(snapshot), result)
            if violations:
                job.status = "failed"
                job.error_code = "SCHEDULER_RESULT_INVALID"
                job.error_message = "El planificador ha produït un calendari invàlid"
                job.result_json = json.dumps(
                    {
                        "outcome": "model_invalid",
                        "error": {
                            "code": job.error_code,
                            "message": job.error_message,
                            "field": None,
                            "details": {"violations": violations},
                        },
                    },
                    ensure_ascii=False,
                )
                job.completed_at = utc_now()
                return
            range_start = job.start_date or date.fromisoformat(f"{job.start_month}-01")
            range_end = job.end_date or month_end(job.end_month)
            locked_ids = {
                item["id"]
                for item in snapshot.get("locked_assignments", [])
                if item.get("id")
            }
            locked_keys = {
                (item["memberId"], item["date"], item["type"])
                for item in snapshot.get("locked_assignments", [])
            }
            session.execute(
                delete(Assignment).where(
                    Assignment.date >= range_start,
                    Assignment.date <= range_end,
                    Assignment.locked.is_(False),
                    Assignment.extra.is_(False),
                    Assignment.manually_modified.is_(False),
                )
            )
            session.execute(
                delete(Vacancy).where(
                    Vacancy.date >= range_start,
                    Vacancy.date <= range_end,
                )
            )
            agenda_loads = {
                agenda.id: agenda.load_percentage
                for agenda in session.scalars(select(Agenda))
            }
            for item in result["assignments"]:
                key = (item["memberId"], item["date"], item["type"])
                if item.get("id") in locked_ids or key in locked_keys:
                    continue
                event_type = item["type"]
                kind = (
                    "no_assignment"
                    if event_type == "no_assignment"
                    else "management"
                    if event_type == "management"
                    else "assigned"
                )
                session.add(
                    Assignment(
                        id=item.get("id") or uid(),
                        generation_job_id=job.id,
                        date=date.fromisoformat(item["date"]),
                        member_id=item["memberId"],
                        agenda_id=event_type if kind == "assigned" else None,
                        kind=kind,
                        load_percentage=(
                            agenda_loads[event_type]
                            if kind == "assigned"
                            else 100
                            if kind == "management"
                            else 0
                        ),
                        locked=bool(item.get("locked")),
                        fixed=bool(item.get("fixed")),
                        extra=bool(item.get("extra")),
                        peonada=bool(item.get("peonada")),
                        deferred_origin_date=(
                            date.fromisoformat(item["deferredOriginDate"])
                            if item.get("deferredOriginDate")
                            else None
                        ),
                        manually_modified=bool(item.get("manuallyModified") or item.get("locked")),
                        management=kind == "management" or bool(item.get("management")),
                    )
                )
            for item in result["vacancies"]:
                session.add(
                    Vacancy(
                        generation_job_id=job.id,
                        date=date.fromisoformat(item["date"]),
                        agenda_id=item["type"],
                    )
                )
            for item in snapshot["conditions"].get("guards", []):
                guard_date = date.fromisoformat(item["date"])
                existing_guard = session.scalar(select(Guard).where(Guard.date == guard_date))
                if existing_guard is None:
                    session.add(
                        Guard(
                            id=item.get("id") or uid(),
                            generation_job_id=job.id,
                            member_id=item["memberId"],
                            date=guard_date,
                        )
                    )
            for item in snapshot["conditions"].get("absences", []):
                category = item.get("category", "vacances")
                absence_start = date.fromisoformat(item["start"])
                absence_end = date.fromisoformat(item["end"])
                existing_absence = session.scalar(
                    select(Absence).where(
                        Absence.member_id == item["memberId"],
                        Absence.category == category,
                        Absence.start == absence_start,
                        Absence.end == absence_end,
                    )
                )
                if existing_absence is None:
                    session.add(
                        Absence(
                            id=item.get("id") or uid(),
                            generation_job_id=job.id,
                            member_id=item["memberId"],
                            category=category,
                            start=absence_start,
                            end=absence_end,
                            notes="",
                        )
                    )
            settings.planning_revision += 1
            job.status = "succeeded"
            job.result_json = json.dumps(
                {
                    "outcome": result.get("outcome"),
                    "metrics": result.get("metrics", {}),
                    "diagnostics": result.get("diagnostics", []),
                }
            )
            job.completed_at = utc_now()

    def _fail(self, job_id: str, error: Exception) -> None:
        logger.exception("Generation job %s failed", job_id)
        with self.database.session_factory.begin() as session:
            job = session.get(GenerationJob, job_id)
            if job:
                job.status = "failed"
                job.error_code = "SCHEDULER_ERROR"
                job.error_message = "S’ha produït un error intern durant la generació"
                job.result_json = json.dumps(
                    {"outcome": "error", "diagnostics": [type(error).__name__]}, ensure_ascii=False
                )
                job.completed_at = utc_now()
