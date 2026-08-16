from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from typing import Any

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from pinendar.application.state import DomainError, bump_revision, uid
from pinendar.domain.fixed_rules import partition_fixed_rule_load
from pinendar.domain.scheduler import matches_recurrence
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
    GuardTransfer,
    Holiday,
    Member,
    MemberAvailableDay,
    MemberCapability,
    MemberTeleDay,
    Vacancy,
)


def _member(session: Session, member_id: str | None) -> Member | None:
    if member_id is None:
        return None
    member = session.get(Member, member_id)
    if not member or member.archived_at or not member.is_active:
        raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="memberId")
    return member


def _guard(
    session: Session,
    guard_id: str | None,
    guard_date: date,
) -> Guard | None:
    if guard_id is None:
        return None
    guard = session.get(Guard, guard_id)
    if not guard or guard.date != guard_date:
        raise DomainError(
            "GUARD_OPERATION_STALE",
            "La guàrdia ha canviat. Recarrega la vista abans de continuar",
        )
    return guard


def _validate_guard_specs(specs: list[dict[str, Any]]) -> None:
    assignments = [(item["date"], item["memberId"]) for item in specs]
    if len(assignments) != len(set(assignments)):
        raise DomainError(
            "DUPLICATE_GUARD_ASSIGNMENT",
            "Una persona només pot tenir una guàrdia en la mateixa data",
        )


def _assert_revision(session: Session, expected_revision: int | None) -> None:
    settings = session.get(AppSettings, 1)
    if expected_revision is not None and settings and settings.planning_revision != expected_revision:
        raise DomainError(
            "PLANNING_REVISION_CONFLICT",
            "El calendari ha canviat. Revisa de nou l’impacte",
            details={
                "expectedRevision": expected_revision,
                "currentRevision": settings.planning_revision,
            },
        )


def _operation(
    session: Session,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    def operation_date(key: str) -> date:
        value = payload[key]
        return value if isinstance(value, date) else date.fromisoformat(value)

    guards = list(
        session.scalars(
            select(Guard).order_by(Guard.date, Guard.id)
        )
    )
    specs = [
        {"id": item.id, "memberId": item.member_id, "date": item.date}
        for item in guards
    ]
    if kind == "cession":
        guard_date = operation_date("date")
        source = _guard(session, payload.get("guardId"), guard_date)
        target = _member(session, payload.get("toMemberId"))
        if source is None and target is None:
            raise DomainError(
                "INVALID_GUARD_CESSION",
                "L’origen i la destinació no poden ser exteriors",
            )
        if source and target and source.member_id == target.id:
            raise DomainError("INVALID_GUARD_CESSION", "La guàrdia ja correspon a aquesta persona")
        if source:
            specs = [item for item in specs if item["id"] != source.id]
        if target:
            target_id = source.id if source else uid()
            specs.append({"id": target_id, "memberId": target.id, "date": guard_date})
        legs = [
            {
                "date": guard_date,
                "fromMemberId": source.member_id if source else None,
                "toMemberId": target.id if target else None,
            }
        ]
        _validate_guard_specs(specs)
        return {"guards": specs, "legs": legs}

    first_date = operation_date("firstDate")
    first = _guard(session, payload.get("firstGuardId"), first_date)
    if first is None:
        raise DomainError(
            "INVALID_GUARD_EXCHANGE",
            "Cal seleccionar una guàrdia interna",
        )
    second_guard_id = payload.get("secondGuardId")
    if second_guard_id is None:
        specs = [item for item in specs if item["id"] != first.id]
        legs = [
            {
                "date": first_date,
                "fromMemberId": first.member_id,
                "toMemberId": None,
            }
        ]
        _validate_guard_specs(specs)
        return {"guards": specs, "legs": legs}

    if not payload.get("secondDate"):
        raise DomainError(
            "INVALID_GUARD_EXCHANGE",
            "Cal seleccionar la segona guàrdia",
        )
    second_date = operation_date("secondDate")
    if first_date == second_date:
        raise DomainError("INVALID_GUARD_EXCHANGE", "Cal seleccionar dues dates diferents")
    second = _guard(session, second_guard_id, second_date)
    assert second is not None
    if first and second and first.member_id == second.member_id:
        raise DomainError(
            "INVALID_GUARD_EXCHANGE",
            "Les dues guàrdies ja corresponen a la mateixa persona",
        )
    for item in specs:
        if item["id"] == first.id:
            item["memberId"] = second.member_id
        elif item["id"] == second.id:
            item["memberId"] = first.member_id
    legs = [
        {
            "date": first_date,
            "fromMemberId": first.member_id,
            "toMemberId": second.member_id,
        },
        {
            "date": second_date,
            "fromMemberId": second.member_id,
            "toMemberId": first.member_id,
        },
    ]
    _validate_guard_specs(specs)
    return {"guards": specs, "legs": legs}


def _works(session: Session, member: Member, value: date) -> bool:
    week_index = (value.isocalendar().week - 1) % max(member.work_pattern_weeks, 1)
    return bool(
        session.scalar(
            select(MemberAvailableDay.id).where(
                MemberAvailableDay.member_id == member.id,
                MemberAvailableDay.week_index == week_index,
                MemberAvailableDay.weekday == value.isoweekday(),
            )
        )
    )


def _telework(session: Session, member: Member, value: date) -> bool:
    week_index = (value.isocalendar().week - 1) % max(member.work_pattern_weeks, 1)
    return bool(
        session.scalar(
            select(MemberTeleDay.id).where(
                MemberTeleDay.member_id == member.id,
                MemberTeleDay.week_index == week_index,
                MemberTeleDay.weekday == value.isoweekday(),
            )
        )
    )


def _planifiable(
    session: Session,
    member: Member,
    value: date,
    guard_specs: list[dict[str, Any]],
) -> bool:
    if (
        member.archived_at
        or not member.is_active
        or value.isoweekday() > 5
        or session.get(Holiday, value)
        or not _works(session, member, value)
    ):
        return False
    profile_absent = session.scalar(
        select(Absence.id).where(
            Absence.member_id == member.id,
            Absence.start <= value,
            Absence.end >= value,
        )
    )
    if profile_absent:
        return False
    return not any(
        item["memberId"] == member.id and item["date"] + timedelta(days=1) == value
        for item in guard_specs
    )


def _demand(
    session: Session,
    agendas: dict[str, Agenda],
    value: date,
    holidays: set[str],
) -> dict[str, int]:
    coverage = {
        item.agenda_id: item.slots
        for item in session.scalars(select(Coverage).where(Coverage.weekday == value.isoweekday()))
    }
    recurrences: dict[str, list[AgendaRecurrence]] = {}
    for item in session.scalars(
        select(AgendaRecurrence).where(
            AgendaRecurrence.agenda_id.in_(agendas),
            AgendaRecurrence.weekday == value.isoweekday(),
        )
    ):
        recurrences.setdefault(item.agenda_id, []).append(item)
    return {
        agenda_id: int(coverage.get(agenda_id, 0))
        + sum(
            item.slots
            for item in recurrences.get(agenda_id, [])
            if matches_recurrence(
                value,
                {
                    "weekday": item.weekday,
                    "ordinal": item.ordinal,
                    "slots": item.slots,
                },
                holidays,
            )
        )
        for agenda_id in agendas
    }


def _solve_phase(
    model: cp_model.CpModel,
    expression: Any,
    hints: list[cp_model.IntVar],
) -> cp_model.CpSolver:
    model.minimize(expression)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    status = solver.solve(model)
    if status != cp_model.OPTIMAL:
        raise DomainError(
            "GUARD_REPAIR_FAILED",
            "No s’ha pogut demostrar una reparació segura del calendari",
        )
    optimum = int(solver.value(expression))
    model.add(expression == optimum)
    model.clear_objective()  # type: ignore[no-untyped-call]
    model.clear_hints()  # type: ignore[no-untyped-call]
    for variable in hints:
        model.add_hint(variable, int(solver.value(variable)))
    return solver


def _repair_date(
    session: Session,
    value: date,
    guard_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(Assignment).where(
                Assignment.date == value,
            )
        )
    )
    old_vacancies = list(
        session.scalars(
            select(Vacancy).where(
                Vacancy.date == value,
            )
        )
    )
    if value.isoweekday() > 5 or session.scalar(
        select(Holiday.date).where(Holiday.date == value)
    ):
        return {
            "date": value,
            "assignments": [],
            "vacancies": [],
            "oldAssignments": rows,
            "oldVacancies": old_vacancies,
        }

    members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.id)
        )
    )
    agendas = {
        item.id: item
        for item in session.scalars(
            select(Agenda).where(Agenda.archived_at.is_(None)).order_by(Agenda.id)
        )
    }
    holidays = {
        item.isoformat()
        for item in session.scalars(select(Holiday.date))
    }
    demand = _demand(session, agendas, value, holidays)
    capabilities: dict[str, set[str]] = {
        member.id: set(
            session.scalars(
                select(MemberCapability.agenda_id).where(
                    MemberCapability.member_id == member.id
                )
            )
        )
        for member in members
    }
    planifiable = {
        member.id: member
        for member in members
        if _planifiable(session, member, value, guard_specs)
    }
    old_by_key = {
        (row.member_id, row.agenda_id): row
        for row in rows
        if row.kind == "assigned"
        and row.agenda_id
        and not row.extra
        and not row.deferred_origin_date
    }
    old_no_assignment = {
        row.member_id: row for row in rows if row.kind == "no_assignment"
    }
    old_management = {
        row.member_id: row
        for row in rows
        if row.kind == "management" or row.management
    }
    old_extras = {
        row.id: row
        for row in rows
        if row.kind == "assigned"
        and row.agenda_id
        and (row.extra or row.deferred_origin_date)
    }

    fixed_peonada: set[tuple[str, str]] = set()
    reserved_coverage: Counter[str] = Counter()
    applicable_rules = list(
        session.scalars(
            select(FixedRule).where(FixedRule.weekday == value.isoweekday())
        )
    )
    rule_links: dict[str, list[FixedRuleAgenda]] = {
        rule.id: list(
            session.scalars(
                select(FixedRuleAgenda).where(FixedRuleAgenda.rule_id == rule.id)
            )
        )
        for rule in applicable_rules
    }
    for rule in applicable_rules:
        if rule.member_id not in planifiable or rule.required_mode != "all":
            continue
        links = rule_links[rule.id]
        required_ids = [
            link.agenda_id
            for link in links
            if link.effect == "required" and demand.get(link.agenda_id, 0) > 0
        ]
        partition = partition_fixed_rule_load(
            required_ids,
            {link.agenda_id for link in links if link.peonada},
            {agenda_id: agenda.load_percentage for agenda_id, agenda in agendas.items()},
        )
        if partition.total_load <= 100:
            continue
        ordinary_load = sum(agendas[item].load_percentage for item in partition.ordinary_ids)
        peonada_load = sum(agendas[item].load_percentage for item in partition.peonada_ids)
        if ordinary_load != 100 or peonada_load != partition.total_load - 100:
            raise DomainError(
                "FIXED_RULE_CONFLICT",
                "La regla fixa de peonada no té una distribució de càrrega vàlida",
            )
        for agenda_id in partition.peonada_ids:
            fixed_peonada.add((rule.member_id, agenda_id))
            reserved_coverage[agenda_id] += 1
    if any(reserved_coverage[agenda_id] > demand[agenda_id] for agenda_id in reserved_coverage):
        raise DomainError(
            "FIXED_RULE_CAPACITY",
            "No hi ha prou places per complir les peonades fixes",
        )

    model = cp_model.CpModel()
    ordinary: dict[tuple[str, str], cp_model.IntVar] = {}
    extra: dict[str, cp_model.IntVar] = {}
    management: dict[str, cp_model.IntVar] = {}
    partial: dict[str, cp_model.IntVar] = {}
    unassigned: dict[str, cp_model.IntVar] = {}
    all_variables: list[cp_model.IntVar] = []

    for member_id, member in planifiable.items():
        telework = _telework(session, member, value)
        candidates = [
            agenda_id
            for agenda_id, agenda in agendas.items()
            if demand[agenda_id] > 0
            and agenda_id in capabilities[member_id]
            and (member_id, agenda_id) not in fixed_peonada
            and (not telework or agenda.telematic)
        ]
        for agenda_id in candidates:
            variable = model.new_bool_var(f"x_{member_id}_{agenda_id}")
            ordinary[(member_id, agenda_id)] = variable
            all_variables.append(variable)
        for row_id, row in old_extras.items():
            agenda = agendas.get(row.agenda_id or "")
            if (
                row.member_id == member_id
                and agenda
                and agenda.id in capabilities[member_id]
                and (not telework or agenda.telematic)
            ):
                variable = model.new_bool_var(f"extra_{row_id}")
                extra[row_id] = variable
                all_variables.append(variable)
                if (member_id, agenda.id) in ordinary:
                    model.add(ordinary[(member_id, agenda.id)] + variable <= 1)
        if member_id in old_management and member.management_quota > 0:
            variable = model.new_bool_var(f"management_{member_id}")
            management[member_id] = variable
            all_variables.append(variable)
        partial[member_id] = model.new_bool_var(f"partial_{member_id}")
        unassigned[member_id] = model.new_bool_var(f"unassigned_{member_id}")
        all_variables.extend([partial[member_id], unassigned[member_id]])
        load: Any = sum(
            variable * (agendas[agenda_id].load_percentage // 50)
            for (person_id, agenda_id), variable in ordinary.items()
            if person_id == member_id
        )
        for row_id, variable in extra.items():
            row = old_extras[row_id]
            if row.member_id == member_id and row.agenda_id:
                load += variable * (agendas[row.agenda_id].load_percentage // 50)
        if member_id in management:
            load += 2 * management[member_id]
        model.add(partial[member_id] + unassigned[member_id] <= 1)
        model.add(load == 2 - partial[member_id] - 2 * unassigned[member_id])

    vacancy: dict[str, cp_model.IntVar] = {}
    uncovered: dict[str, cp_model.IntVar] = {}
    for agenda_id, amount in demand.items():
        if amount <= 0:
            continue
        vacancy[agenda_id] = model.new_int_var(0, amount, f"vacancy_{agenda_id}")
        uncovered[agenda_id] = model.new_bool_var(f"uncovered_{agenda_id}")
        all_variables.extend([vacancy[agenda_id], uncovered[agenda_id]])
        model.add(
            sum(
                variable
                for (member_id, candidate_id), variable in ordinary.items()
                if candidate_id == agenda_id
            )
            + vacancy[agenda_id]
            + reserved_coverage[agenda_id]
            == amount
        )
        model.add(vacancy[agenda_id] == amount).only_enforce_if(uncovered[agenda_id])
        model.add(vacancy[agenda_id] <= amount - 1).only_enforce_if(
            uncovered[agenda_id].Not()
        )

    fixed_keys: set[tuple[str, str]] = set()
    for rule in applicable_rules:
        if rule.member_id not in planifiable:
            continue
        links = rule_links[rule.id]
        required_variables = [
            ordinary[(rule.member_id, link.agenda_id)]
            for link in links
            if link.effect == "required"
            and demand.get(link.agenda_id, 0) > 0
            and (rule.member_id, link.agenda_id) not in fixed_peonada
            and (rule.member_id, link.agenda_id) in ordinary
        ]
        if rule.required_mode == "all":
            for variable in required_variables:
                model.add(variable == 1)
        elif required_variables:
            model.add(sum(required_variables) == 1)
        fixed_keys.update(
            (rule.member_id, link.agenda_id)
            for link in links
            if link.effect == "required"
            and demand.get(link.agenda_id, 0) > 0
            and (rule.member_id, link.agenda_id) not in fixed_peonada
            and (rule.member_id, link.agenda_id) in ordinary
        )
        for link in links:
            if (
                link.effect == "forbidden"
                and (rule.member_id, link.agenda_id) in ordinary
            ):
                model.add(ordinary[(rule.member_id, link.agenda_id)] == 0)

    phases: list[Any] = []
    for priority in (1,):
        variables = [
            variable
            for agenda_id, variable in vacancy.items()
            if agendas[agenda_id].priority == priority
        ]
        complete = [
            variable
            for agenda_id, variable in uncovered.items()
            if agendas[agenda_id].priority == priority
        ]
        if variables:
            phases.extend([sum(variables), sum(complete)])
    if management:
        phases.append(len(management) - sum(management.values()))
    for priority in (2, 3, 4):
        variables = [
            variable
            for agenda_id, variable in vacancy.items()
            if agendas[agenda_id].priority == priority
        ]
        complete = [
            variable
            for agenda_id, variable in uncovered.items()
            if agendas[agenda_id].priority == priority
        ]
        if variables:
            phases.extend([sum(variables), sum(complete)])
    if partial:
        phases.append(sum(partial.values()))
    if unassigned:
        phases.append(sum(unassigned.values()))

    changes: list[Any] = []
    for key, variable in ordinary.items():
        changes.append(1 - variable if key in old_by_key else variable)
    changes.extend(1 - variable for variable in extra.values())
    changes.extend(1 - variable for variable in management.values())
    if changes:
        phases.append(sum(changes))
    deterministic = [
        variable * (index + 1)
        for index, variable in enumerate(
            sorted(all_variables, key=lambda item: item.name)
        )
    ]
    if deterministic:
        phases.append(sum(deterministic))

    solver: cp_model.CpSolver | None = None
    for phase in phases or [0]:
        solver = _solve_phase(model, phase, all_variables)
    assert solver is not None

    output: list[dict[str, Any]] = []
    for member_id, agenda_id in fixed_peonada:
        previous = old_by_key.get((member_id, agenda_id))
        output.append(
            {
                "id": previous.id if previous else uid(),
                "memberId": member_id,
                "agendaId": agenda_id,
                "kind": "assigned",
                "locked": previous.locked if previous else True,
                "fixed": True,
                "extra": False,
                "peonada": True,
                "management": False,
            }
        )
    for (member_id, agenda_id), variable in ordinary.items():
        if solver.value(variable) != 1:
            continue
        previous = old_by_key.get((member_id, agenda_id))
        output.append(
            {
                "id": previous.id if previous else uid(),
                "memberId": member_id,
                "agendaId": agenda_id,
                "kind": "assigned",
                "locked": previous.locked if previous else True,
                "fixed": (previous.fixed if previous else False)
                or (member_id, agenda_id) in fixed_keys,
                "extra": False,
                "peonada": False,
                "management": False,
            }
        )
    for row_id, variable in extra.items():
        if solver.value(variable) == 1:
            row = old_extras[row_id]
            output.append(
                {
                    "id": row.id,
                    "memberId": row.member_id,
                    "agendaId": row.agenda_id,
                    "kind": "assigned",
                    "locked": row.locked,
                    "fixed": False,
                    "extra": row.extra,
                    "peonada": row.peonada,
                    "deferredOriginDate": (
                        row.deferred_origin_date.isoformat()
                        if row.deferred_origin_date
                        else None
                    ),
                    "management": False,
                }
            )
    for member_id, variable in management.items():
        if solver.value(variable) == 1:
            row = old_management[member_id]
            output.append(
                {
                    "id": row.id,
                    "memberId": member_id,
                    "agendaId": None,
                    "kind": "management",
                    "locked": row.locked,
                    "fixed": False,
                    "extra": False,
                    "peonada": False,
                    "management": True,
                }
            )
    for member_id, variable in unassigned.items():
        if solver.value(variable) == 1:
            previous = old_no_assignment.get(member_id)
            output.append(
                {
                    "id": previous.id if previous else uid(),
                    "memberId": member_id,
                    "agendaId": None,
                    "kind": "no_assignment",
                    "locked": previous.locked if previous else False,
                    "fixed": False,
                    "extra": False,
                    "peonada": False,
                    "management": False,
                }
            )
    vacancy_ids = [
        agenda_id
        for agenda_id, variable in vacancy.items()
        for _ in range(int(solver.value(variable)))
    ]
    return {
        "date": value,
        "assignments": output,
        "vacancies": vacancy_ids,
        "oldAssignments": rows,
        "oldVacancies": old_vacancies,
    }


def _assignment_key(item: Assignment | dict[str, Any]) -> tuple[str, str]:
    if isinstance(item, Assignment):
        activity = (
            item.agenda_id
            or ("management" if item.kind == "management" or item.management else "no_assignment")
        )
        return item.member_id, activity
    activity = item["agendaId"] or item["kind"]
    return item["memberId"], activity


def _relocate_management(
    session: Session,
    guard_specs: list[dict[str, Any]],
    repairs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    before: Counter[tuple[str, str]] = Counter()
    after: Counter[tuple[str, str]] = Counter()
    for repair in repairs:
        month = repair["date"].strftime("%Y-%m")
        before.update(
            (item.member_id, month)
            for item in repair["oldAssignments"]
            if item.kind == "management" or item.management
        )
        after.update(
            (item["memberId"], month)
            for item in repair["assignments"]
            if item["kind"] == "management"
        )
    relocations: list[dict[str, Any]] = []
    affected = {item["date"] for item in repairs}
    members = {item.id: item for item in session.scalars(select(Member))}
    for (member_id, month), count in (before - after).items():
        member = members.get(member_id)
        if not member or member.management_quota <= 0:
            continue
        candidates: list[tuple[int, date, Assignment]] = []
        for row in session.scalars(
            select(Assignment).where(
                Assignment.member_id == member_id,
                Assignment.kind == "no_assignment",
            )
        ):
            if (
                row.date in affected
                or row.date.strftime("%Y-%m") != month
                or not _planifiable(session, member, row.date, guard_specs)
            ):
                continue
            weekday_rank = 0 if row.date.isoweekday() == 5 else 1 if row.date.isoweekday() == 1 else 2
            candidates.append((weekday_rank, row.date, row))
        candidates.sort(key=lambda item: (item[0], item[1]))
        for _ in range(count):
            if not candidates:
                break
            _rank, candidate_date, row = candidates.pop(0)
            relocations.append(
                {
                    "date": candidate_date,
                    "assignment": {
                        "id": row.id,
                        "memberId": member_id,
                        "agendaId": None,
                        "kind": "management",
                        "locked": True,
                        "fixed": False,
                        "extra": False,
                        "management": True,
                    },
                    "oldAssignment": row,
                }
            )
    return relocations


def _impact(
    operation: dict[str, Any],
    repairs: list[dict[str, Any]],
    relocations: list[dict[str, Any]],
) -> dict[str, Any]:
    changed_dates: list[dict[str, Any]] = []
    for repair in repairs:
        before = Counter(_assignment_key(item) for item in repair["oldAssignments"])
        after = Counter(_assignment_key(item) for item in repair["assignments"])
        old_vacancies = Counter(item.agenda_id for item in repair["oldVacancies"])
        new_vacancies = Counter(repair["vacancies"])
        removed = list((before - after).elements())
        added = list((after - before).elements())
        if removed or added or old_vacancies != new_vacancies:
            changed_dates.append(
                {
                    "date": repair["date"].isoformat(),
                    "removed": [
                        {"memberId": member_id, "type": activity}
                        for member_id, activity in removed
                    ],
                    "added": [
                        {"memberId": member_id, "type": activity}
                        for member_id, activity in added
                    ],
                    "vacanciesBefore": list(old_vacancies.elements()),
                    "vacanciesAfter": list(new_vacancies.elements()),
                }
            )
    for relocation in relocations:
        changed_dates.append(
            {
                "date": relocation["date"].isoformat(),
                "removed": [
                    {
                        "memberId": relocation["assignment"]["memberId"],
                        "type": "no_assignment",
                    }
                ],
                "added": [
                    {
                        "memberId": relocation["assignment"]["memberId"],
                        "type": "management",
                    }
                ],
                "vacanciesBefore": [],
                "vacanciesAfter": [],
            }
        )
    return {
        "legs": [
            {
                **leg,
                "date": leg["date"].isoformat(),
            }
            for leg in operation["legs"]
        ],
        "changedDates": sorted(changed_dates, key=lambda item: item["date"]),
        "moves": sum(
            len(item["removed"]) + len(item["added"]) for item in changed_dates
        ),
        "vacanciesBefore": sum(
            len(item["vacanciesBefore"]) for item in changed_dates
        ),
        "vacanciesAfter": sum(
            len(item["vacanciesAfter"]) for item in changed_dates
        ),
    }


def _calculate(
    session: Session,
    kind: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    operation = _operation(session, kind, payload)
    affected_dates = sorted(
        {
            leg["date"] + timedelta(days=1)
            for leg in operation["legs"]
            if session.scalar(
                select(Assignment.id)
                .where(Assignment.date == leg["date"] + timedelta(days=1))
                .limit(1)
            )
            or session.scalar(
                select(Vacancy.id)
                .where(Vacancy.date == leg["date"] + timedelta(days=1))
                .limit(1)
            )
        }
    )
    repairs = [
        _repair_date(session, value, operation["guards"])
        for value in affected_dates
    ]
    relocations = _relocate_management(
        session, operation["guards"], repairs
    )
    return operation, repairs, relocations, _impact(operation, repairs, relocations)


def preview_guard_operation(
    session: Session,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _operation_data, _repairs, _relocations, impact = _calculate(
        session, kind, payload
    )
    settings = session.get(AppSettings, 1)
    return {
        "operation": kind,
        "planningRevision": settings.planning_revision if settings else 1,
        "impact": impact,
    }


def apply_guard_operation(
    session: Session,
    kind: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    _assert_revision(session, payload.get("expectedRevision"))
    operation, repairs, relocations, impact = _calculate(
        session, kind, payload
    )

    existing_guards = {
        item.id: item
        for item in session.scalars(select(Guard))
    }
    desired_guard_ids = {item["id"] for item in operation["guards"]}
    for guard_id, existing_guard in existing_guards.items():
        if guard_id not in desired_guard_ids:
            session.delete(existing_guard)
    for item in operation["guards"]:
        desired_guard = existing_guards.get(item["id"])
        if desired_guard is None:
            session.add(
                Guard(
                    id=item["id"],
                    member_id=item["memberId"],
                    date=item["date"],
                )
            )
        else:
            desired_guard.member_id = item["memberId"]
            desired_guard.date = item["date"]

    for repair in repairs:
        existing = {item.id: item for item in repair["oldAssignments"]}
        desired_ids = {item["id"] for item in repair["assignments"]}
        for row_id, row in existing.items():
            if row_id not in desired_ids:
                session.delete(row)
        for item in repair["assignments"]:
            row = existing.get(item["id"])
            if row is None:
                row = Assignment(
                    id=item["id"],
                    date=repair["date"],
                    member_id=item["memberId"],
                )
                session.add(row)
            row.member_id = item["memberId"]
            row.agenda_id = item["agendaId"]
            row.kind = item["kind"]
            agenda = session.get(Agenda, item["agendaId"]) if item["agendaId"] else None
            row.load_percentage = (
                agenda.load_percentage
                if agenda
                else 100
                if item["kind"] == "management"
                else 0
            )
            row.locked = item["locked"]
            row.fixed = item["fixed"]
            row.extra = item["extra"]
            row.peonada = bool(item.get("peonada"))
            row.deferred_origin_date = (
                date.fromisoformat(item["deferredOriginDate"])
                if item.get("deferredOriginDate")
                else None
            )
            row.management = item["management"]
        for vacancy in repair["oldVacancies"]:
            session.delete(vacancy)
        for agenda_id in repair["vacancies"]:
            session.add(
                Vacancy(
                    date=repair["date"],
                    agenda_id=agenda_id,
                )
            )

    for relocation in relocations:
        row = relocation["oldAssignment"]
        row.kind = "management"
        row.agenda_id = None
        row.load_percentage = 100
        row.locked = True
        row.fixed = False
        row.extra = False
        row.peonada = False
        row.management = True

    operation_id = uid()
    note = str(payload.get("note") or "").strip()
    for leg in operation["legs"]:
        session.add(
            GuardTransfer(
                id=uid(),
                operation_id=operation_id,
                operation_kind=kind,
                guard_date=leg["date"],
                from_member_id=leg["fromMemberId"],
                to_member_id=leg["toMemberId"],
                note=note,
                impact_json=json.dumps(impact, ensure_ascii=False),
            )
        )
    revision = bump_revision(session)
    return {
        "operationId": operation_id,
        "planningRevision": revision,
        "impact": impact,
    }
