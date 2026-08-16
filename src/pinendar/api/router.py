import uuid
from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pinendar.api.auth import (
    ADMIN_COOKIE_NAME,
    COOKIE_NAME,
    SESSION_SECONDS,
    create_session,
    require_admin,
    require_auth,
)
from pinendar.application.commands import (
    add_hospital,
    archive_agenda,
    archive_member,
    assign_vacancy,
    delete_calendar_range,
    distinct_color,
    exchange_assignments,
    exchange_options,
    extra_assignment_options,
    fairness,
    open_extra_assignment,
    peonada_options,
    remove_hospital,
    save_agenda,
    save_member,
    transfer_assignment,
    transfer_options,
    update_assignment,
    update_hospital_short_name,
    update_peonadas,
    vacancy_assignment_options,
)
from pinendar.application.deferred_operations import (
    apply_deferred_vacancy,
    apply_direct_deferred_vacancy,
    deferred_member_options,
    deferred_vacancy_options,
)
from pinendar.application.guard_imports import (
    add_guards,
    create_member_alias,
    preview_guard_import,
    replace_guards,
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
)
from pinendar.infrastructure.models import (
    Agenda,
    AppSettings,
    GenerationJob,
    Guard,
    Holiday,
    Member,
)

router = APIRouter()
authenticated = Annotated[None, Depends(require_auth)]


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str
    password: str


class AdminAccountCreateRequest(BaseModel):
    username: str
    password: str


class AdminAccountUpdateRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    disabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "AdminAccountUpdateRequest":
        if self.username is None and self.password is None and self.disabled is None:
            raise ValueError("At least one change is required")
        return self


class RecoveryRequest(BaseModel):
    username: str
    recovery_code: str = Field(alias="recoveryCode")
    new_password: str = Field(alias="newPassword")


@router.get("/api/v1/auth/config")
def auth_config(request: Request) -> dict[str, bool]:
    return {"signupEnabled": request.app.state.settings.signup_enabled}


class FixedRuleRequest(BaseModel):
    id: str | None = None
    weekday: int = Field(ge=1, le=5)
    required_mode: Literal["all", "one"] = Field(default="all", alias="requiredMode")
    required_agenda_ids: list[str] = Field(default_factory=list, alias="requiredAgendaIds")
    forbidden_agenda_ids: list[str] = Field(default_factory=list, alias="forbiddenAgendaIds")
    legacy_type: str | None = Field(default=None, alias="type", exclude=True)

    @model_validator(mode="after")
    def normalize_legacy_rule(self) -> "FixedRuleRequest":
        if self.legacy_type and not self.required_agenda_ids:
            self.required_agenda_ids = [self.legacy_type]
        if not self.required_agenda_ids and not self.forbidden_agenda_ids:
            raise ValueError("La regla ha de contenir almenys una agenda")
        return self


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


class HospitalAliasRequest(BaseModel):
    short_name: str | None = Field(default=None, alias="shortName", max_length=20)


class HolidayRequest(BaseModel):
    date: date


class AssignmentRequest(BaseModel):
    type: str


class AssignmentExchangeRequest(BaseModel):
    target_assignment_id: str | None = Field(default=None, alias="targetAssignmentId")
    target_vacancy_id: int | None = Field(default=None, alias="targetVacancyId")
    confirm_fixed: bool = Field(default=False, alias="confirmFixed")
    peonada_selections: dict[str, list[str]] | None = Field(
        default=None,
        alias="peonadaAssignments",
    )

    @model_validator(mode="after")
    def validate_target(self) -> "AssignmentExchangeRequest":
        if bool(self.target_assignment_id) == bool(self.target_vacancy_id):
            raise ValueError("Select exactly one exchange target")
        return self


class VacancyAssignmentRequest(BaseModel):
    member_id: str = Field(alias="memberId")
    peonada_selections: dict[str, list[str]] | None = Field(
        default=None,
        alias="peonadaAssignments",
    )


class DeferredVacancyRequest(BaseModel):
    target_date: date = Field(alias="targetDate")
    target_member_id: str | None = Field(default=None, alias="targetMemberId")
    expected_revision: int | None = Field(default=None, alias="expectedRevision")


class AssignmentTransferRequest(BaseModel):
    target_member_id: str = Field(alias="targetMemberId")
    confirm_fixed: bool = Field(default=False, alias="confirmFixed")
    peonada_selections: dict[str, list[str]] | None = Field(
        default=None,
        alias="peonadaAssignments",
    )


class PeonadaRequest(BaseModel):
    assignment_ids: list[str] = Field(default_factory=list, alias="assignmentIds")


class ExtraAssignmentRequest(BaseModel):
    agenda_id: str = Field(alias="agendaId")
    peonada_selections: dict[str, list[str]] | None = Field(
        default=None,
        alias="peonadaAssignments",
    )


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
    replace_existing: bool = Field(default=False, alias="replaceExisting")
    optimization_mode: Literal["fairness"] = Field(default="fairness", alias="optimizationMode")
    time_limit_minutes: int | None = Field(default=None, alias="timeLimitMinutes", ge=1, le=30)


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


class GuardListRequest(BaseModel):
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


@router.post("/api/v1/auth/signup", status_code=status.HTTP_202_ACCEPTED)
def signup(payload: SignupRequest, request: Request) -> dict[str, Any]:
    if not request.app.state.settings.signup_enabled:
        raise DomainError("SIGNUP_DISABLED", "La creació de comptes està desactivada")
    client_address = request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )
    if not request.app.state.signup_limiter.allow(client_address):
        raise DomainError(
            "SIGNUP_RATE_LIMITED",
            "S’han enviat massa sol·licituds. Torna-ho a provar més tard",
        )
    auth_store = request.app.state.auth_store
    signup_request, recovery_code = auth_store.request_signup(payload.username, payload.password)
    return {
        "ok": True,
        "status": "pending",
        "requestId": signup_request.id,
        "username": signup_request.username,
        "recoveryCode": recovery_code,
    }


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


@router.post("/api/v1/admin/auth/login")
def admin_login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    settings = request.app.state.settings
    account = request.app.state.auth_store.authenticate(payload.username, payload.password)
    if not account.is_admin:
        raise DomainError("INVALID_CREDENTIALS", "Usuari o contrasenya incorrectes")
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        create_session(settings.session_secret, account),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=settings.secure_cookies,
    )
    return {"ok": True, "username": account.username}


@router.post("/api/v1/admin/auth/logout")
def admin_logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(ADMIN_COOKIE_NAME, httponly=True, samesite="strict")
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


def account_payload(account: Any) -> dict[str, Any]:
    return {
        "id": account.id,
        "username": account.username,
        "disabled": account.disabled,
        "isAdmin": account.is_admin,
        "createdAt": account.created_at.isoformat(),
        "lastActiveAt": account.last_active_at.isoformat() if account.last_active_at else None,
    }


def signup_request_payload(signup_request: Any) -> dict[str, Any]:
    return {
        "id": signup_request.id,
        "username": signup_request.username,
        "createdAt": signup_request.created_at.isoformat(),
    }


def backup_payload(backup: Any) -> dict[str, Any]:
    return {
        "name": backup.name,
        "size": backup.size,
        "createdAt": backup.created_at.isoformat(),
        "downloadUrl": f"/api/v1/admin/backups/{backup.name}",
    }


@router.get("/api/v1/admin", dependencies=[Depends(require_admin)])
def admin_overview(request: Request) -> dict[str, Any]:
    return {
        "signupRequests": [
            signup_request_payload(item)
            for item in request.app.state.auth_store.list_signup_requests()
        ],
        "accounts": [
            account_payload(item) for item in request.app.state.auth_store.list_accounts()
        ],
        "backups": [backup_payload(item) for item in request.app.state.backups.list()],
    }


@router.post(
    "/api/v1/admin/signup-requests/{request_id}/approve",
    dependencies=[Depends(require_admin)],
)
def approve_signup(request_id: str, request: Request) -> dict[str, Any]:
    pending = request.app.state.auth_store.get_signup_request(request_id)
    if not pending:
        raise DomainError("SIGNUP_REQUEST_NOT_FOUND", "Sol·licitud no trobada")
    environment_path = request.app.state.settings.environments_dir / f"{uuid.uuid4()}.sqlite"
    request.app.state.environments.create(environment_path)
    try:
        account = request.app.state.auth_store.approve_signup_request(
            request_id, environment_path
        )
    except Exception:
        request.app.state.environments.delete(environment_path)
        raise
    return {"ok": True, "id": account.id, "username": account.username}


@router.post(
    "/api/v1/admin/signup-requests/{request_id}/reject",
    dependencies=[Depends(require_admin)],
)
def reject_signup(request_id: str, request: Request) -> dict[str, bool]:
    request.app.state.auth_store.reject_signup_request(request_id)
    return {"ok": True}


@router.post(
    "/api/v1/admin/accounts",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_account(payload: AdminAccountCreateRequest, request: Request) -> dict[str, Any]:
    environment_path = request.app.state.settings.environments_dir / f"{uuid.uuid4()}.sqlite"
    request.app.state.environments.create(environment_path)
    try:
        account, recovery_code = request.app.state.auth_store.create_account(
            payload.username, payload.password, environment_path
        )
    except Exception:
        request.app.state.environments.delete(environment_path)
        raise
    return {
        "ok": True,
        "id": account.id,
        "username": account.username,
        "recoveryCode": recovery_code,
    }


@router.patch("/api/v1/admin/accounts/{account_id}", dependencies=[Depends(require_admin)])
def update_account(
    account_id: str, payload: AdminAccountUpdateRequest, request: Request
) -> dict[str, Any]:
    target = request.app.state.auth_store.get_account(account_id)
    if not target:
        raise DomainError("ACCOUNT_NOT_FOUND", "Usuari no trobat")
    if target.is_admin and (
        payload.disabled is True or account_id == request.state.account.id and payload.password is not None
    ):
        raise DomainError("ADMIN_ACCOUNT_PROTECTED", "No es pot bloquejar ni reiniciar l’administrador actiu")
    account = request.app.state.auth_store.update_account(
        account_id,
        username=payload.username,
        password=payload.password,
        disabled=payload.disabled,
    )
    return {"ok": True, "id": account.id, "username": account.username}


@router.delete("/api/v1/admin/accounts/{account_id}", dependencies=[Depends(require_admin)])
def delete_account(account_id: str, request: Request) -> Response:
    target = request.app.state.auth_store.get_account(account_id)
    if not target:
        raise DomainError("ACCOUNT_NOT_FOUND", "Usuari no trobat")
    if target.is_admin or target.id == request.state.account.id:
        raise DomainError("ADMIN_ACCOUNT_PROTECTED", "No es pot eliminar el compte administrador")
    if not request.app.state.environments.manages(target.environment_path):
        raise DomainError("ENVIRONMENT_NOT_FOUND", "Entorn d’usuari no vàlid")
    deleted = request.app.state.auth_store.delete_account(account_id)
    if not request.app.state.environments.delete(deleted.environment_path):
        raise DomainError("ENVIRONMENT_NOT_FOUND", "Entorn d’usuari no vàlid")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/v1/admin/backups",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_backup(request: Request) -> dict[str, Any]:
    return backup_payload(request.app.state.backups.create())


@router.get("/api/v1/admin/backups/{name}", dependencies=[Depends(require_admin)])
def download_backup(name: str, request: Request) -> FileResponse:
    path = request.app.state.backups.resolve(name)
    if not path:
        raise DomainError("BACKUP_NOT_FOUND", "Còpia no trobada")
    return FileResponse(path, filename=path.name, media_type="application/zip")


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


@router.patch("/api/v1/selected-hospitals/{hospital_id}", dependencies=[Depends(require_auth)])
def update_selected_hospital(
    hospital_id: str,
    payload: HospitalAliasRequest,
    request: Request,
) -> dict[str, str | None]:
    with request.state.database.session_factory.begin() as database_session:
        return update_hospital_short_name(database_session, hospital_id, payload.short_name)


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


@router.patch("/api/v1/calendar/events/{assignment_id}", dependencies=[Depends(require_auth)])
def patch_assignment(assignment_id: str, payload: AssignmentRequest, request: Request) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return update_assignment(database_session, assignment_id, payload.type)


@router.get(
    "/api/v1/calendar/events/{assignment_id}/exchange-options",
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
    "/api/v1/calendar/events/{assignment_id}/exchange",
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
            payload.target_vacancy_id,
            confirm_fixed=payload.confirm_fixed,
            peonada_selections=payload.peonada_selections,
        )


@router.get(
    "/api/v1/calendar/events/{assignment_id}/transfer-options",
    dependencies=[Depends(require_auth)],
)
def assignment_transfer_options(
    assignment_id: str,
    request: Request,
    include_fixed: Annotated[bool, Query(alias="includeFixed")] = False,
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return transfer_options(
            database_session,
            assignment_id,
            include_fixed=include_fixed,
        )


@router.post(
    "/api/v1/calendar/events/{assignment_id}/transfer",
    dependencies=[Depends(require_auth)],
)
def transfer_calendar_assignment(
    assignment_id: str,
    payload: AssignmentTransferRequest,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return transfer_assignment(
            database_session,
            assignment_id,
            payload.target_member_id,
            confirm_fixed=payload.confirm_fixed,
            peonada_selections=payload.peonada_selections,
        )


@router.get(
    "/api/v1/calendar/vacancies/{vacancy_id}/assignment-options",
    dependencies=[Depends(require_auth)],
)
def calendar_vacancy_assignment_options(
    vacancy_id: int,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        result = vacancy_assignment_options(database_session, vacancy_id)
        deferred = deferred_vacancy_options(database_session, vacancy_id)
        return {
            **result,
            "deferredOptions": deferred["options"],
            "planningRevision": deferred["planningRevision"],
        }


@router.post(
    "/api/v1/calendar/vacancies/{vacancy_id}/defer",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def defer_calendar_vacancy(
    vacancy_id: int,
    payload: DeferredVacancyRequest,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        if payload.target_member_id:
            return apply_direct_deferred_vacancy(
                database_session,
                vacancy_id,
                payload.target_date,
                payload.target_member_id,
                expected_revision=payload.expected_revision,
            )
        return apply_deferred_vacancy(
            database_session,
            vacancy_id,
            payload.target_date,
            expected_revision=payload.expected_revision,
        )


@router.post(
    "/api/v1/calendar/vacancies/{vacancy_id}/assign",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def create_vacancy_assignment(
    vacancy_id: int,
    payload: VacancyAssignmentRequest,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return assign_vacancy(
            database_session,
            vacancy_id,
            payload.member_id,
            peonada_selections=payload.peonada_selections,
        )


@router.get(
    "/api/v1/calendar/dates/{assignment_date}/members/{member_id}/peonadas",
    dependencies=[Depends(require_auth)],
)
def member_peonada_options(
    assignment_date: date,
    member_id: str,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return peonada_options(database_session, member_id, assignment_date)


@router.put(
    "/api/v1/calendar/dates/{assignment_date}/members/{member_id}/peonadas",
    dependencies=[Depends(require_auth)],
)
def replace_member_peonadas(
    assignment_date: date,
    member_id: str,
    payload: PeonadaRequest,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return update_peonadas(
            database_session,
            member_id,
            assignment_date,
            payload.assignment_ids,
        )


@router.get(
    "/api/v1/calendar/dates/{assignment_date}/members/{member_id}/extra-options",
    dependencies=[Depends(require_auth)],
)
def member_extra_assignment_options(
    assignment_date: date,
    member_id: str,
    request: Request,
) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        result = extra_assignment_options(database_session, member_id, assignment_date)
        deferred = deferred_member_options(database_session, member_id, assignment_date)
        return {
            **result,
            "deferredOptions": deferred["options"],
            "planningRevision": deferred["planningRevision"],
        }


@router.post(
    "/api/v1/calendar/dates/{assignment_date}/members/{member_id}/extra-assignments",
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
        return open_extra_assignment(
            database_session,
            member_id,
            assignment_date,
            payload.agenda_id,
            peonada_selections=payload.peonada_selections,
        )


@router.post(
    "/api/v1/guards",
    dependencies=[Depends(require_auth)],
    status_code=status.HTTP_201_CREATED,
)
def add_guards_endpoint(
    payload: GuardListRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return add_guards(database_session, command_payload(payload)["guards"])


@router.put("/api/v1/guards", dependencies=[Depends(require_auth)])
def replace_guards_endpoint(
    payload: GuardListRequest, request: Request
) -> dict[str, Any]:
    with request.state.database.session_factory.begin() as database_session:
        return replace_guards(database_session, command_payload(payload)["guards"])


@router.post(
    "/api/v1/guard-cessions/preview",
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
    "/api/v1/guard-cessions",
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
    "/api/v1/guard-exchanges/preview",
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
    "/api/v1/guard-exchanges",
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


@router.get("/api/v1/fairness", dependencies=[Depends(require_auth)])
def get_fairness(request: Request) -> dict[str, Any]:
    with request.state.database.session_factory() as database_session:
        return fairness(database_session)


@router.post("/api/v1/generation-jobs", dependencies=[Depends(require_auth)], status_code=status.HTTP_202_ACCEPTED)
def create_generation_job(payload: GenerationRequest, request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    time_limit_seconds = (
        payload.time_limit_minutes * 60
        if payload.time_limit_minutes is not None
        else settings.scheduler_time_limit_seconds
    )
    job = enqueue_job(
        request.state.database,
        request.app.state.catalog,
        command_payload(payload),
        {
            "timeLimitSeconds": time_limit_seconds,
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
