import uuid
from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from pinendar.api.auth import COOKIE_NAME, SESSION_SECONDS, create_session, require_auth
from pinendar.application.commands import (
    add_hospital,
    archive_agenda,
    archive_member,
    delete_calendar_range,
    distinct_color,
    exchange_assignments,
    exchange_options,
    extra_assignment_options,
    fairness,
    open_extra_assignment,
    remove_hospital,
    save_agenda,
    save_member,
    update_assignment,
)
from pinendar.application.guard_imports import (
    add_current_proposal_guards,
    create_member_alias,
    preview_guard_import,
    replace_current_proposal_guards,
)
from pinendar.application.guard_operations import (
    apply_guard_operation,
    preview_guard_operation,
)
from pinendar.application.jobs import enqueue_job
from pinendar.application.state import (
    DomainError,
    bootstrap,
    bump_revision,
    job_payload,
    serialize_proposal,
)
from pinendar.infrastructure.models import (
    Agenda,
    AppSettings,
    GenerationJob,
    Guard,
    Holiday,
    Member,
    Proposal,
)

router = APIRouter()
authenticated = Annotated[None, Depends(require_auth)]


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str


class RecoveryRequest(BaseModel):
    username: str
    recovery_code: str = Field(alias="recoveryCode")
    new_password: str = Field(alias="newPassword")


class FixedRuleRequest(BaseModel):
    id: str | None = None
    weekday: int
    type: str


class WorkPatternWeekRequest(BaseModel):
    working_days: list[int] = Field(alias="workingDays")
    tele_days: list[int] = Field(default_factory=list, alias="teleDays")


class WorkPatternRequest(BaseModel):
    weeks: list[WorkPatternWeekRequest] = Field(min_length=1, max_length=5)


class MemberRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    available_days: list[int] | None = Field(default=None, alias="availableDays")
    work_pattern: WorkPatternRequest | None = Field(default=None, alias="workPattern")
    tele_days: list[int] = Field(default_factory=list, alias="teleDays")
    allowed_types: list[str] = Field(alias="allowedTypes")
    management_quota: int = Field(default=0, alias="managementQuota", ge=0, le=5)
    fixed_rules: list[FixedRuleRequest] = Field(alias="fixedRules")
    agenda_preferences: dict[str, Literal[-1, 0, 1]] = Field(
        default_factory=dict, alias="agendaPreferences"
    )
    active: bool = True
    vacation_dates: list[date] = Field(default_factory=list, alias="vacationDates")
    confirm_shared_fixed_rules: bool = Field(default=False, alias="confirmSharedFixedRules")


class AgendaRecurrenceRequest(BaseModel):
    id: str | None = None
    ordinal: int = Field(ge=1, le=5)
    weekday: int = Field(ge=1, le=5)
    slots: int = Field(default=1, ge=1, le=1)


class AgendaRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    hospital_id: str = Field(alias="hospitalId")
    telematic: bool
    shift: Literal["morning", "afternoon"]
    priority: int = Field(default=3, ge=1, le=4)
    load_percentage: Literal[50, 100] = Field(default=100, alias="loadPercentage")
    coverage: dict[str, int]
    recurrences: list[AgendaRecurrenceRequest] = Field(default_factory=list)
    delete_conflicting_fixed_rules: bool = Field(default=False, alias="deleteConflictingFixedRules")


class HospitalSelectionRequest(BaseModel):
    catalog_id: str | None = Field(default=None, alias="catalogId")
    name: str | None = Field(default=None, min_length=2)


class HolidayRequest(BaseModel):
    date: date


class AssignmentRequest(BaseModel):
    type: str


class AssignmentExchangeRequest(BaseModel):
    target_assignment_id: str = Field(alias="targetAssignmentId")
    confirm_fixed: bool = Field(default=False, alias="confirmFixed")


class ExtraAssignmentRequest(BaseModel):
    agenda_id: str = Field(alias="agendaId")


class LanguageRequest(BaseModel):
    language: str = Field(pattern="^(ca|es)$")


class GenerationGuardRequest(BaseModel):
    id: str | None = None
    member_id: str = Field(alias="memberId")
    date: date


class GenerationAbsenceRequest(BaseModel):
    id: str | None = None
    member_id: str = Field(alias="memberId")
    start: date
    end: date


class GenerationRequest(BaseModel):
    start_month: str = Field(alias="startMonth", pattern=r"^\d{4}-\d{2}$")
    end_month: str = Field(alias="endMonth", pattern=r"^\d{4}-\d{2}$")
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    guards: list[GenerationGuardRequest] = []
    absences: list[GenerationAbsenceRequest] = []
    locked_assignments: list[dict[str, Any]] = Field(default=[], alias="lockedAssignments")
    optimization_mode: Literal["fairness"] = Field(default="fairness", alias="optimizationMode")


class GuardImportRowRequest(BaseModel):
    row_number: int = Field(alias="rowNumber", ge=1)
    date: str = ""
    names: list[str] = Field(default_factory=list)


class GuardImportPreviewRequest(BaseModel):
    start_month: str = Field(alias="startMonth", pattern=r"^\d{4}-\d{2}$")
    end_month: str = Field(alias="endMonth", pattern=r"^\d{4}-\d{2}$")
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    rows: list[GuardImportRowRequest] = Field(max_length=5000)


class MemberAliasRequest(BaseModel):
    member_id: str = Field(alias="memberId", min_length=1)
    alias: str = Field(min_length=1, max_length=120)


class CurrentProposalGuardsRequest(BaseModel):
    guards: list[GenerationGuardRequest] = Field(default_factory=list)


class GuardCessionRequest(BaseModel):
    guard_id: str | None = Field(default=None, alias="guardId")
    date: date
    to_member_id: str | None = Field(default=None, alias="toMemberId")
    expected_revision: int | None = Field(default=None, alias="expectedRevision")
    note: str = Field(default="", max_length=500)


class GuardExchangeRequest(BaseModel):
    first_guard_id: str | None = Field(default=None, alias="firstGuardId")
    first_date: date = Field(alias="firstDate")
    second_guard_id: str | None = Field(default=None, alias="secondGuardId")
    second_date: date | None = Field(default=None, alias="secondDate")
    expected_revision: int | None = Field(default=None, alias="expectedRevision")
    note: str = Field(default="", max_length=500)


def command_payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=True)


@router.post("/api/v1/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    settings = request.app.state.settings
    account = request.app.state.auth_store.authenticate(payload.username, payload.password)
    response.set_cookie(
        COOKIE_NAME,
        create_session(settings.session_secret, account),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )
    return {"ok": True, "username": account.username}


@router.post("/api/v1/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, request: Request, response: Response) -> dict[str, Any]:
    auth_store = request.app.state.auth_store
    if auth_store.username_exists(payload.username):
        raise DomainError("USERNAME_EXISTS", "Aquest usuari ja existeix", field="username")
    environment_path = request.app.state.settings.environments_dir / f"{uuid.uuid4()}.sqlite"
    request.app.state.environments.get(environment_path)
    account, recovery_code = auth_store.create_account(
        payload.username, payload.password, environment_path
    )
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE_NAME,
        create_session(settings.session_secret, account),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )
    return {"ok": True, "username": account.username, "recoveryCode": recovery_code}


@router.post("/api/v1/auth/recover")
def recover(payload: RecoveryRequest, request: Request, response: Response) -> dict[str, Any]:
    account, recovery_code = request.app.state.auth_store.recover(
        payload.username, payload.recovery_code, payload.new_password
    )
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE_NAME,
        create_session(settings.session_secret, account),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )
    return {"ok": True, "username": account.username, "recoveryCode": recovery_code}


@router.post("/api/v1/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME, httponly=True, samesite="lax")
    return {"ok": True}


@router.post("/api/v1/auth/recovery-code", dependencies=[Depends(require_auth)])
def rotate_recovery_code(request: Request) -> dict[str, str]:
    recovery_code = request.app.state.auth_store.rotate_recovery_code(
        request.state.account.id
    )
    return {"recoveryCode": recovery_code}


@router.post("/api/v1/auth/guide-onboarding-seen", dependencies=[Depends(require_auth)])
def mark_guide_onboarding_seen(request: Request) -> dict[str, bool]:
    request.app.state.auth_store.mark_guide_onboarding_seen(request.state.account.id)
    return {"ok": True}


@router.get("/api/v1/bootstrap", dependencies=[Depends(require_auth)])
def get_bootstrap(request: Request) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        result = bootstrap(database_session, request.app.state.catalog)
        result["account"] = {
            "username": request.state.account.username,
            "guideOnboardingPending": request.app.state.auth_store.guide_onboarding_pending(
                request.state.account.id
            ),
        }
        return result


@router.post("/api/v1/guard-imports/preview", dependencies=[Depends(require_auth)])
def preview_guard_import_endpoint(
    payload: GuardImportPreviewRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return preview_guard_import(
            database_session,
            payload.start_month,
            payload.end_month,
            [item.model_dump(by_alias=True, mode="json") for item in payload.rows],
            payload.start_date.isoformat() if payload.start_date else None,
            payload.end_date.isoformat() if payload.end_date else None,
        )


@router.post("/api/v1/member-aliases", dependencies=[Depends(require_auth)], status_code=status.HTTP_201_CREATED)
def save_member_alias(payload: MemberAliasRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        result = create_member_alias(database_session, payload.member_id, payload.alias)
        bump_revision(database_session)
        return result


@router.patch("/api/v1/settings/language", dependencies=[Depends(require_auth)])
def change_language(payload: LanguageRequest, request: Request) -> dict[str, str]:
    with request.state.database.session_factory.begin() as database_session:
        settings = database_session.get(AppSettings, 1)
        settings.language = payload.language
        return {"language": settings.language}


@router.post("/api/v1/members", dependencies=[Depends(require_auth)], status_code=status.HTTP_201_CREATED)
def create_member(payload: MemberRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return save_member(database_session, command_payload(payload))


@router.put("/api/v1/members/{member_id}", dependencies=[Depends(require_auth)])
def update_member(member_id: str, payload: MemberRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return save_member(database_session, command_payload(payload), member_id)


@router.delete(
    "/api/v1/members/{member_id}", dependencies=[Depends(require_auth)], status_code=status.HTTP_204_NO_CONTENT
)
def delete_member(member_id: str, request: Request) -> Response:
    with request.state.database.session_factory.begin() as database_session:
        archive_member(database_session, member_id)
    return Response(status_code=204)


@router.post("/api/v1/members/{member_id}/random-color", dependencies=[Depends(require_auth)])
def member_random_color(member_id: str, request: Request) -> dict[str, str]:
    with request.state.database.session_factory.begin() as database_session:
        member = database_session.get(Member, member_id)
        if not member or member.archived_at:
            raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada")
        member.color = distinct_color(database_session, "member", member.id, member.color)
        return {"color": member.color}


@router.post("/api/v1/agendas", dependencies=[Depends(require_auth)], status_code=status.HTTP_201_CREATED)
def create_agenda(payload: AgendaRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return save_agenda(database_session, command_payload(payload))


@router.put("/api/v1/agendas/{agenda_id}", dependencies=[Depends(require_auth)])
def update_agenda(agenda_id: str, payload: AgendaRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return save_agenda(database_session, command_payload(payload), agenda_id)


@router.delete(
    "/api/v1/agendas/{agenda_id}", dependencies=[Depends(require_auth)], status_code=status.HTTP_204_NO_CONTENT
)
def delete_agenda(agenda_id: str, request: Request) -> Response:
    with request.state.database.session_factory.begin() as database_session:
        archive_agenda(database_session, agenda_id)
    return Response(status_code=204)


@router.post("/api/v1/agendas/{agenda_id}/random-color", dependencies=[Depends(require_auth)])
def agenda_random_color(agenda_id: str, request: Request) -> dict[str, str]:
    with request.state.database.session_factory.begin() as database_session:
        agenda = database_session.get(Agenda, agenda_id)
        if not agenda or agenda.archived_at:
            raise DomainError("AGENDA_NOT_FOUND", "Agenda no trobada")
        agenda.color = distinct_color(database_session, "agenda", agenda.id, agenda.color)
        return {"color": agenda.color}


@router.post("/api/v1/selected-hospitals", dependencies=[Depends(require_auth)], status_code=status.HTTP_201_CREATED)
def select_hospital(payload: HospitalSelectionRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return add_hospital(
            database_session,
            request.app.state.catalog,
            payload.catalog_id,
            payload.name,
        )


@router.delete(
    "/api/v1/selected-hospitals/{hospital_id}",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_selected_hospital(hospital_id: str, request: Request) -> Response:
    with request.state.database.session_factory.begin() as database_session:
        remove_hospital(database_session, hospital_id)
    return Response(status_code=204)


@router.post("/api/v1/holidays", dependencies=[Depends(require_auth)], status_code=status.HTTP_201_CREATED)
def create_holiday(payload: HolidayRequest, request: Request) -> dict[str, str]:
    with request.state.database.session_factory.begin() as database_session:
        if database_session.get(Holiday, payload.date):
            raise DomainError("HOLIDAY_EXISTS", "Aquest festiu ja existeix", field="date")
        database_session.add(Holiday(date=payload.date))
        bump_revision(database_session)
        return {"date": payload.date.isoformat()}


@router.delete(
    "/api/v1/holidays/{holiday_date}", dependencies=[Depends(require_auth)], status_code=status.HTTP_204_NO_CONTENT
)
def delete_holiday(holiday_date: date, request: Request) -> Response:
    with request.state.database.session_factory.begin() as database_session:
        holiday = database_session.get(Holiday, holiday_date)
        if not holiday:
            raise DomainError("HOLIDAY_NOT_FOUND", "Festiu no trobat")
        database_session.delete(holiday)
        bump_revision(database_session)
    return Response(status_code=204)


@router.delete(
    "/api/v1/guards/{guard_id}", dependencies=[Depends(require_auth)], status_code=status.HTTP_204_NO_CONTENT
)
def delete_guard(guard_id: str, request: Request) -> Response:
    with request.state.database.session_factory.begin() as database_session:
        guard = database_session.get(Guard, guard_id)
        if not guard:
            raise DomainError("GUARD_NOT_FOUND", "Guàrdia no trobada")
        database_session.delete(guard)
        bump_revision(database_session)
    return Response(status_code=204)


@router.delete("/api/v1/calendar/assignments", dependencies=[Depends(require_auth)])
def delete_assignments_in_range(
    request: Request,
    start_date: Annotated[date, Query(alias="startDate")],
    end_date: Annotated[date, Query(alias="endDate")],
) -> dict[str, int]:
    with request.state.database.session_factory.begin() as database_session:
        return delete_calendar_range(database_session, start_date, end_date)


@router.patch("/api/v1/proposals/current/assignments/{assignment_id}", dependencies=[Depends(require_auth)])
def patch_assignment(assignment_id: str, payload: AssignmentRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return update_assignment(database_session, assignment_id, payload.type)


@router.get(
    "/api/v1/proposals/current/assignments/{assignment_id}/exchange-options",
    dependencies=[Depends(require_auth)],
)
def assignment_exchange_options(
    assignment_id: str,
    request: Request,
    include_fixed: Annotated[bool, Query(alias="includeFixed")] = False,
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return exchange_options(database_session, assignment_id, include_fixed=include_fixed)


@router.post(
    "/api/v1/proposals/current/assignments/{assignment_id}/exchange",
    dependencies=[Depends(require_auth)],
)
def exchange_assignment(
    assignment_id: str,
    payload: AssignmentExchangeRequest,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return exchange_assignments(
            database_session,
            assignment_id,
            payload.target_assignment_id,
            confirm_fixed=payload.confirm_fixed,
        )


@router.get(
    "/api/v1/proposals/current/dates/{assignment_date}/members/{member_id}/extra-options",
    dependencies=[Depends(require_auth)],
)
def member_extra_assignment_options(
    assignment_date: date,
    member_id: str,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return extra_assignment_options(database_session, member_id, assignment_date)


@router.post(
    "/api/v1/proposals/current/dates/{assignment_date}/members/{member_id}/extra-assignments",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def create_extra_assignment(
    assignment_date: date,
    member_id: str,
    payload: ExtraAssignmentRequest,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return open_extra_assignment(database_session, member_id, assignment_date, payload.agenda_id)


@router.get("/api/v1/proposals/current", dependencies=[Depends(require_auth)])
def current_proposal(request: Request) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        proposal = database_session.scalar(select(Proposal).where(Proposal.status == "current"))
        if not proposal:
            raise DomainError("PROPOSAL_NOT_FOUND", "No hi ha cap proposta actual")
        return serialize_proposal(database_session, proposal)


@router.post(
    "/api/v1/proposals/current/guards",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def add_current_proposal_guards_endpoint(
    payload: CurrentProposalGuardsRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return add_current_proposal_guards(database_session, command_payload(payload)["guards"])


@router.put("/api/v1/proposals/current/guards", dependencies=[Depends(require_auth)])
def replace_current_proposal_guards_endpoint(
    payload: CurrentProposalGuardsRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return replace_current_proposal_guards(database_session, command_payload(payload)["guards"])


@router.post(
    "/api/v1/proposals/current/guard-cessions/preview",
    dependencies=[Depends(require_auth)],
)
def preview_guard_cession_endpoint(
    payload: GuardCessionRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return preview_guard_operation(
            database_session, "cession", command_payload(payload)
        )


@router.post(
    "/api/v1/proposals/current/guard-cessions",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def apply_guard_cession_endpoint(
    payload: GuardCessionRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return apply_guard_operation(
            database_session, "cession", command_payload(payload)
        )


@router.post(
    "/api/v1/proposals/current/guard-exchanges/preview",
    dependencies=[Depends(require_auth)],
)
def preview_guard_exchange_endpoint(
    payload: GuardExchangeRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return preview_guard_operation(
            database_session, "exchange", command_payload(payload)
        )


@router.post(
    "/api/v1/proposals/current/guard-exchanges",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def apply_guard_exchange_endpoint(
    payload: GuardExchangeRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return apply_guard_operation(
            database_session, "exchange", command_payload(payload)
        )


@router.get("/api/v1/proposals/history", dependencies=[Depends(require_auth)])
def proposal_history(request: Request) -> list[dict[str, Any]]:
    with request.state.database.session_factory() as database_session:
        proposals = database_session.scalars(
            select(Proposal).where(Proposal.status == "historical").order_by(Proposal.generated_at.desc())
        )
        return [serialize_proposal(database_session, proposal) for proposal in proposals]


@router.get("/api/v1/fairness", dependencies=[Depends(require_auth)])
def get_fairness(request: Request) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return fairness(database_session)


@router.post("/api/v1/generation-jobs", dependencies=[Depends(require_auth)], status_code=status.HTTP_202_ACCEPTED)
def create_generation_job(payload: GenerationRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    job = enqueue_job(
        request.state.database,
        request.app.state.catalog,
        command_payload(payload),
        {
            "timeLimitSeconds": settings.scheduler_time_limit_seconds,
            "workers": settings.scheduler_workers,
            "randomSeed": settings.scheduler_random_seed,
            "optimizationMode": payload.optimization_mode,
        },
    )
    request.state.job_dispatcher.notify()
    return job


@router.get("/api/v1/generation-jobs/{job_id}", dependencies=[Depends(require_auth)])
def get_generation_job(job_id: str, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        job = database_session.get(GenerationJob, job_id)
        if not job:
            raise DomainError("GENERATION_JOB_NOT_FOUND", "Treball de generació no trobat")
        return job_payload(job)


@router.get("/api/v1/hospitals", dependencies=[Depends(require_auth)])
def search_hospitals(query: str, request: Request) -> dict[str, Any]:
    return cast(dict[str, Any], request.app.state.catalog.search(query))


@router.get("/api/v1/hospitals/{hospital_id}", dependencies=[Depends(require_auth)])
def hospital_details(hospital_id: str, request: Request) -> dict[str, Any]:
    details = cast(dict[str, Any] | None, request.app.state.catalog.details(hospital_id))
    if not details:
        raise DomainError("HOSPITAL_NOT_FOUND", "Hospital no trobat")
    return details
