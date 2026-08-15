from __future__ import annotations

import random
import re
from datetime import date, datetime, timedelta
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from pinendar.application.state import (
    DomainError,
    bump_revision,
    clear_agenda_coverage,
    clear_member_configuration,
    normalized,
    parse_date,
    serialize_member,
    uid,
)
from pinendar.domain.fairness import operational_fairness_score, operational_person_distances
from pinendar.infrastructure.catalog import HospitalCatalog
from pinendar.infrastructure.models import (
    Absence,
    Agenda,
    AgendaRecurrence,
    AppSettings,
    Assignment,
    Coverage,
    FixedRule,
    FixedRuleAgenda,
    Guard,
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


def madrid_today() -> date:
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


HSL_HUE = re.compile(r"hsl\(\s*(\d+(?:\.\d+)?)")


def color_hue(color: str) -> int | None:
    match = HSL_HUE.match(color)
    return round(float(match.group(1))) % 360 if match else None


def random_color(kind: str, used_colors: list[str] | None = None) -> str:
    used_hues = [hue for color in used_colors or [] if (hue := color_hue(color)) is not None]
    generator = random.SystemRandom()
    if used_hues:
        distances = {
            hue: min(min(abs(hue - used), 360 - abs(hue - used)) for used in used_hues)
            for hue in range(360)
        }
        best_distance = max(distances.values())
        hue = generator.choice([candidate for candidate, distance in distances.items() if distance == best_distance])
    else:
        hue = generator.randrange(360)
    return f"hsl({hue} {'58% 78%' if kind == 'member' else '90% 56%'})"


def distinct_color(session: Session, kind: str, record_id: str | None = None, avoid: str | None = None) -> str:
    model = Member if kind == "member" else Agenda
    query = select(model.color).where(model.archived_at.is_(None))
    if record_id:
        query = query.where(model.id != record_id)
    used = list(session.scalars(query))
    if avoid:
        used.append(avoid)
    return random_color(kind, used)


def reassign_agenda_colors(session: Session) -> int:
    agendas = list(session.scalars(select(Agenda).where(Agenda.archived_at.is_(None)).order_by(Agenda.name)))
    assigned: list[str] = []
    for agenda in agendas:
        agenda.color = random_color("agenda", assigned)
        assigned.append(agenda.color)
    settings = session.get(AppSettings, 1)
    if settings:
        settings.color_scheme_version = 4
    return len(agendas)


def assert_member_identity_available(session: Session, name: str, email: str, member_id: str | None = None) -> None:
    name_query = select(Member).where(Member.normalized_name == normalized(name))
    email_query = select(Member).where(Member.normalized_email == normalized(email))
    if member_id:
        name_query = name_query.where(Member.id != member_id)
        email_query = email_query.where(Member.id != member_id)
    name_match = session.scalar(name_query)
    if name_match:
        raise DomainError("MEMBER_NAME_EXISTS", f"Ja existeix una persona amb el nom {name}", field="name")
    email_match = session.scalar(email_query)
    if email_match:
        raise DomainError("MEMBER_EMAIL_EXISTS", f"Ja existeix una persona amb el correu {email}", field="email")


def normalize_work_pattern(payload: dict[str, Any]) -> list[dict[str, list[int]]]:
    pattern = payload.get("workPattern")
    legacy_tele = {int(day) for day in payload.get("teleDays", [])}
    if pattern:
        raw_weeks = pattern.get("weeks", [])
    else:
        raw_weeks = [payload.get("availableDays", [])]
    weeks: list[dict[str, list[int]]] = []
    for raw_week in raw_weeks:
        if isinstance(raw_week, dict):
            working_days = [int(day) for day in raw_week.get("workingDays", [])]
            tele_days = [int(day) for day in raw_week.get("teleDays", [])]
        else:
            working_days = [int(day) for day in raw_week]
            tele_days = sorted(legacy_tele.intersection(working_days))
        weeks.append({"workingDays": working_days, "teleDays": tele_days})
    if not 1 <= len(weeks) <= 5:
        raise DomainError(
            "INVALID_WORK_PATTERN",
            "El patró de treball necessita entre una i cinc setmanes",
            field="workPattern",
        )
    for week in weeks:
        working = week["workingDays"]
        tele = week["teleDays"]
        if (
            len(working) != len(set(working))
            or len(tele) != len(set(tele))
            or not set(working).issubset(range(1, 6))
            or not set(tele).issubset(working)
        ):
            raise DomainError(
                "INVALID_WORK_PATTERN",
                "El patró de treball conté dies no vàlids, repetits o telemàtics fora dels dies treballats",
                field="workPattern",
            )
    available = sorted({day for week in weeks for day in week["workingDays"]})
    if not available:
        raise DomainError(
            "INVALID_WORK_PATTERN", "El patró de treball ha de contenir almenys un dia", field="workPattern"
        )
    payload["workPattern"] = {"weeks": weeks}
    payload["availableDays"] = available
    payload["teleDays"] = sorted({day for week in weeks for day in week["teleDays"]})
    return weeks


def validate_member_payload(session: Session, payload: dict[str, Any], member_id: str | None = None) -> None:
    assert_member_identity_available(session, payload["name"], payload["email"], member_id)
    weeks = normalize_work_pattern(payload)
    available = {day for week in weeks for day in week["workingDays"]}
    active_agendas = {item.id: item for item in session.scalars(select(Agenda).where(Agenda.archived_at.is_(None)))}
    allowed = set(payload["allowedTypes"])
    preferences = payload.get("agendaPreferences", {})
    if not set(preferences).issubset(active_agendas) or any(
        int(value) not in {-1, 0, 1} for value in preferences.values()
    ):
        raise DomainError(
            "INVALID_AGENDA_PREFERENCE",
            "Les preferències contenen una agenda o valor no vàlid",
            field="agendaPreferences",
        )
    management_quota = int(payload.get("managementQuota", 0))
    if not 0 <= management_quota <= 5:
        raise DomainError(
            "INVALID_MANAGEMENT_QUOTA",
            "Els dies de gestió han d’estar entre 0 i 5",
            field="managementQuota",
        )
    payload["managementQuota"] = management_quota
    if not allowed.issubset(active_agendas):
        raise DomainError("INVALID_CAPABILITY", "Hi ha una agenda no habilitada", field="allowedTypes")
    weekdays: set[int] = set()
    for rule in payload.get("fixedRules", []):
        weekday = int(rule["weekday"])
        if weekday in weekdays:
            raise DomainError(
                "DUPLICATE_FIXED_RULE_DAY",
                "Una persona no pot tenir dues regles fixes el mateix dia",
                field="fixedRules",
            )
        weekdays.add(weekday)
        required_mode = rule.get("requiredMode", "all")
        required_ids = list(dict.fromkeys(rule.get("requiredAgendaIds", [])))
        forbidden_ids = list(dict.fromkeys(rule.get("forbiddenAgendaIds", [])))
        referenced_ids = set(required_ids) | set(forbidden_ids)
        if (
            required_mode not in {"all", "one"}
            or not referenced_ids
            or set(required_ids) & set(forbidden_ids)
        ):
            raise DomainError(
                "INVALID_FIXED_RULE",
                "La regla fixa conté condicions buides o contradictòries",
                field="fixedRules",
            )
        if weekday not in available or not referenced_ids.issubset(allowed):
            raise DomainError(
                "INVALID_FIXED_RULE", "La regla fixa utilitza una agenda o dia no habilitat", field="fixedRules"
            )
        if not referenced_ids.issubset(active_agendas):
            raise DomainError(
                "INVALID_FIXED_RULE", "La regla fixa utilitza una agenda inexistent", field="fixedRules"
            )
        telework_day = any(weekday in week["teleDays"] for week in weeks)
        required_telematic = [
            active_agendas[agenda_id].telematic for agenda_id in required_ids
        ]
        if telework_day and required_telematic and (
            (required_mode == "all" and not all(required_telematic))
            or (required_mode == "one" and not any(required_telematic))
        ):
            raise DomainError(
                "TELEWORK_AGENDA_REQUIRED",
                "En un dia telemàtic només es pot assignar una agenda telemàtica",
                field="fixedRules",
            )
        required_occurrences: dict[str, set[int]] = {}
        for agenda_id in required_ids:
            coverage = (
                session.scalar(
                    select(Coverage.slots).where(
                        Coverage.weekday == weekday,
                        Coverage.agenda_id == agenda_id,
                    )
                )
                or 0
            )
            recurrence_ordinals = set(
                session.scalars(
                    select(AgendaRecurrence.ordinal).where(
                        AgendaRecurrence.weekday == weekday,
                        AgendaRecurrence.agenda_id == agenda_id,
                    )
                )
            )
            if coverage <= 0 and not recurrence_ordinals:
                raise DomainError(
                    "FIXED_RULE_CAPACITY",
                    "Cada agenda obligatòria necessita almenys una plaça de cobertura",
                    field="fixedRules",
                )
            required_occurrences[agenda_id] = (
                set(range(1, 6)) if coverage > 0 else recurrence_ordinals
            )
        if required_mode == "all" and max(
            (
                sum(
                    active_agendas[agenda_id].load_percentage
                    for agenda_id in required_ids
                    if ordinal in required_occurrences[agenda_id]
                )
                for ordinal in range(1, 6)
            ),
            default=0,
        ) > 100:
            raise DomainError(
                "FIXED_RULE_LOAD",
                "Les agendes obligatòries superen el 100% de càrrega diària",
                field="fixedRules",
            )
        rule["requiredMode"] = required_mode
        rule["requiredAgendaIds"] = required_ids
        rule["forbiddenAgendaIds"] = forbidden_ids
def save_member(session: Session, payload: dict[str, Any], member_id: str | None = None) -> dict[str, Any]:
    validate_member_payload(session, payload, member_id)
    pattern_weeks = payload["workPattern"]["weeks"]
    member = session.get(Member, member_id) if member_id else None
    if member_id and (not member or member.archived_at):
        raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada")
    if not member:
        member = Member(
            id=uid(),
            name=payload["name"],
            normalized_name=normalized(payload["name"]),
            email=payload["email"],
            normalized_email=normalized(payload["email"]),
            color=distinct_color(session, "member"),
            management_quota=int(payload.get("managementQuota", 0)),
            is_active=bool(payload.get("active", True)),
            has_completed_generation=False,
            work_pattern_weeks=len(pattern_weeks),
        )
        session.add(member)
        session.flush()
    else:
        member.name = payload["name"]
        member.normalized_name = normalized(payload["name"])
        member.email = payload["email"]
        member.normalized_email = normalized(payload["email"])
        member.management_quota = int(payload.get("managementQuota", 0))
        member.work_pattern_weeks = len(pattern_weeks)
        next_active = bool(payload.get("active", True))
        if member.is_active != next_active:
            member.is_active = next_active
            session.add(MemberStatusChange(id=uid(), member_id=member.id, active=next_active))
        clear_member_configuration(session, member.id)
        session.execute(
            delete(MemberAgendaPreference).where(
                MemberAgendaPreference.member_id == member.id
            )
        )
    for week_index, week in enumerate(pattern_weeks):
        for weekday in week["workingDays"]:
            session.add(MemberAvailableDay(member_id=member.id, week_index=week_index, weekday=int(weekday)))
        for weekday in week["teleDays"]:
            session.add(MemberTeleDay(member_id=member.id, week_index=week_index, weekday=int(weekday)))
    for agenda_id in payload["allowedTypes"]:
        session.add(MemberCapability(member_id=member.id, agenda_id=agenda_id))
    for agenda_id, preference in payload.get("agendaPreferences", {}).items():
        if int(preference):
            session.add(
                MemberAgendaPreference(
                    member_id=member.id,
                    agenda_id=agenda_id,
                    preference=int(preference),
                )
            )
    for rule in payload.get("fixedRules", []):
        fixed_rule = FixedRule(
            id=rule.get("id") or uid(),
            member_id=member.id,
            weekday=int(rule["weekday"]),
            required_mode=rule["requiredMode"],
        )
        session.add(fixed_rule)
        session.flush()
        for agenda_id in rule["requiredAgendaIds"]:
            session.add(
                FixedRuleAgenda(
                    rule_id=fixed_rule.id,
                    agenda_id=agenda_id,
                    effect="required",
                )
            )
        for agenda_id in rule["forbiddenAgendaIds"]:
            session.add(
                FixedRuleAgenda(
                    rule_id=fixed_rule.id,
                    agenda_id=agenda_id,
                    effect="forbidden",
                )
            )
    replace_member_vacations(session, member, payload.get("vacationDates", []))
    bump_revision(session)
    session.flush()
    return serialize_member(session, member)


def vacation_dates(session: Session, member_id: str) -> set[date]:
    dates: set[date] = set()
    for item in session.scalars(select(Absence).where(Absence.member_id == member_id, Absence.category == "vacances")):
        current = item.start
        while current <= item.end:
            dates.add(current)
            current += timedelta(days=1)
    return dates


def replace_member_vacations(session: Session, member: Member, values: list[str]) -> None:
    submitted = {parse_date(value) for value in values}
    today = madrid_today()
    existing_past = {value for value in vacation_dates(session, member.id) if value < today}
    submitted_past = {value for value in submitted if value < today}
    if submitted_past != existing_past:
        raise DomainError(
            "PAST_VACATIONS_IMMUTABLE",
            "Els dies de vacances passats no es poden modificar",
            field="vacationDates",
        )
    session.execute(
        delete(Absence).where(Absence.member_id == member.id, Absence.category == "vacances")
    )
    ordered = sorted(submitted)
    if not ordered:
        return
    start = end = ordered[0]
    for value in ordered[1:]:
        if value == end + timedelta(days=1):
            end = value
            continue
        session.add(Absence(id=uid(), member_id=member.id, category="vacances", start=start, end=end))
        start = end = value
    session.add(Absence(id=uid(), member_id=member.id, category="vacances", start=start, end=end))


def archive_member(session: Session, member_id: str) -> None:
    member = session.get(Member, member_id)
    if not member or member.archived_at:
        raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada")
    today = madrid_today()
    yesterday = today - timedelta(days=1)
    member.archived_at = today
    clear_member_configuration(session, member_id)
    session.execute(delete(Guard).where(Guard.member_id == member_id, Guard.date >= today))
    session.execute(delete(Assignment).where(Assignment.member_id == member_id, Assignment.date >= today))
    for item in session.scalars(select(Absence).where(Absence.member_id == member_id, Absence.end >= today)):
        if item.start < today:
            item.end = yesterday
        else:
            session.delete(item)
    bump_revision(session)


def save_agenda(session: Session, payload: dict[str, Any], agenda_id: str | None = None) -> dict[str, Any]:
    hospital = session.scalar(select(Hospital).where(Hospital.catalog_id == payload["hospitalId"]))
    if not hospital:
        raise DomainError("HOSPITAL_NOT_SELECTED", "Selecciona un hospital vàlid", field="hospitalId")
    agenda = session.get(Agenda, agenda_id) if agenda_id else None
    if agenda_id and (not agenda or agenda.archived_at):
        raise DomainError("AGENDA_NOT_FOUND", "Agenda no trobada")
    priority = int(payload.get("priority", 3))
    if not 1 <= priority <= 4:
        raise DomainError("INVALID_AGENDA_PRIORITY", "La prioritat ha d’estar entre 1 i 4", field="priority")
    shift = payload.get("shift")
    if shift not in {"morning", "afternoon"}:
        raise DomainError(
            "INVALID_AGENDA_SHIFT",
            "El torn ha de ser de matí o tarda",
            field="shift",
        )
    load_percentage = int(payload.get("loadPercentage", 100))
    if load_percentage not in {50, 100}:
        raise DomainError(
            "INVALID_AGENDA_LOAD",
            "La càrrega de l’agenda ha de ser del 50% o del 100%",
            field="loadPercentage",
        )
    recurrences = payload.get("recurrences", [])
    coverage_values = {weekday: int(payload.get("coverage", {}).get(str(weekday), 0)) for weekday in range(1, 6)}
    for weekday, slots in coverage_values.items():
        if slots < 0:
            raise DomainError("INVALID_COVERAGE", "La cobertura no pot ser negativa", field=f"coverage.{weekday}")
    conflicting_rules: dict[str, tuple[FixedRule, Member]] = {}
    telework_rule_conflicts: dict[str, tuple[FixedRule, Member]] = {}
    if agenda:
        fixed_rules = session.execute(
            select(FixedRule, Member)
            .join(FixedRuleAgenda, FixedRuleAgenda.rule_id == FixedRule.id)
            .join(Member, Member.id == FixedRule.member_id)
            .where(
                FixedRuleAgenda.agenda_id == agenda.id,
                FixedRuleAgenda.effect == "required",
            )
        ).all()
        for rule, member in fixed_rules:
            required_ids = list(
                session.scalars(
                    select(FixedRuleAgenda.agenda_id).where(
                        FixedRuleAgenda.rule_id == rule.id,
                        FixedRuleAgenda.effect == "required",
                    )
                )
            )
            demand_occurrences: list[set[int]] = []
            telematic_available: list[bool] = []
            required_loads: list[int] = []
            for required_id in required_ids:
                if required_id == agenda.id:
                    demand_occurrences.append(
                        set(range(1, 6))
                        if coverage_values[rule.weekday] > 0
                        else {
                            int(recurrence["ordinal"])
                            for recurrence in recurrences
                            if int(recurrence["weekday"]) == rule.weekday
                        }
                    )
                    telematic_available.append(bool(payload.get("telematic", False)))
                    required_loads.append(load_percentage)
                    continue
                weekly_demand = bool(
                    session.scalar(
                        select(Coverage.slots).where(
                            Coverage.weekday == rule.weekday,
                            Coverage.agenda_id == required_id,
                        )
                    )
                )
                demand_occurrences.append(
                    set(range(1, 6))
                    if weekly_demand
                    else set(
                        session.scalars(
                            select(AgendaRecurrence.ordinal).where(
                                AgendaRecurrence.weekday == rule.weekday,
                                AgendaRecurrence.agenda_id == required_id,
                            )
                        )
                    )
                )
                required_agenda = session.get(Agenda, required_id)
                telematic_available.append(bool(required_agenda and required_agenda.telematic))
                required_loads.append(
                    required_agenda.load_percentage if required_agenda else 100
                )
            demand_valid = (
                all(demand_occurrences)
                if rule.required_mode == "all"
                else any(demand_occurrences)
            )
            max_required_load = max(
                (
                    sum(
                        load
                        for occurrences, load in zip(
                            demand_occurrences, required_loads, strict=True
                        )
                        if ordinal in occurrences
                    )
                    for ordinal in range(1, 6)
                ),
                default=0,
            )
            if not demand_valid or (
                rule.required_mode == "all" and max_required_load > 100
            ):
                conflicting_rules[rule.id] = (rule, member)
            tele_day = session.scalar(
                select(MemberTeleDay.id)
                .where(
                    MemberTeleDay.member_id == member.id,
                    MemberTeleDay.weekday == rule.weekday,
                )
                .limit(1)
            )
            telematic_valid = (
                all(telematic_available)
                if rule.required_mode == "all"
                else any(telematic_available)
            )
            if tele_day and not telematic_valid:
                telework_rule_conflicts[rule.id] = (rule, member)
    if telework_rule_conflicts:
        raise DomainError(
            "TELEWORK_AGENDA_REQUIRED",
            "Una regla fixa en dia telemàtic necessita una agenda telemàtica",
            field="telematic",
            details={
                "rules": [
                    {
                        "id": rule.id,
                        "memberId": member.id,
                        "memberName": member.name,
                        "weekday": rule.weekday,
                        "agendaId": agenda_id,
                        "agendaName": payload["name"],
                    }
                    for rule, member in telework_rule_conflicts.values()
                ]
            },
        )
    if conflicting_rules and not payload.get("deleteConflictingFixedRules", False):
        raise DomainError(
            "FIXED_RULE_CAPACITY",
            "La nova cobertura afecta regles fixes existents",
            field="coverage",
            details={
                "rules": [
                    {
                        "id": rule.id,
                        "memberId": member.id,
                        "memberName": member.name,
                        "weekday": rule.weekday,
                        "agendaId": agenda_id,
                        "agendaName": payload["name"],
                    }
                    for rule, member in conflicting_rules.values()
                ]
            },
        )
    for rule, _member in conflicting_rules.values():
        session.delete(rule)
    recurrence_keys: set[tuple[int, int]] = set()
    for index, recurrence in enumerate(recurrences):
        ordinal = int(recurrence["ordinal"])
        weekday = int(recurrence["weekday"])
        slots = int(recurrence["slots"])
        if not 1 <= ordinal <= 5 or not 1 <= weekday <= 5 or slots != 1:
            raise DomainError(
                "INVALID_AGENDA_RECURRENCE",
                "La regla especial té valors invàlids",
                field=f"recurrences.{index}",
            )
        key = (ordinal, weekday)
        if key in recurrence_keys:
            raise DomainError(
                "DUPLICATE_AGENDA_RECURRENCE",
                "No es pot repetir el mateix dia ordinal",
                field=f"recurrences.{index}",
            )
        recurrence_keys.add(key)
    if not agenda:
        generated_id = f"agenda_{uuid4().hex[:10]}"
        agenda = Agenda(
            id=generated_id,
            name=payload["name"],
            hospital_catalog_id=payload["hospitalId"],
            telematic=bool(payload["telematic"]),
            shift=shift,
            color=distinct_color(session, "agenda"),
            priority=priority,
            load_percentage=load_percentage,
        )
        session.add(agenda)
        session.flush()
    else:
        agenda.name = payload["name"]
        agenda.hospital_catalog_id = payload["hospitalId"]
        agenda.telematic = bool(payload["telematic"])
        agenda.shift = shift
        agenda.priority = priority
        agenda.load_percentage = load_percentage
        clear_agenda_coverage(session, agenda.id)
    for weekday in range(1, 6):
        slots = coverage_values[weekday]
        session.add(Coverage(agenda_id=agenda.id, weekday=weekday, slots=slots))
    for recurrence in recurrences:
        session.add(
            AgendaRecurrence(
                id=recurrence.get("id") or uid(),
                agenda_id=agenda.id,
                ordinal=int(recurrence["ordinal"]),
                weekday=int(recurrence["weekday"]),
                slots=int(recurrence["slots"]),
            )
        )
    bump_revision(session)
    session.flush()
    return {
        "id": agenda.id,
        "name": agenda.name,
        "hospitalId": agenda.hospital_catalog_id,
        "telematic": agenda.telematic,
        "shift": agenda.shift,
        "color": agenda.color,
        "priority": agenda.priority,
        "loadPercentage": agenda.load_percentage,
        "recurrences": [
            {
                "id": item.id,
                "ordinal": item.ordinal,
                "weekday": item.weekday,
                "slots": item.slots,
            }
            for item in session.scalars(
                select(AgendaRecurrence)
                .where(AgendaRecurrence.agenda_id == agenda.id)
                .order_by(AgendaRecurrence.ordinal, AgendaRecurrence.weekday)
            )
        ],
    }


def archive_agenda(session: Session, agenda_id: str) -> None:
    agenda = session.get(Agenda, agenda_id)
    if not agenda or agenda.archived_at:
        raise DomainError("AGENDA_NOT_FOUND", "Agenda no trobada")
    today = madrid_today()
    agenda.archived_at = today
    related_rule_ids = list(
        session.scalars(
            select(FixedRuleAgenda.rule_id).where(
                FixedRuleAgenda.agenda_id == agenda_id
            )
        )
    )
    session.execute(delete(MemberCapability).where(MemberCapability.agenda_id == agenda_id))
    if related_rule_ids:
        session.execute(
            delete(FixedRuleAgenda).where(FixedRuleAgenda.agenda_id == agenda_id)
        )
        session.flush()
        for rule_id in related_rule_ids:
            has_conditions = session.scalar(
                select(FixedRuleAgenda.id)
                .where(FixedRuleAgenda.rule_id == rule_id)
                .limit(1)
            )
            if has_conditions is None:
                session.execute(delete(FixedRule).where(FixedRule.id == rule_id))
    session.execute(delete(Coverage).where(Coverage.agenda_id == agenda_id))
    session.execute(delete(AgendaRecurrence).where(AgendaRecurrence.agenda_id == agenda_id))
    session.execute(delete(Assignment).where(Assignment.agenda_id == agenda_id, Assignment.date >= today))
    session.execute(delete(Vacancy).where(Vacancy.agenda_id == agenda_id, Vacancy.date >= today))
    bump_revision(session)


def add_hospital(
    session: Session,
    catalog: HospitalCatalog,
    catalog_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    clean_name = (name or "").strip()
    if not catalog_id:
        if len(clean_name) < 2:
            raise DomainError("HOSPITAL_NAME_REQUIRED", "Escriu el nom del centre", field="name")
        duplicate = session.scalar(
            select(Hospital).where(func.lower(Hospital.name) == clean_name.lower())
        )
        if duplicate:
            raise DomainError("HOSPITAL_ALREADY_SELECTED", "Aquest centre ja està afegit")
        manual_id = f"manual_{uuid4().hex}"
        hospital = Hospital(
            id=uid(),
            catalog_id=manual_id,
            name=clean_name,
            address=None,
            location_known=False,
        )
        session.add(hospital)
        bump_revision(session)
        session.flush()
        return {
            "id": hospital.id,
            "catalogId": hospital.catalog_id,
            "name": hospital.name,
            "shortName": hospital.short_name,
            "address": "",
            "locationKnown": False,
        }
    details = catalog.details(catalog_id)
    if not details or catalog_id not in catalog.areas:
        raise DomainError("HOSPITAL_NOT_AVAILABLE", "Aquest hospital no té una àrea disponible", field="catalogId")
    existing = session.scalar(select(Hospital).where(Hospital.catalog_id == catalog_id))
    if existing:
        raise DomainError("HOSPITAL_ALREADY_SELECTED", "Aquest hospital ja està afegit")
    hospital = Hospital(id=uid(), catalog_id=catalog_id, location_known=True)
    session.add(hospital)
    bump_revision(session)
    session.flush()
    return {
        **{key: value for key, value in details.items() if key not in {"geometry", "id"}},
        "id": hospital.id,
        "catalogId": catalog_id,
        "shortName": hospital.short_name,
        "locationKnown": True,
    }


def update_hospital_short_name(
    session: Session,
    hospital_id: str,
    short_name: str | None,
) -> dict[str, str | None]:
    hospital = session.get(Hospital, hospital_id)
    if not hospital:
        raise DomainError("HOSPITAL_NOT_FOUND", "Hospital no trobat")
    hospital.short_name = (short_name or "").strip() or None
    bump_revision(session)
    session.flush()
    return {"id": hospital.id, "shortName": hospital.short_name}


def delete_calendar_range(session: Session, start: date, end: date) -> dict[str, int]:
    if end < start:
        raise DomainError(
            "INVALID_DATE_RANGE",
            "La data final no pot ser anterior a la data inicial",
            field="endDate",
        )
    assignments_result = session.execute(
        delete(Assignment).where(
            Assignment.date >= start,
            Assignment.date <= end,
        )
    )
    assignments = int(getattr(assignments_result, "rowcount", 0) or 0)
    vacancies_result = session.execute(
        delete(Vacancy).where(
            Vacancy.date >= start,
            Vacancy.date <= end,
        )
    )
    vacancies = int(getattr(vacancies_result, "rowcount", 0) or 0)
    if assignments or vacancies:
        bump_revision(session)
    return {
        "assignmentsDeleted": int(assignments or 0),
        "vacanciesDeleted": int(vacancies or 0),
    }


def remove_hospital(session: Session, hospital_id: str) -> None:
    hospital = session.get(Hospital, hospital_id)
    if not hospital:
        raise DomainError("HOSPITAL_NOT_FOUND", "Hospital no trobat")
    agenda = session.scalar(
        select(Agenda).where(Agenda.hospital_catalog_id == hospital.catalog_id, Agenda.archived_at.is_(None))
    )
    if agenda:
        raise DomainError(
            "HOSPITAL_IN_USE", "No es pot eliminar un hospital amb agendes actives", details={"agendaId": agenda.id}
        )
    session.delete(hospital)
    bump_revision(session)


def _validate_member_planifiable(
    session: Session,
    member_id: str,
    assignment_date: date,
) -> Member:
    member = session.get(Member, member_id)
    if not member or member.archived_at or not member.is_active:
        raise DomainError("MEMBER_NOT_PLANNABLE", "La persona no està activa", field="memberId")
    week_index = (assignment_date.isocalendar().week - 1) % max(member.work_pattern_weeks, 1)
    works = session.scalar(
        select(MemberAvailableDay.id).where(
            MemberAvailableDay.member_id == member_id,
            MemberAvailableDay.week_index == week_index,
            MemberAvailableDay.weekday == assignment_date.isoweekday(),
        )
    )
    profile_absent = session.scalar(
        select(Absence.id).where(
            Absence.member_id == member_id,
            Absence.start <= assignment_date,
            Absence.end >= assignment_date,
        )
    )
    holiday = session.get(Holiday, assignment_date)
    if not works or profile_absent or holiday:
        raise DomainError("MEMBER_NOT_PLANNABLE", "La persona no és planificable en aquesta data", field="date")
    return member


def _validate_clinical_assignment(
    session: Session,
    member_id: str,
    assignment_date: date,
    agenda_id: str,
    *,
    exclude_assignment_ids: set[str] | None = None,
    maximum_daily_load: int = 100,
) -> Agenda:
    excluded = exclude_assignment_ids or set()
    agenda = session.get(Agenda, agenda_id)
    capability = session.scalar(
        select(MemberCapability).where(
            MemberCapability.member_id == member_id,
            MemberCapability.agenda_id == agenda_id,
        )
    )
    if not agenda or agenda.archived_at or not capability:
        raise DomainError("ASSIGNMENT_NOT_ALLOWED", "La persona no pot fer aquesta agenda", field="agendaId")
    member = session.get(Member, member_id)
    if not member:
        raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="memberId")
    week_index = (assignment_date.isocalendar().week - 1) % max(member.work_pattern_weeks, 1)
    is_telework_day = session.scalar(
        select(MemberTeleDay.id).where(
            MemberTeleDay.member_id == member_id,
            MemberTeleDay.week_index == week_index,
            MemberTeleDay.weekday == assignment_date.isoweekday(),
        )
    )
    if is_telework_day and not agenda.telematic:
        raise DomainError(
            "TELEWORK_AGENDA_REQUIRED",
            "En un dia telemàtic només es pot assignar una agenda telemàtica",
            field="agendaId",
        )
    siblings = list(
        session.scalars(
            select(Assignment).where(
                Assignment.date == assignment_date,
                Assignment.member_id == member_id,
                Assignment.id.not_in(excluded),
            )
        )
    )
    sibling_agendas = [
        sibling_agenda
        for item in siblings
        if item.kind == "assigned"
        and item.agenda_id
        and (sibling_agenda := session.get(Agenda, item.agenda_id))
    ]
    if any(item.id == agenda_id for item in sibling_agendas):
        raise DomainError(
            "DUPLICATE_DAILY_AGENDA",
            "No es pot repetir la mateixa agenda el mateix dia",
            field="agendaId",
        )
    daily_load = agenda.load_percentage + sum(
        item.load_percentage
        for item in siblings
        if item.kind in {"assigned", "management"} or item.management
    )
    valid_loads = {value for value in (50, 100, 150, 200) if value <= maximum_daily_load}
    if daily_load not in valid_loads:
        raise DomainError(
            "INVALID_DAILY_LOAD",
            f"La càrrega diària de la persona no pot superar el {maximum_daily_load}%",
            field="agendaId",
            details={"loadPercentage": daily_load},
        )
    return agenda


def _clinical_day_rows(
    session: Session,
    member_id: str,
    assignment_date: date,
) -> list[Assignment]:
    return list(
        session.scalars(
            select(Assignment)
            .where(
                Assignment.member_id == member_id,
                Assignment.date == assignment_date,
                Assignment.kind == "assigned",
                Assignment.agenda_id.is_not(None),
            )
            .order_by(Assignment.id)
        )
    )


def _peonada_person_details(
    session: Session,
    member_id: str,
    assignment_date: date,
    *,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    member = session.get(Member, member_id)
    rows = _clinical_day_rows(session, member_id, assignment_date)
    day_rows = _unassigned_rows(session, member_id, assignment_date)
    reverse_aliases = {value: key for key, value in (aliases or {}).items()}
    total = sum(
        item.load_percentage
        for item in day_rows
        if item.kind != "no_assignment"
    )
    return {
        "memberId": member_id,
        "memberName": member.name if member else "—",
        "date": assignment_date.isoformat(),
        "totalLoadPercentage": total,
        "minimumPeonadaLoadPercentage": max(total - 100, 0),
        "assignments": [
            {
                "id": reverse_aliases.get(item.id, item.id),
                "agendaId": item.agenda_id,
                "loadPercentage": item.load_percentage,
                "peonada": item.peonada,
            }
            for item in rows
        ],
    }


def _apply_peonada_selections(
    session: Session,
    people: list[tuple[str, date]],
    selections: dict[str, list[str]] | None,
    *,
    aliases: dict[str, dict[str, str]] | None = None,
    reset_existing: bool = False,
) -> list[dict[str, Any]]:
    unique_people = list(dict.fromkeys(people))
    for member_id, assignment_date in unique_people:
        for item in _unassigned_rows(session, member_id, assignment_date):
            if item.kind == "management" or item.management:
                item.peonada = False
            elif reset_existing and item.kind == "assigned" and item.agenda_id:
                item.peonada = False
    details = [
        _peonada_person_details(
            session,
            member_id,
            assignment_date,
            aliases=(aliases or {}).get(member_id),
        )
        for member_id, assignment_date in unique_people
    ]
    for person in details:
        if person["totalLoadPercentage"] > 200:
            raise DomainError(
                "MAX_DAILY_LOAD_EXCEEDED",
                "Una persona no pot superar el 200% de càrrega diària",
                details={"people": details},
            )
    requires_review = any(
        person["totalLoadPercentage"] > 100
        or any(item["peonada"] for item in person["assignments"])
        for person in details
    )
    if requires_review and selections is None:
        raise DomainError(
            "PEONADA_REVIEW_REQUIRED",
            "Cal revisar quines assignacions són peonades",
            details={"people": details},
        )
    selections = selections or {}
    for person, (member_id, assignment_date) in zip(details, unique_people, strict=True):
        rows = _clinical_day_rows(session, member_id, assignment_date)
        alias_map = (aliases or {}).get(member_id, {})
        selected_tokens = set(selections.get(member_id, []))
        selected_ids = {alias_map.get(item, item) for item in selected_tokens}
        valid_ids = {item.id for item in rows}
        if selected_ids - valid_ids:
            raise DomainError(
                "INVALID_PEONADA_SELECTION",
                "La selecció de peonades no és vàlida",
                details={"people": details},
            )
        selected_load = sum(
            item.load_percentage for item in rows if item.id in selected_ids
        )
        total = int(person["totalLoadPercentage"])
        if total <= 100 and selected_ids:
            raise DomainError(
                "PEONADA_NOT_REQUIRED",
                "Amb una càrrega de fins al 100% no cal marcar cap peonada",
                details={"people": details},
            )
        if total > 100 and total - selected_load != 100:
            message = (
                "Cal marcar prou assignacions perquè la càrrega ordinària sigui del 100%"
                if total - selected_load > 100
                else "No es pot marcar tanta càrrega com a peonada: la càrrega ordinària ha de ser del 100%"
            )
            raise DomainError(
                "PEONADA_REQUIRED",
                message,
                details={"people": details},
            )
        for item in rows:
            item.peonada = item.id in selected_ids
            if requires_review:
                item.locked = True
                item.manually_modified = True
    return [
        _peonada_person_details(
            session,
            member_id,
            assignment_date,
            aliases=(aliases or {}).get(member_id),
        )
        for member_id, assignment_date in unique_people
    ]


def _fairness_context(session: Session) -> dict[str, Any]:
    members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.id)
        )
    )
    agendas = list(session.scalars(select(Agenda).where(Agenda.archived_at.is_(None)).order_by(Agenda.id)))
    loads = {agenda.id: agenda.load_percentage / 100 for agenda in agendas}
    counts = {member.id: {agenda.id: 0.0 for agenda in agendas} for member in members}
    for item in session.scalars(select(Assignment).where(Assignment.agenda_id.is_not(None))):
        if item.member_id in counts and item.agenda_id in loads:
            counts[item.member_id][item.agenda_id] += item.load_percentage / 100
    capabilities = {
        member.id: set(
            session.scalars(select(MemberCapability.agenda_id).where(MemberCapability.member_id == member.id))
        )
        for member in members
    }
    return {
        "memberIds": [member.id for member in members],
        "agendaIds": [agenda.id for agenda in agendas],
        "loads": loads,
        "counts": counts,
        "capabilities": capabilities,
    }


def _projected_fairness_score(
    context: dict[str, Any],
    changes: list[tuple[str, str | None, str | None]],
) -> tuple[int, int]:
    counts = {
        member_id: dict(agenda_counts)
        for member_id, agenda_counts in context["counts"].items()
    }
    loads: dict[str, float] = context["loads"]
    for member_id, old_agenda_id, new_agenda_id in changes:
        if member_id not in counts:
            continue
        if old_agenda_id in loads:
            counts[member_id][old_agenda_id] -= loads[old_agenda_id]
        if new_agenda_id in loads:
            counts[member_id][new_agenda_id] += loads[new_agenda_id]
    return operational_fairness_score(
        context["memberIds"],
        context["agendaIds"],
        counts,
        context["capabilities"],
    )


def _fairness_result(baseline: tuple[int, int], projected: tuple[int, int]) -> dict[str, Any]:
    worst_delta = baseline[0] - projected[0]
    total_delta = baseline[1] - projected[1]
    effect = "improves" if projected < baseline else "worsens" if projected > baseline else "neutral"
    return {
        "fairnessWorstDeltaBasisPoints": worst_delta,
        "fairnessDeltaBasisPoints": total_delta,
        "fairnessEffect": effect,
    }


def _validate_exchange(
    session: Session,
    source: Assignment,
    target: Assignment,
    *,
    allow_fixed_source: bool = False,
) -> tuple[Agenda, Agenda]:
    if target.date != source.date or target.member_id == source.member_id:
        raise DomainError("EXCHANGE_NOT_ALLOWED", "Aquest intercanvi ja no està disponible")
    if (
        source.kind != "assigned"
        or target.kind != "assigned"
        or not source.agenda_id
        or not target.agenda_id
        or source.management
        or target.management
        or source.agenda_id == target.agenda_id
    ):
        raise DomainError("EXCHANGE_NOT_ALLOWED", "Aquestes assignacions no es poden intercanviar")
    if target.fixed:
        raise DomainError(
            "EXCHANGE_NOT_ALLOWED",
            "Una assignació fixa només es pot canviar des de la persona que la té assignada",
        )
    if source.fixed and not allow_fixed_source:
        raise DomainError(
            "FIXED_ASSIGNMENT_CONFIRMATION_REQUIRED",
            "Cal confirmar el canvi d'una assignació fixa",
        )
    source_agenda = session.get(Agenda, source.agenda_id)
    target_agenda = session.get(Agenda, target.agenda_id)
    if not source_agenda or not target_agenda or source_agenda.load_percentage != target_agenda.load_percentage:
        raise DomainError("EXCHANGE_LOAD_MISMATCH", "Les agendes han de tenir la mateixa càrrega")
    _validate_clinical_assignment(
        session,
        source.member_id,
        source.date,
        target.agenda_id,
        exclude_assignment_ids={source.id},
        maximum_daily_load=200,
    )
    _validate_clinical_assignment(
        session,
        target.member_id,
        target.date,
        source.agenda_id,
        exclude_assignment_ids={target.id},
        maximum_daily_load=200,
    )
    return source_agenda, target_agenda


def _validate_vacancy_change(
    session: Session,
    source: Assignment,
    vacancy: Vacancy,
    *,
    allow_fixed_source: bool = False,
) -> tuple[Agenda, Agenda]:
    if vacancy.date != source.date:
        raise DomainError("EXCHANGE_NOT_ALLOWED", "Aquesta vacant ja no està disponible")
    if (
        source.kind != "assigned"
        or not source.agenda_id
        or source.management
        or source.deferred_origin_date
        or source.agenda_id == vacancy.agenda_id
    ):
        raise DomainError("EXCHANGE_NOT_ALLOWED", "Aquesta assignació no es pot canviar per la vacant")
    if source.fixed and not allow_fixed_source:
        raise DomainError(
            "FIXED_ASSIGNMENT_CONFIRMATION_REQUIRED",
            "Cal confirmar el canvi d'una assignació fixa",
        )
    source_agenda = session.get(Agenda, source.agenda_id)
    target_agenda = _validate_clinical_assignment(
        session,
        source.member_id,
        source.date,
        vacancy.agenda_id,
        exclude_assignment_ids={source.id},
        maximum_daily_load=200,
    )
    if not source_agenda:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    return source_agenda, target_agenda


def _validate_transfer(
    session: Session,
    source: Assignment,
    target_member_id: str,
    *,
    allow_fixed_source: bool = False,
) -> Agenda:
    if (
        source.kind != "assigned"
        or not source.agenda_id
        or source.management
        or source.member_id == target_member_id
    ):
        raise DomainError("TRANSFER_NOT_ALLOWED", "Aquesta assignació no es pot cedir")
    if len(_clinical_day_rows(session, source.member_id, source.date)) <= 1:
        raise DomainError(
            "TRANSFER_REQUIRES_MULTIPLE_ASSIGNMENTS",
            "Només es pot cedir una agenda si la persona en té més d'una aquest dia",
        )
    if source.fixed and not allow_fixed_source:
        raise DomainError(
            "FIXED_ASSIGNMENT_CONFIRMATION_REQUIRED",
            "Cal confirmar el canvi d'una assignació fixa",
        )
    _validate_member_planifiable(session, target_member_id, source.date)
    return _validate_clinical_assignment(
        session,
        target_member_id,
        source.date,
        source.agenda_id,
        maximum_daily_load=200,
    )


def exchange_options(
    session: Session,
    assignment_id: str,
    *,
    include_fixed: bool = False,
) -> dict[str, Any]:
    source = session.get(Assignment, assignment_id)
    if not source:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    if source.kind != "assigned" or not source.agenda_id or source.management:
        raise DomainError("EXCHANGE_NOT_ALLOWED", "Aquesta activitat no es pot intercanviar")
    if source.fixed and not include_fixed:
        raise DomainError(
            "FIXED_ASSIGNMENT_CONFIRMATION_REQUIRED",
            "Cal confirmar el canvi d'una assignació fixa",
        )
    context = _fairness_context(session)
    baseline = _projected_fairness_score(context, [])
    options: list[dict[str, Any]] = []
    targets = list(
        session.scalars(
            select(Assignment).where(
                Assignment.date == source.date,
                Assignment.member_id != source.member_id,
                Assignment.kind == "assigned",
                Assignment.agenda_id.is_not(None),
            )
        )
    )
    for target in targets:
        try:
            source_agenda, target_agenda = _validate_exchange(
                session,
                source,
                target,
                allow_fixed_source=include_fixed,
            )
        except DomainError:
            continue
        projected = _projected_fairness_score(
            context,
            [
                (source.member_id, source_agenda.id, target_agenda.id),
                (target.member_id, target_agenda.id, source_agenda.id),
            ],
        )
        target_member = session.get(Member, target.member_id)
        options.append(
            {
                "optionType": "assignment",
                "targetAssignmentId": target.id,
                "targetMemberId": target.member_id,
                "targetMemberName": target_member.name if target_member else "—",
                "targetAgendaId": target_agenda.id,
                **_fairness_result(baseline, projected),
            }
        )
    vacancies = list(
        session.scalars(
            select(Vacancy).where(Vacancy.date == source.date).order_by(Vacancy.id)
        )
    )
    for vacancy in vacancies:
        try:
            source_agenda, target_agenda = _validate_vacancy_change(
                session,
                source,
                vacancy,
                allow_fixed_source=include_fixed,
            )
        except DomainError:
            continue
        projected = _projected_fairness_score(
            context,
            [(source.member_id, source_agenda.id, target_agenda.id)],
        )
        options.append(
            {
                "optionType": "vacancy",
                "targetVacancyId": vacancy.id,
                "targetAgendaId": target_agenda.id,
                **_fairness_result(baseline, projected),
            }
        )
    options.sort(
        key=lambda item: (
            -int(item["fairnessWorstDeltaBasisPoints"]),
            -int(item["fairnessDeltaBasisPoints"]),
            str(item.get("targetMemberName", "Vacant")).casefold(),
            str(item["targetAgendaId"]),
        )
    )
    return {
        "assignmentId": source.id,
        "memberId": source.member_id,
        "agendaId": source.agenda_id,
        "date": source.date.isoformat(),
        "sourceFixed": source.fixed,
        "options": options,
    }


def exchange_assignments(
    session: Session,
    assignment_id: str,
    target_assignment_id: str | None = None,
    target_vacancy_id: int | None = None,
    *,
    confirm_fixed: bool = False,
    peonada_selections: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    source = session.get(Assignment, assignment_id)
    if not source:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    if bool(target_assignment_id) == bool(target_vacancy_id):
        raise DomainError(
            "EXCHANGE_TARGET_REQUIRED",
            "Cal seleccionar una assignació o una vacant",
        )
    if target_vacancy_id is not None:
        vacancy = session.get(Vacancy, target_vacancy_id)
        if not vacancy:
            raise DomainError("VACANCY_NOT_FOUND", "Vacant no trobada")
        source_agenda, target_agenda = _validate_vacancy_change(
            session,
            source,
            vacancy,
            allow_fixed_source=confirm_fixed,
        )
        was_extra = source.extra
        source.agenda_id = target_agenda.id
        source.load_percentage = target_agenda.load_percentage
        source.extra = False
        source.fixed = False
        source.locked = True
        source.manually_modified = True
        if not was_extra:
            session.add(
                Vacancy(
                    generation_job_id=source.generation_job_id,
                    date=source.date,
                    agenda_id=source_agenda.id,
                )
            )
        session.delete(vacancy)
        peonada = _apply_peonada_selections(
            session,
            [(source.member_id, source.date)],
            peonada_selections,
            reset_existing=True,
        )
        bump_revision(session)
        return {
            "source": {
                "id": source.id,
                "memberId": source.member_id,
                "type": source.agenda_id,
                "extra": False,
                "fixed": False,
                "locked": True,
                "peonada": source.peonada,
            },
            "vacancy": {
                "filledId": target_vacancy_id,
                "createdAgendaId": source_agenda.id if not was_extra else None,
            },
            "peonadaReview": peonada,
        }
    target = session.get(Assignment, target_assignment_id)
    if not target:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    source_agenda, target_agenda = _validate_exchange(
        session,
        source,
        target,
        allow_fixed_source=confirm_fixed,
    )
    source_extra, target_extra = source.extra, target.extra
    source_deferred_origin, target_deferred_origin = (
        source.deferred_origin_date,
        target.deferred_origin_date,
    )
    source.agenda_id = target_agenda.id
    target.agenda_id = source_agenda.id
    source.load_percentage = target_agenda.load_percentage
    target.load_percentage = source_agenda.load_percentage
    source.extra = target_extra
    target.extra = source_extra
    source.deferred_origin_date = target_deferred_origin
    target.deferred_origin_date = source_deferred_origin
    source.fixed = False
    target.fixed = False
    source.locked = True
    target.locked = True
    source.manually_modified = True
    target.manually_modified = True
    peonada = _apply_peonada_selections(
        session,
        [(source.member_id, source.date), (target.member_id, target.date)],
        peonada_selections,
        reset_existing=True,
    )
    bump_revision(session)
    return {
        "source": {
            "id": source.id,
            "memberId": source.member_id,
            "type": source.agenda_id,
            "extra": source.extra,
            "peonada": source.peonada,
            "fixed": False,
            "locked": True,
        },
        "target": {
            "id": target.id,
            "memberId": target.member_id,
            "type": target.agenda_id,
            "extra": target.extra,
            "peonada": target.peonada,
            "fixed": False,
            "locked": True,
        },
        "peonadaReview": peonada,
    }


def transfer_options(
    session: Session,
    assignment_id: str,
    *,
    include_fixed: bool = False,
) -> dict[str, Any]:
    source = session.get(Assignment, assignment_id)
    if not source:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    context = _fairness_context(session)
    baseline = _projected_fairness_score(context, [])
    options: list[dict[str, Any]] = []
    members = list(
        session.scalars(
            select(Member)
            .where(
                Member.id != source.member_id,
                Member.archived_at.is_(None),
                Member.is_active.is_(True),
            )
            .order_by(Member.name, Member.id)
        )
    )
    for member in members:
        try:
            source_agenda = _validate_transfer(
                session,
                source,
                member.id,
                allow_fixed_source=include_fixed,
            )
        except DomainError:
            continue
        rows = _clinical_day_rows(session, member.id, source.date)
        current_load = sum(item.load_percentage for item in rows)
        projected = _projected_fairness_score(
            context,
            [
                (source.member_id, source_agenda.id, None),
                (member.id, None, source_agenda.id),
            ],
        )
        options.append(
            {
                "targetMemberId": member.id,
                "targetMemberName": member.name,
                "currentLoadPercentage": current_load,
                "projectedLoadPercentage": current_load
                + source_agenda.load_percentage,
                "requiresPeonadaReview": (
                    current_load + source_agenda.load_percentage > 100
                ),
                **_fairness_result(baseline, projected),
            }
        )
    options.sort(
        key=lambda item: (
            -int(item["fairnessWorstDeltaBasisPoints"]),
            -int(item["fairnessDeltaBasisPoints"]),
            str(item["targetMemberName"]).casefold(),
        )
    )
    return {
        "assignmentId": source.id,
        "memberId": source.member_id,
        "agendaId": source.agenda_id,
        "date": source.date.isoformat(),
        "sourceFixed": source.fixed,
        "options": options,
    }


def transfer_assignment(
    session: Session,
    assignment_id: str,
    target_member_id: str,
    *,
    confirm_fixed: bool = False,
    peonada_selections: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    source = session.get(Assignment, assignment_id)
    if not source:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    source_member_id = source.member_id
    assignment_date = source.date
    _validate_transfer(
        session,
        source,
        target_member_id,
        allow_fixed_source=confirm_fixed,
    )
    no_assignment_rows = list(
        session.scalars(
            select(Assignment).where(
                Assignment.member_id == target_member_id,
                Assignment.date == assignment_date,
                Assignment.kind == "no_assignment",
            )
        )
    )
    for item in no_assignment_rows:
        session.delete(item)
    source.member_id = target_member_id
    source.fixed = False
    source.locked = True
    source.manually_modified = True
    peonada = _apply_peonada_selections(
        session,
        [
            (source_member_id, assignment_date),
            (target_member_id, assignment_date),
        ],
        peonada_selections,
        reset_existing=True,
    )
    bump_revision(session)
    return {
        "id": source.id,
        "date": source.date.isoformat(),
        "sourceMemberId": source_member_id,
        "targetMemberId": source.member_id,
        "type": source.agenda_id,
        "fixed": False,
        "locked": True,
        "peonada": source.peonada,
        "peonadaReview": peonada,
    }


def vacancy_assignment_options(
    session: Session,
    vacancy_id: int,
) -> dict[str, Any]:
    vacancy = session.get(Vacancy, vacancy_id)
    if not vacancy:
        raise DomainError("VACANCY_NOT_FOUND", "Vacant no trobada")
    agenda = session.get(Agenda, vacancy.agenda_id)
    if not agenda:
        raise DomainError("AGENDA_NOT_FOUND", "Agenda no trobada")
    context = _fairness_context(session)
    baseline = _projected_fairness_score(context, [])
    options: list[dict[str, Any]] = []
    members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.name, Member.id)
        )
    )
    for member in members:
        try:
            _validate_member_planifiable(session, member.id, vacancy.date)
            _validate_clinical_assignment(
                session,
                member.id,
                vacancy.date,
                agenda.id,
                maximum_daily_load=200,
            )
        except DomainError:
            continue
        rows = _clinical_day_rows(session, member.id, vacancy.date)
        current_load = sum(item.load_percentage for item in rows)
        projected = _projected_fairness_score(
            context,
            [(member.id, None, agenda.id)],
        )
        options.append(
            {
                "memberId": member.id,
                "memberName": member.name,
                "currentLoadPercentage": current_load,
                "projectedLoadPercentage": current_load + agenda.load_percentage,
                "requiresPeonadaReview": (
                    current_load + agenda.load_percentage > 100
                    or any(item.peonada for item in rows)
                ),
                **_fairness_result(baseline, projected),
            }
        )
    options.sort(
        key=lambda item: (
            -int(item["fairnessWorstDeltaBasisPoints"]),
            -int(item["fairnessDeltaBasisPoints"]),
            str(item["memberName"]).casefold(),
        )
    )
    return {
        "vacancyId": vacancy.id,
        "agendaId": vacancy.agenda_id,
        "date": vacancy.date.isoformat(),
        "options": options,
    }


def assign_vacancy(
    session: Session,
    vacancy_id: int,
    member_id: str,
    *,
    peonada_selections: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    vacancy = session.get(Vacancy, vacancy_id)
    if not vacancy:
        raise DomainError("VACANCY_NOT_FOUND", "Vacant no trobada")
    _validate_member_planifiable(session, member_id, vacancy.date)
    agenda = _validate_clinical_assignment(
        session,
        member_id,
        vacancy.date,
        vacancy.agenda_id,
        maximum_daily_load=200,
    )
    no_assignment_rows = list(
        session.scalars(
            select(Assignment).where(
                Assignment.member_id == member_id,
                Assignment.date == vacancy.date,
                Assignment.kind == "no_assignment",
            )
        )
    )
    for item in no_assignment_rows:
        session.delete(item)
    assignment = Assignment(
        id=uid(),
        generation_job_id=vacancy.generation_job_id,
        date=vacancy.date,
        member_id=member_id,
        agenda_id=agenda.id,
        kind="assigned",
        load_percentage=agenda.load_percentage,
        locked=True,
        fixed=False,
        extra=False,
        peonada=False,
        manually_modified=True,
        management=False,
    )
    session.add(assignment)
    session.delete(vacancy)
    peonada = _apply_peonada_selections(
        session,
        [(member_id, assignment.date)],
        peonada_selections,
        aliases={member_id: {"new": assignment.id}},
        reset_existing=True,
    )
    bump_revision(session)
    return {
        "id": assignment.id,
        "date": assignment.date.isoformat(),
        "memberId": assignment.member_id,
        "type": assignment.agenda_id,
        "locked": True,
        "extra": False,
        "peonada": assignment.peonada,
        "peonadaReview": peonada,
    }


def peonada_options(
    session: Session,
    member_id: str,
    assignment_date: date,
) -> dict[str, Any]:
    details = _peonada_person_details(session, member_id, assignment_date)
    if not details["assignments"]:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "No hi ha assignacions per revisar")
    return details


def update_peonadas(
    session: Session,
    member_id: str,
    assignment_date: date,
    assignment_ids: list[str],
) -> dict[str, Any]:
    if not _clinical_day_rows(session, member_id, assignment_date):
        raise DomainError("ASSIGNMENT_NOT_FOUND", "No hi ha assignacions per revisar")
    people = _apply_peonada_selections(
        session,
        [(member_id, assignment_date)],
        {member_id: assignment_ids},
    )
    bump_revision(session)
    return people[0]


def _unassigned_rows(
    session: Session,
    member_id: str,
    assignment_date: date,
) -> list[Assignment]:
    return list(
        session.scalars(
            select(Assignment).where(
                Assignment.member_id == member_id,
                Assignment.date == assignment_date,
            )
        )
    )


def extra_assignment_options(
    session: Session,
    member_id: str,
    assignment_date: date,
) -> dict[str, Any]:
    member = _validate_member_planifiable(session, member_id, assignment_date)
    rows = _unassigned_rows(session, member_id, assignment_date)
    no_assignment_rows = [item for item in rows if item.kind == "no_assignment"]
    current_load = sum(
        item.load_percentage
        for item in rows
        if item.kind != "no_assignment"
    )
    context = _fairness_context(session)
    baseline = _projected_fairness_score(context, [])
    options: list[dict[str, Any]] = []
    agenda_ids = list(
        session.scalars(
            select(MemberCapability.agenda_id)
            .join(Agenda, Agenda.id == MemberCapability.agenda_id)
            .where(
                MemberCapability.member_id == member_id,
                Agenda.archived_at.is_(None),
            )
            .order_by(Agenda.name, Agenda.id)
        )
    )
    excluded = {item.id for item in no_assignment_rows}
    for agenda_id in agenda_ids:
        try:
            agenda = _validate_clinical_assignment(
                session,
                member_id,
                assignment_date,
                agenda_id,
                exclude_assignment_ids=excluded,
                maximum_daily_load=200,
            )
        except DomainError:
            continue
        projected = _projected_fairness_score(context, [(member_id, None, agenda.id)])
        projected_load = current_load + agenda.load_percentage
        options.append(
            {
                "agendaId": agenda.id,
                "currentLoadPercentage": current_load,
                "projectedLoadPercentage": projected_load,
                "requiresPeonadaReview": projected_load > 100,
                **_fairness_result(baseline, projected),
            }
        )
    options.sort(
        key=lambda item: (
            -int(item["fairnessWorstDeltaBasisPoints"]),
            -int(item["fairnessDeltaBasisPoints"]),
            str(item["agendaId"]),
        )
    )
    return {
        "memberId": member.id,
        "memberName": member.name,
        "date": assignment_date.isoformat(),
        "options": options,
    }


def open_extra_assignment(
    session: Session,
    member_id: str,
    assignment_date: date,
    agenda_id: str,
    *,
    peonada_selections: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    _validate_member_planifiable(session, member_id, assignment_date)
    rows = _unassigned_rows(session, member_id, assignment_date)
    no_assignment_rows = [item for item in rows if item.kind == "no_assignment"]
    agenda = _validate_clinical_assignment(
        session,
        member_id,
        assignment_date,
        agenda_id,
        exclude_assignment_ids={item.id for item in no_assignment_rows},
        maximum_daily_load=200,
    )
    assignment = no_assignment_rows[0] if no_assignment_rows else Assignment(
        id=uid(),
        date=assignment_date,
        member_id=member_id,
    )
    for duplicate in no_assignment_rows[1:]:
        session.delete(duplicate)
    if not no_assignment_rows:
        session.add(assignment)
    assignment.agenda_id = agenda.id
    assignment.kind = "assigned"
    assignment.load_percentage = agenda.load_percentage
    assignment.locked = True
    assignment.fixed = False
    assignment.extra = True
    assignment.peonada = False
    assignment.manually_modified = True
    assignment.management = False
    peonada = _apply_peonada_selections(
        session,
        [(member_id, assignment_date)],
        peonada_selections,
        aliases={member_id: {"new": assignment.id}},
        reset_existing=True,
    )
    bump_revision(session)
    return {
        "id": assignment.id,
        "date": assignment.date.isoformat(),
        "memberId": assignment.member_id,
        "type": assignment.agenda_id,
        "locked": True,
        "extra": True,
        "peonada": assignment.peonada,
        "peonadaReview": peonada,
    }


def update_assignment(session: Session, assignment_id: str, agenda_id: str) -> dict[str, Any]:
    assignment = session.get(Assignment, assignment_id)
    if not assignment:
        raise DomainError("ASSIGNMENT_NOT_FOUND", "Assignació no trobada")
    siblings = list(
        session.scalars(
            select(Assignment).where(
                Assignment.date == assignment.date,
                Assignment.member_id == assignment.member_id,
                Assignment.id != assignment.id,
            )
        )
    )
    if agenda_id == "no_assignment":
        for sibling in siblings:
            session.delete(sibling)
        assignment.agenda_id = None
        assignment.kind = "no_assignment"
        assignment.load_percentage = 0
        assignment.locked = True
        assignment.fixed = False
        assignment.extra = False
        assignment.peonada = False
        assignment.deferred_origin_date = None
        assignment.manually_modified = True
        assignment.management = False
        bump_revision(session)
        return {
            "id": assignment.id,
            "date": assignment.date.isoformat(),
            "memberId": assignment.member_id,
            "type": "no_assignment",
            "locked": True,
        }
    if agenda_id == "management":
        member = session.get(Member, assignment.member_id)
        if not member or member.management_quota <= 0:
            raise DomainError(
                "ASSIGNMENT_NOT_ALLOWED",
                "La persona no té la gestió habilitada",
                field="type",
            )
        if siblings:
            raise DomainError(
                "INVALID_DAILY_LOAD",
                "La gestió necessita una jornada completament lliure",
                field="type",
            )
        month_start = assignment.date.replace(day=1)
        next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        existing = session.scalar(
            select(func.count())
            .select_from(Assignment)
            .where(
                Assignment.member_id == assignment.member_id,
                Assignment.kind == "management",
                Assignment.date >= month_start,
                Assignment.date < next_month,
                Assignment.id != assignment.id,
            )
        )
        if int(existing or 0) >= member.management_quota:
            raise DomainError(
                "MANAGEMENT_QUOTA_EXCEEDED",
                "La persona ja té assignats tots els dies de gestió del mes",
                field="type",
            )
        assignment.agenda_id = None
        assignment.kind = "management"
        assignment.load_percentage = 100
        assignment.locked = True
        assignment.fixed = False
        assignment.extra = False
        assignment.peonada = False
        assignment.deferred_origin_date = None
        assignment.manually_modified = True
        assignment.management = True
        bump_revision(session)
        return {
            "id": assignment.id,
            "date": assignment.date.isoformat(),
            "memberId": assignment.member_id,
            "type": "management",
            "management": True,
            "telematic": True,
            "locked": True,
        }
    agenda = session.get(Agenda, agenda_id)
    capability = session.scalar(
        select(MemberCapability).where(
            MemberCapability.member_id == assignment.member_id, MemberCapability.agenda_id == agenda_id
        )
    )
    if not agenda or agenda.archived_at or not capability:
        raise DomainError("ASSIGNMENT_NOT_ALLOWED", "La persona no pot fer aquesta agenda", field="type")
    member = session.get(Member, assignment.member_id)
    week_count = member.work_pattern_weeks if member else 1
    week_index = (assignment.date.isocalendar().week - 1) % week_count
    is_telework_day = session.scalar(
        select(MemberTeleDay.id).where(
            MemberTeleDay.member_id == assignment.member_id,
            MemberTeleDay.week_index == week_index,
            MemberTeleDay.weekday == assignment.date.isoweekday(),
        )
    )
    if is_telework_day and not agenda.telematic:
        raise DomainError(
            "TELEWORK_AGENDA_REQUIRED",
            "En un dia telemàtic només es pot assignar una agenda telemàtica",
            field="type",
        )
    sibling_agendas = [session.get(Agenda, item.agenda_id) for item in siblings if item.agenda_id]
    if any(item and item.id == agenda_id for item in sibling_agendas):
        raise DomainError("DUPLICATE_DAILY_AGENDA", "No es pot repetir la mateixa agenda el mateix dia", field="type")
    daily_load = agenda.load_percentage + sum(item.load_percentage for item in sibling_agendas if item)
    if daily_load not in {50, 100}:
        raise DomainError(
            "INVALID_DAILY_LOAD",
            "La càrrega diària de la persona ha de sumar el 50% o el 100%",
            field="type",
            details={"loadPercentage": daily_load},
        )
    assignment.agenda_id = agenda_id
    assignment.kind = "assigned"
    assignment.load_percentage = agenda.load_percentage
    assignment.locked = True
    assignment.fixed = False
    assignment.extra = False
    assignment.peonada = False
    assignment.deferred_origin_date = None
    assignment.manually_modified = True
    assignment.management = False
    bump_revision(session)
    return {
        "id": assignment.id,
        "date": assignment.date.isoformat(),
        "memberId": assignment.member_id,
        "type": agenda_id,
        "locked": True,
    }


def fairness(session: Session) -> dict[str, Any]:
    members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.name)
        )
    )
    agendas = list(session.scalars(select(Agenda).where(Agenda.archived_at.is_(None)).order_by(Agenda.name)))
    counts = {member.id: {agenda.id: 0.0 for agenda in agendas} for member in members}
    statement = select(Assignment).where(Assignment.agenda_id.is_not(None))
    for item in session.scalars(statement):
        if item.member_id in counts and item.agenda_id in counts[item.member_id]:
            counts[item.member_id][item.agenda_id] += item.load_percentage / 100
    management_counts = {
        member.id: int(
            session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(
                    Assignment.member_id == member.id,
                    Assignment.kind == "management",
                )
            )
            or 0
        )
        for member in members
    }
    tele_ids = {item.id for item in agendas if item.telematic}
    totals = {member.id: sum(counts[member.id].values()) for member in members}
    capabilities = {
        member.id: set(
            session.scalars(select(MemberCapability.agenda_id).where(MemberCapability.member_id == member.id))
        )
        for member in members
    }
    operational_distances = operational_person_distances(
        [member.id for member in members],
        [agenda.id for agenda in agendas],
        counts,
        capabilities,
    )
    means: dict[str, float | None] = {}
    for agenda in agendas:
        comparable = [
            member for member in members if totals[member.id] and agenda.id in capabilities[member.id]
        ]
        means[agenda.id] = (
            sum(counts[member.id][agenda.id] / totals[member.id] for member in comparable) / len(comparable)
            if comparable
            else None
        )
    people: list[dict[str, Any]] = []
    for member in members:
        total = totals[member.id]
        management = management_counts[member.id]
        activity_total = total + management
        tele = (
            sum(value for agenda_id, value in counts[member.id].items() if agenda_id in tele_ids)
            + management
        )
        percentages: dict[str, float | None] = {
            agenda.id: counts[member.id][agenda.id] / total if total else None for agenda in agendas
        }
        activity_counts = {**counts[member.id], "management": management}
        activity_percentages = {
            activity_id: value / activity_total if activity_total else None
            for activity_id, value in activity_counts.items()
        }
        deviations: dict[str, float | None] = {}
        for agenda in agendas:
            percentage = percentages[agenda.id]
            mean = means[agenda.id]
            deviations[agenda.id] = (
                percentage - mean
                if percentage is not None and mean is not None and agenda.id in capabilities[member.id]
                else None
            )
        people.append(
            {
                "memberId": member.id,
                "agendaCounts": counts[member.id],
                "agendaPercentages": percentages,
                "deviations": deviations,
                "averageDistanceBasisPoints": (
                    round(operational_distances[member.id] * 10_000)
                    if member.id in operational_distances
                    else None
                ),
                "total": total,
                "activityCounts": activity_counts,
                "activityPercentages": activity_percentages,
                "activityTotal": activity_total,
                "managementDays": management,
                "managementQuota": member.management_quota,
                "teleworkPercent": round(tele * 100 / activity_total) if activity_total else 0,
            }
        )
    active: list[int] = [int(item["teleworkPercent"]) for item in people if item["activityTotal"]]
    return {
        "agendaMeanBasisPoints": {
            agenda_id: round(value * 10_000) if value is not None else None for agenda_id, value in means.items()
        },
        "people": people,
        "teamTeleworkPercent": round(sum(active) / len(active)) if active else 0,
    }
