from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from pinendar.infrastructure.catalog import HospitalCatalog
from pinendar.infrastructure.database import Database, table_exists
from pinendar.infrastructure.models import (
    Absence,
    Agenda,
    AgendaRecurrence,
    AppSettings,
    Assignment,
    Coverage,
    FixedRule,
    GenerationJob,
    Guard,
    GuardTransfer,
    Holiday,
    Hospital,
    Member,
    MemberAgendaPreference,
    MemberAvailableDay,
    MemberCapability,
    MemberStatusChange,
    MemberTeleDay,
    Vacancy,
)

AGENDA_SEED = [
    ("tac_amb", "TAC ambulatori", True),
    ("eco_amb", "Eco ambulatòria", False),
    ("tac_urg", "TAC urgent", False),
    ("eco_urg", "Eco urgent", False),
    ("eco_tec", "Eco tècnics", False),
    ("reso", "Ressonància", True),
    ("intervencio", "Intervencionisme", False),
    ("general", "General", False),
    ("telemando", "Telecomandament", True),
]

AGENDA_PRIORITIES = {
    "tac_urg": 1,
    "eco_urg": 1,
    "tac_amb": 2,
    "reso": 2,
    "intervencio": 2,
    "general": 3,
    "telemando": 3,
    "eco_amb": 4,
    "eco_tec": 4,
}

COVERAGE_SEED = {
    1: {"tac_amb": 3, "eco_amb": 3, "eco_urg": 1, "reso": 2, "tac_urg": 2},
    2: {"tac_amb": 2, "eco_amb": 2, "eco_urg": 1, "reso": 2, "tac_urg": 2, "telemando": 1, "general": 1},
    3: {"tac_amb": 3, "eco_amb": 1, "eco_tec": 1, "eco_urg": 1, "reso": 3, "tac_urg": 2},
    4: {
        "tac_amb": 3,
        "eco_amb": 1,
        "eco_tec": 1,
        "eco_urg": 1,
        "reso": 2,
        "tac_urg": 2,
        "general": 1,
        "intervencio": 1,
    },
    5: {"tac_amb": 2, "eco_amb": 1, "eco_tec": 1, "eco_urg": 1, "reso": 2, "tac_urg": 2, "general": 1},
}

TEAM_SEED = [
    ("Aina Costa", "aina@hospital.test"),
    ("Biel Ferrer", "biel@hospital.test"),
    ("Clàudia Riera", "claudia@hospital.test"),
    ("David Puig", "david@hospital.test"),
    ("Elena Vidal", "elena@hospital.test"),
    ("Ferran Grau", "ferran@hospital.test"),
    ("Gemma Soler", "gemma@hospital.test"),
    ("Hugo Martí", "hugo@hospital.test"),
    ("Ivet Serra", "ivet@hospital.test"),
    ("Joan Roca", "joan@hospital.test"),
    ("Laia Bosch", "laia@hospital.test"),
    ("Marc Pons", "marc@hospital.test"),
]


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, field: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.details = details or {}


def uid() -> str:
    return uuid4().hex


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.strip().lower())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def normalize_agenda_priority(value: Any) -> int:
    priority = int(value or 3)
    if priority <= 1:
        return 1
    if priority <= 3:
        return 2
    if priority <= 5:
        return 3
    return 4


def parse_date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def parse_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return datetime.now(UTC).replace(tzinfo=None)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def automatic_color(seed: str, kind: str) -> str:
    value = 0
    for char in seed:
        value = (value * 31 + ord(char)) % 360
    hue = round((value * 137.508) % 360)
    return f"hsl({hue} {'58% 78%' if kind == 'member' else '90% 56%'})"


def months_in_period(start_month: str, end_month: str) -> int:
    if not re.fullmatch(r"\d{4}-\d{2}", start_month) or not re.fullmatch(r"\d{4}-\d{2}", end_month):
        return math.inf  # type: ignore[return-value]
    start_year, start = map(int, start_month.split("-"))
    end_year, end = map(int, end_month.split("-"))
    return (end_year - start_year) * 12 + end - start + 1


def month_end(month: str) -> date:
    year, value = map(int, month.split("-"))
    following = date(year + (value == 12), 1 if value == 12 else value + 1, 1)
    return following - timedelta(days=1)


def bump_revision(session: Session) -> int:
    settings = session.get(AppSettings, 1)
    if settings is None:
        raise RuntimeError("Settings not initialized")
    settings.planning_revision += 1
    return settings.planning_revision


def initialize_database(database: Database, catalog: HospitalCatalog) -> None:
    with database.session_factory.begin() as session:
        if session.get(AppSettings, 1):
            return
        legacy: dict[str, Any] | None = None
        if table_exists(database.engine, "app_state"):
            row = session.execute(text("SELECT value FROM app_state WHERE key='state'")).first()
            if row:
                legacy = json.loads(row[0])
        if legacy:
            import_legacy_state(session, legacy, catalog)
        else:
            seed_initial_state(session, catalog)


def seed_initial_state(session: Session, catalog: HospitalCatalog) -> None:
    session.add(AppSettings(id=1, language="ca", color_scheme_version=4, planning_revision=1))
    hospital_ids = [catalog_id for catalog_id in ("170010", "170301") if catalog_id in catalog.by_id]
    if not hospital_ids:
        hospital_ids = list(catalog.by_id)[:1]
    for catalog_id in hospital_ids:
        session.add(Hospital(id=uid(), catalog_id=catalog_id))
    session.flush()
    for index, (agenda_id, name, telematic) in enumerate(AGENDA_SEED):
        hospital_id = hospital_ids[index % len(hospital_ids)]
        session.add(
            Agenda(
                id=agenda_id,
                name=name,
                hospital_catalog_id=hospital_id,
                telematic=telematic,
                shift="morning",
                color=automatic_color(agenda_id, "agenda"),
                priority=AGENDA_PRIORITIES.get(agenda_id, 5),
                load_percentage=100,
            )
        )
        for weekday in range(1, 6):
            session.add(
                Coverage(agenda_id=agenda_id, weekday=weekday, slots=COVERAGE_SEED.get(weekday, {}).get(agenda_id, 0))
            )
        if agenda_id == "intervencio":
            session.add(AgendaRecurrence(id=uid(), agenda_id=agenda_id, ordinal=3, weekday=1, slots=1))
    session.flush()
    agenda_ids = [item[0] for item in AGENDA_SEED]
    for index, (name, email) in enumerate(TEAM_SEED):
        member_id = uid()
        session.add(
            Member(
                id=member_id,
                name=name,
                normalized_name=normalized(name),
                email=email,
                normalized_email=normalized(email),
                color=automatic_color(email, "member"),
                management_quota=0,
            )
        )
        session.flush()
        for weekday in range(1, 6):
            session.add(MemberAvailableDay(member_id=member_id, week_index=0, weekday=weekday))
        if index % 4 == 0:
            session.add(MemberTeleDay(member_id=member_id, week_index=0, weekday=index % 5 + 1))
        for agenda_id in agenda_ids:
            session.add(MemberCapability(member_id=member_id, agenda_id=agenda_id))
        if index == 0:
            session.add(FixedRule(id=uid(), member_id=member_id, weekday=5, agenda_id="reso"))


def import_legacy_state(session: Session, state: dict[str, Any], catalog: HospitalCatalog) -> None:
    session.add(AppSettings(id=1, language=state.get("language", "ca"), color_scheme_version=4, planning_revision=1))
    for item in state.get("hospitals", []):
        catalog_id = item.get("catalogId")
        if catalog_id and (catalog_id in catalog.by_id or item.get("locationKnown") is False):
            session.add(
                Hospital(
                    id=item.get("id") or uid(),
                    catalog_id=catalog_id,
                    name=item.get("name") if catalog_id not in catalog.by_id else None,
                    address=item.get("address") if catalog_id not in catalog.by_id else None,
                    location_known=catalog_id in catalog.by_id,
                )
            )
    session.flush()
    selected_hospitals = list(session.scalars(select(Hospital)).all())
    if not selected_hospitals:
        for catalog_id in ("170010", "170301"):
            if catalog_id in catalog.by_id:
                session.add(Hospital(id=uid(), catalog_id=catalog_id))
        session.flush()
        selected_hospitals = list(session.scalars(select(Hospital)).all())
    hospital_ids = {item.catalog_id for item in selected_hospitals}
    fallback_hospital = selected_hospitals[0].catalog_id

    all_agendas = [*state.get("agendas", []), *state.get("archivedAgendas", [])]
    seen_agendas: set[str] = set()
    for item in all_agendas:
        if not item.get("id") or item["id"] in seen_agendas:
            continue
        seen_agendas.add(item["id"])
        hospital_id = item.get("hospitalId") if item.get("hospitalId") in hospital_ids else fallback_hospital
        session.add(
            Agenda(
                id=item["id"],
                name=item.get("name", item["id"]),
                hospital_catalog_id=hospital_id,
                telematic=bool(item.get("telematic")),
                shift=(
                    item.get("shift")
                    if item.get("shift") in {"morning", "afternoon"}
                    else "morning"
                ),
                color=item.get("color") or automatic_color(item["id"], "agenda"),
                priority=normalize_agenda_priority(
                    item.get("priority", AGENDA_PRIORITIES.get(item["id"], 3))
                ),
                load_percentage=50 if int(item.get("loadPercentage", 100)) == 50 else 100,
                archived_at=parse_date(item["archivedAt"]) if item.get("archivedAt") else None,
            )
        )
        for weekday in range(1, 6):
            slots = int(
                state.get("coverage", {})
                .get(str(weekday), state.get("coverage", {}).get(weekday, {}))
                .get(item["id"], 0)
            )
            session.add(Coverage(agenda_id=item["id"], weekday=weekday, slots=slots))
        recurrences = item.get("recurrences", [])
        if not recurrences and item["id"] == "intervencio":
            recurrences = [{"ordinal": 3, "weekday": 1, "slots": 1}]
        for recurrence in recurrences:
            session.add(
                AgendaRecurrence(
                    id=recurrence.get("id") or uid(),
                    agenda_id=item["id"],
                    ordinal=int(recurrence["ordinal"]),
                    weekday=int(recurrence["weekday"]),
                    slots=1,
                )
            )
    session.flush()

    all_members = [*state.get("team", []), *state.get("archivedTeam", [])]
    seen_members: set[str] = set()
    for item in all_members:
        if not item.get("id") or item["id"] in seen_members:
            continue
        seen_members.add(item["id"])
        name = item.get("name") or item["id"]
        email = item.get("email") or f"{item['id']}@archived.invalid"
        raw_weeks = ((item.get("workPattern") or {}).get("weeks") or [item.get("availableDays", [])])[:5]
        legacy_tele = {int(day) for day in item.get("teleDays", [])}
        pattern_weeks = []
        for raw_week in raw_weeks:
            if isinstance(raw_week, dict):
                working_days = [int(day) for day in raw_week.get("workingDays", [])]
                tele_days = [int(day) for day in raw_week.get("teleDays", [])]
            else:
                working_days = [int(day) for day in raw_week]
                tele_days = sorted(legacy_tele.intersection(working_days))
            pattern_weeks.append({"workingDays": working_days, "teleDays": tele_days})
        session.add(
            Member(
                id=item["id"],
                name=name,
                normalized_name=normalized(name),
                email=email,
                normalized_email=normalized(email),
                color=item.get("color") or automatic_color(email, "member"),
                management_quota=min(5, max(0, int(item.get("managementQuota", 0)))),
                is_active=bool(item.get("active", True)),
                work_pattern_weeks=len(pattern_weeks),
                archived_at=parse_date(item["archivedAt"]) if item.get("archivedAt") else None,
            )
        )
        session.flush()
        for week_index, week in enumerate(pattern_weeks):
            for weekday in week["workingDays"]:
                session.add(
                    MemberAvailableDay(member_id=item["id"], week_index=week_index, weekday=int(weekday))
                )
            for weekday in week["teleDays"]:
                session.add(MemberTeleDay(member_id=item["id"], week_index=week_index, weekday=int(weekday)))
        for agenda_id in item.get("allowedTypes", []):
            if agenda_id in seen_agendas:
                session.add(MemberCapability(member_id=item["id"], agenda_id=agenda_id))
        for agenda_id, preference in item.get("agendaPreferences", {}).items():
            if agenda_id in seen_agendas and int(preference) in {-1, 1}:
                session.add(
                    MemberAgendaPreference(
                        member_id=item["id"],
                        agenda_id=agenda_id,
                        preference=int(preference),
                    )
                )
        for rule in item.get("fixedRules", []):
            if rule.get("type") in seen_agendas:
                session.add(
                    FixedRule(
                        id=rule.get("id") or uid(),
                        member_id=item["id"],
                        agenda_id=rule["type"],
                        weekday=int(rule["weekday"]),
                    )
                )
        for absence in item.get("absences", []):
            category = absence.get("category", "vacances")
            if category not in {"vacances", "postguardia"}:
                continue
            session.add(
                Absence(
                    id=absence.get("id") or uid(),
                    member_id=item["id"],
                    category=category,
                    start=parse_date(absence["start"]),
                    end=parse_date(absence["end"]),
                    notes=absence.get("notes", ""),
                )
            )

    for holiday in state.get("holidays", []):
        session.add(Holiday(date=parse_date(holiday)))
    for guard in state.get("guards", []):
        if guard.get("memberId") in seen_members:
            session.add(Guard(id=guard.get("id") or uid(), member_id=guard["memberId"], date=parse_date(guard["date"])))

    records = [*state.get("published", [])]
    if state.get("draft"):
        records.append(state["draft"])
    records.sort(key=lambda record: parse_datetime(record.get("generatedAt") or record.get("publishedAt")))
    for record in records:
        import_calendar_record(session, record, seen_members, seen_agendas)


def import_calendar_record(
    session: Session,
    record: dict[str, Any],
    member_ids: set[str],
    agenda_ids: set[str],
) -> None:
    dates = {
        parse_date(item["date"])
        for item in [*record.get("assignments", []), *record.get("unfilled", [])]
        if item.get("date")
    }
    if dates:
        session.execute(delete(Assignment).where(Assignment.date.in_(dates)))
        session.execute(delete(Vacancy).where(Vacancy.date.in_(dates)))
    for item in record.get("assignments", []):
        if item.get("memberId") not in member_ids:
            continue
        assignment_type = item.get("type")
        agenda_id = assignment_type if assignment_type in agenda_ids else None
        kind = (
            "no_assignment"
            if assignment_type == "no_assignment"
            else "management"
            if assignment_type == "management"
            else "assigned"
        )
        if kind == "assigned" and not agenda_id:
            continue
        agenda = session.get(Agenda, agenda_id) if agenda_id else None
        load_percentage = agenda.load_percentage if agenda else 100 if kind == "management" else 0
        session.add(
            Assignment(
                id=item.get("id") or uid(),
                date=parse_date(item["date"]),
                member_id=item["memberId"],
                agenda_id=agenda_id,
                kind=kind,
                load_percentage=load_percentage,
                locked=bool(item.get("locked")),
                fixed=bool(item.get("fixed")),
                extra=bool(item.get("extra")),
                manually_modified=bool(item.get("manuallyModified") or item.get("locked")),
                management=kind == "management" or bool(item.get("management")),
            )
        )
    for item in record.get("unfilled", []):
        if item.get("type") in agenda_ids:
            session.add(Vacancy(date=parse_date(item["date"]), agenda_id=item["type"]))
    conditions = record.get("conditions", {})
    for item in conditions.get("guards", []):
        if item.get("memberId") in member_ids:
            guard_date = parse_date(item["date"])
            existing_guard = session.scalar(select(Guard).where(Guard.date == guard_date))
            if existing_guard:
                existing_guard.member_id = item["memberId"]
            else:
                session.add(
                    Guard(
                        id=item.get("id") or uid(),
                        member_id=item["memberId"],
                        date=guard_date,
                    )
                )
    for item in conditions.get("absences", []):
        if item.get("memberId") not in member_ids:
            continue
        absence_start = parse_date(item["start"])
        absence_end = parse_date(item["end"])
        existing_absence = session.scalar(
            select(Absence).where(
                Absence.member_id == item["memberId"],
                Absence.category == item.get("category", "vacances"),
                Absence.start == absence_start,
                Absence.end == absence_end,
            )
        )
        if not existing_absence:
            session.add(
                Absence(
                    id=item.get("id") or uid(),
                    member_id=item["memberId"],
                    category=item.get("category", "vacances"),
                    start=absence_start,
                    end=absence_end,
                    notes="",
                )
            )


def serialize_member(session: Session, member: Member) -> dict[str, Any]:
    pattern_days = list(
        session.scalars(
            select(MemberAvailableDay)
            .where(MemberAvailableDay.member_id == member.id)
            .order_by(MemberAvailableDay.week_index, MemberAvailableDay.weekday)
        )
    )
    pattern_weeks: list[dict[str, list[int]]] = [
        {"workingDays": [], "teleDays": []} for _ in range(member.work_pattern_weeks)
    ]
    for pattern_day in pattern_days:
        if pattern_day.week_index < len(pattern_weeks):
            pattern_weeks[pattern_day.week_index]["workingDays"].append(pattern_day.weekday)
    pattern_tele_days = list(
        session.scalars(
            select(MemberTeleDay)
            .where(MemberTeleDay.member_id == member.id)
            .order_by(MemberTeleDay.week_index, MemberTeleDay.weekday)
        )
    )
    for tele_day in pattern_tele_days:
        if tele_day.week_index < len(pattern_weeks):
            pattern_weeks[tele_day.week_index]["teleDays"].append(tele_day.weekday)
    available = sorted({weekday for week in pattern_weeks for weekday in week["workingDays"]})
    tele = sorted({weekday for week in pattern_weeks for weekday in week["teleDays"]})
    capabilities = list(
        session.scalars(
            select(MemberCapability.agenda_id)
            .where(MemberCapability.member_id == member.id)
            .order_by(MemberCapability.id)
        )
    )
    preferences = {
        item.agenda_id: item.preference
        for item in session.scalars(
            select(MemberAgendaPreference)
            .where(MemberAgendaPreference.member_id == member.id)
            .order_by(MemberAgendaPreference.agenda_id)
        )
    }
    rules = list(session.scalars(select(FixedRule).where(FixedRule.member_id == member.id).order_by(FixedRule.weekday)))
    absences = list(session.scalars(select(Absence).where(Absence.member_id == member.id).order_by(Absence.start)))
    vacation_dates: list[str] = []
    for absence in absences:
        if absence.category != "vacances":
            continue
        current = absence.start
        while current <= absence.end:
            vacation_dates.append(current.isoformat())
            current += timedelta(days=1)
    status_history = list(
        session.scalars(
            select(MemberStatusChange)
            .where(MemberStatusChange.member_id == member.id)
            .order_by(MemberStatusChange.changed_at)
        )
    )
    return {
        "id": member.id,
        "name": member.name,
        "email": member.email,
        "color": member.color,
        "active": member.is_active,
        "availableDays": available,
        "workPattern": {"weeks": pattern_weeks},
        "teleDays": tele,
        "allowedTypes": capabilities,
        "agendaPreferences": preferences,
        "managementQuota": member.management_quota,
        "fixedRules": [{"id": item.id, "weekday": item.weekday, "type": item.agenda_id} for item in rules],
        "vacations": [
            {
                "id": item.id,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
            }
            for item in absences
            if item.category == "vacances"
        ],
        "vacationDates": vacation_dates,
        "statusHistory": [
            {"active": item.active, "changedAt": item.changed_at.isoformat() + "Z"}
            for item in status_history
        ],
        **({"archivedAt": member.archived_at.isoformat()} if member.archived_at else {}),
    }


def serialize_calendar(session: Session) -> dict[str, Any]:
    events = list(session.scalars(select(Assignment).order_by(Assignment.date, Assignment.id)))
    vacancies = list(session.scalars(select(Vacancy).order_by(Vacancy.date, Vacancy.id)))
    guards = list(session.scalars(select(Guard).order_by(Guard.date, Guard.id)))
    guard_transfers = list(
        session.scalars(
            select(GuardTransfer)
            .order_by(GuardTransfer.created_at.desc(), GuardTransfer.id)
        )
    )
    absences = list(session.scalars(select(Absence).order_by(Absence.start, Absence.id)))
    return {
        "events": [
            {
                "id": item.id,
                "date": item.date.isoformat(),
                "memberId": item.member_id,
                "type": (
                    item.agenda_id
                    or ("management" if item.kind == "management" or item.management else "no_assignment")
                ),
                "loadPercentage": item.load_percentage,
                **({"locked": True} if item.locked else {}),
                **({"fixed": True} if item.fixed else {}),
                **({"extra": True} if item.extra else {}),
                **({"manuallyModified": True} if item.manually_modified else {}),
                **({"management": True} if item.management else {}),
            }
            for item in events
        ],
        "vacancies": [
            {"id": item.id, "date": item.date.isoformat(), "type": item.agenda_id}
            for item in vacancies
        ],
        "guards": [
            {"id": item.id, "memberId": item.member_id, "date": item.date.isoformat()}
            for item in guards
        ],
        "guardTransfers": [
            {
                "id": item.id,
                "operationId": item.operation_id,
                "operationKind": item.operation_kind,
                "date": item.guard_date.isoformat(),
                "fromMemberId": item.from_member_id,
                "toMemberId": item.to_member_id,
                "createdAt": item.created_at.isoformat() + "Z",
                "note": item.note,
                "impact": json.loads(item.impact_json or "{}"),
            }
            for item in guard_transfers
        ],
        "absences": [
            {
                "id": item.id,
                "memberId": item.member_id,
                "category": item.category,
                "start": item.start.isoformat(),
                "end": item.end.isoformat(),
            }
            for item in absences
        ],
    }


def bootstrap(session: Session, catalog: HospitalCatalog) -> dict[str, Any]:
    settings = session.get(AppSettings, 1)
    if not settings:
        raise RuntimeError("Settings not initialized")
    members = list(session.scalars(select(Member).order_by(Member.name)))
    agendas = list(session.scalars(select(Agenda).order_by(Agenda.id)))
    selected_hospitals = list(session.scalars(select(Hospital).order_by(Hospital.created_at)))
    coverage_rows = list(session.scalars(select(Coverage)))
    recurrence_rows = list(
        session.scalars(select(AgendaRecurrence).order_by(AgendaRecurrence.agenda_id, AgendaRecurrence.ordinal))
    )
    recurrences: dict[str, list[dict[str, Any]]] = {}
    for recurrence in recurrence_rows:
        recurrences.setdefault(recurrence.agenda_id, []).append(
            {
                "id": recurrence.id,
                "ordinal": recurrence.ordinal,
                "weekday": recurrence.weekday,
                "slots": recurrence.slots,
            }
        )
    coverage: dict[str, dict[str, int]] = {str(day): {} for day in range(1, 6)}
    for item in coverage_rows:
        coverage[str(item.weekday)][item.agenda_id] = item.slots
    hospitals = []
    for selected in selected_hospitals:
        details = catalog.by_id.get(selected.catalog_id, {}) if selected.location_known else {}
        hospitals.append(
            {
                **details,
                "id": selected.id,
                "catalogId": selected.catalog_id,
                "name": details.get("name") or selected.name or "Centre sense nom",
                "address": details.get("address") or details.get("streetAddress") or selected.address or "",
                "locationKnown": selected.location_known,
            }
        )
    active_agendas = [item for item in agendas if item.archived_at is None]
    archived_agendas = [item for item in agendas if item.archived_at is not None]

    def agenda_payload(item: Agenda) -> dict[str, Any]:
        return {
            "id": item.id,
            "name": item.name,
            "hospitalId": item.hospital_catalog_id,
            "telematic": item.telematic,
            "shift": item.shift,
            "color": item.color,
            "priority": item.priority,
            "loadPercentage": item.load_percentage,
            "recurrences": recurrences.get(item.id, []),
            **({"archivedAt": item.archived_at.isoformat(), "active": False} if item.archived_at else {}),
        }

    return {
        "language": settings.language,
        "colorSchemeVersion": settings.color_scheme_version,
        "planningRevision": settings.planning_revision,
        "team": [serialize_member(session, item) for item in members if item.archived_at is None],
        "archivedTeam": [serialize_member(session, item) for item in members if item.archived_at is not None],
        "agendas": [agenda_payload(item) for item in active_agendas],
        "archivedAgendas": [agenda_payload(item) for item in archived_agendas],
        "coverage": coverage,
        "holidays": [item.isoformat() for item in session.scalars(select(Holiday.date).order_by(Holiday.date))],
        "hospitals": hospitals,
        "calendar": serialize_calendar(session),
    }


def clear_member_configuration(session: Session, member_id: str) -> None:
    for model in (MemberAvailableDay, MemberTeleDay, MemberCapability, FixedRule):
        session.execute(delete(model).where(model.member_id == member_id))


def clear_agenda_coverage(session: Session, agenda_id: str) -> None:
    session.execute(delete(Coverage).where(Coverage.agenda_id == agenda_id))
    session.execute(delete(AgendaRecurrence).where(AgendaRecurrence.agenda_id == agenda_id))


def job_payload(job: GenerationJob) -> dict[str, Any]:
    try:
        decoded = json.loads(job.result_json) if job.result_json else {}
    except (json.JSONDecodeError, TypeError):
        decoded = {}
    stored = decoded if isinstance(decoded, dict) else {}
    try:
        snapshot = json.loads(job.input_snapshot) if job.input_snapshot else {}
    except (json.JSONDecodeError, TypeError):
        snapshot = {}
    snapshot_config = snapshot.get("solver_config", {}) if isinstance(snapshot, dict) else {}
    candidate_error = stored.get("error", {})
    stored_error = candidate_error if isinstance(candidate_error, dict) else {}
    return {
        "id": job.id,
        "status": job.status,
        "startMonth": job.start_month,
        "endMonth": job.end_month,
        "startDate": (job.start_date or date.fromisoformat(f"{job.start_month}-01")).isoformat(),
        "endDate": (job.end_date or month_end(job.end_month)).isoformat(),
        "inputRevision": job.input_revision,
        "optimizationMode": snapshot_config.get("optimizationMode", "fairness"),
        "error": {
            "code": job.error_code,
            "message": job.error_message,
            "field": stored_error.get("field"),
            "details": stored_error.get("details", {}),
        }
        if job.error_code
        else None,
        "createdAt": job.created_at.isoformat() + "Z",
        "completedAt": job.completed_at.isoformat() + "Z" if job.completed_at else None,
    }
