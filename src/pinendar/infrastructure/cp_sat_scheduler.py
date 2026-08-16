from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.metadata import version
from random import Random
from statistics import pstdev
from time import monotonic
from typing import Any
from uuid import uuid4

from ortools.sat.python import cp_model

from pinendar.domain.scheduler import (
    ScheduleProblem,
    ScheduleResult,
    matches_recurrence,
    period_dates,
)
from pinendar.infrastructure.cp_sat_fairness import add_operational_fairness

MODEL_VERSION = "26"
ORTOOLS_VERSION = version("ortools")


@dataclass(frozen=True)
class _Phase:
    name: str
    expression: Any
    requires_optimum: bool


def _phase_time_weight(phase: _Phase, final_phase_count: int) -> float:
    if phase.name == "guard-onsite-days":
        return 10
    if phase.name == "automatic-deferred-telematic-coverage":
        return 12
    if phase.name == "telematic-percentage-range":
        return 15
    if phase.name == "telematic-percentage-dispersion":
        return 10
    if phase.name == "worst-historical-distance":
        return 60
    if phase.name == "total-historical-distance":
        return 30
    if phase.name == "consecutive-clinical-agendas":
        return 9
    if phase.requires_optimum:
        return 0
    return 1 / max(final_phase_count, 1)


def _phase_time_budget(phases: list[_Phase], phase_index: int, remaining: float) -> float:
    phase = phases[phase_index]
    if phase.requires_optimum:
        return remaining
    primary_names = {
        "guard-onsite-days",
        "automatic-deferred-telematic-coverage",
        "telematic-percentage-range",
        "telematic-percentage-dispersion",
        "worst-historical-distance",
        "total-historical-distance",
        "consecutive-clinical-agendas",
    }
    final_phase_count = sum(1 for item in phases if not item.requires_optimum and item.name not in primary_names)
    remaining_weights = sum(_phase_time_weight(item, final_phase_count) for item in phases[phase_index:])
    return min(
        remaining,
        max(
            0.05,
            remaining * _phase_time_weight(phase, final_phase_count) / remaining_weights,
        ),
    )


def _polishing_reserve(time_limit: float) -> float:
    return min(max(time_limit * 0.05, 0.05), time_limit * 0.1)


def _failure(
    code: str,
    message: str,
    *,
    outcome: str = "infeasible",
    details: dict[str, Any] | None = None,
    diagnostics: list[str] | None = None,
) -> ScheduleResult:
    return ScheduleResult(
        outcome=outcome,
        assignments=[],
        vacancies=[],
        metrics={"optimal": False, "ortoolsVersion": ORTOOLS_VERSION, "modelVersion": MODEL_VERSION},
        diagnostics=diagnostics or [message],
        engine="cp-sat",
        engine_version=MODEL_VERSION,
        error={"code": code, "message": message, "field": None, "details": details or {}},
    )


def _planning_dates(problem: ScheduleProblem) -> list[date]:
    holidays = set(problem.holidays)
    return [
        value
        for value in period_dates(
            problem.start_month,
            problem.end_month,
            problem.start_date,
            problem.end_date,
        )
        if value.isoweekday() <= 5 and value.isoformat() not in holidays
    ]


def _management_weekly_cap(quota: int, month: str) -> int:
    calendar_weeks = len({value.isocalendar()[:2] for value in period_dates(month, month)})
    return max(1, (quota + calendar_weeks - 1) // calendar_weeks)


def _member_absences(member: dict[str, Any], problem: ScheduleProblem) -> list[dict[str, Any]]:
    return [
        *member.get("vacations", member.get("absences", [])),
        *(item for item in problem.conditions.get("absences", []) if item.get("memberId") == member.get("id")),
    ]


def _is_planifiable(member: dict[str, Any], value: date, problem: ScheduleProblem) -> bool:
    if not _is_present(member, value, problem):
        return False
    return _works_on_date(member, value)


def _works_on_date(member: dict[str, Any], value: date) -> bool:
    pattern = member.get("workPattern") or {}
    weeks = pattern.get("weeks") or []
    if not weeks:
        return value.isoweekday() in member.get("availableDays", [])
    week_index = (value.isocalendar().week - 1) % len(weeks)
    week = weeks[week_index]
    working_days = week.get("workingDays", []) if isinstance(week, dict) else week
    return value.isoweekday() in working_days


def _is_telework_day(member: dict[str, Any], value: date) -> bool:
    pattern = member.get("workPattern") or {}
    weeks = pattern.get("weeks") or []
    if not weeks:
        return value.isoweekday() in member.get("teleDays", [])
    week_index = (value.isocalendar().week - 1) % len(weeks)
    week = weeks[week_index]
    tele_days = week.get("teleDays", []) if isinstance(week, dict) else []
    return value.isoweekday() in tele_days


def _guard_keys(problem: ScheduleProblem) -> set[tuple[str, date]]:
    return {
        (str(item["memberId"]), date.fromisoformat(str(item["date"])))
        for item in [*problem.guards, *problem.conditions.get("guards", [])]
    }


def _is_present(member: dict[str, Any], value: date, problem: ScheduleProblem) -> bool:
    if not member.get("active", True):
        return False
    key = value.isoformat()
    if any(item["start"] <= key <= item["end"] for item in _member_absences(member, problem)):
        return False
    guards = [*problem.guards, *problem.conditions.get("guards", [])]
    return not any(
        item.get("memberId") == member.get("id") and date.fromisoformat(item["date"]) + timedelta(days=1) == value
        for item in guards
    )


def _daily_demand(problem: ScheduleProblem, planning_dates: list[date]) -> dict[tuple[date, str], int]:
    holidays = set(problem.holidays)
    demand: dict[tuple[date, str], int] = {}
    for value in planning_dates:
        coverage = problem.coverage.get(str(value.isoweekday()), {})
        for agenda in problem.agendas:
            agenda_id = agenda["id"]
            amount = int(coverage.get(agenda_id, 0))
            amount += sum(
                int(recurrence.get("slots", 1))
                for recurrence in agenda.get("recurrences", [])
                if matches_recurrence(value, recurrence, holidays)
            )
            demand[(value, agenda_id)] = amount
    return demand


class CpSatScheduler:
    def solve(self, problem: ScheduleProblem) -> ScheduleResult:
        started = monotonic()
        if problem.schema_version not in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
            return _failure(
                "UNSUPPORTED_SNAPSHOT_VERSION",
                "La versió de les dades de planificació no és compatible",
                outcome="model_invalid",
                details={"schemaVersion": problem.schema_version},
            )

        agendas = {item["id"]: item for item in problem.agendas}
        members = {item["id"]: item for item in problem.team}
        invalid_loads = [
            {"agendaId": agenda_id, "loadPercentage": agenda.get("loadPercentage")}
            for agenda_id, agenda in agendas.items()
            if int(agenda.get("loadPercentage", 100)) not in {50, 100}
        ]
        if invalid_loads:
            return _failure(
                "INVALID_AGENDA_LOAD",
                "La càrrega de les agendes ha de ser del 50% o del 100%",
                outcome="model_invalid",
                details={"agendas": invalid_loads},
            )
        invalid_management_quotas = [
            {"memberId": member_id, "managementQuota": member.get("managementQuota")}
            for member_id, member in members.items()
            if not 0 <= int(member.get("managementQuota", 0)) <= 5
        ]
        if invalid_management_quotas:
            return _failure(
                "INVALID_MANAGEMENT_QUOTA",
                "Els dies de gestió han d’estar entre 0 i 5",
                outcome="model_invalid",
                details={"members": invalid_management_quotas},
            )
        agenda_load = {agenda_id: int(agenda.get("loadPercentage", 100)) for agenda_id, agenda in agendas.items()}
        agenda_load_units = {agenda_id: load // 50 for agenda_id, load in agenda_load.items()}
        planning_dates = _planning_dates(problem)
        demand = _daily_demand(problem, planning_dates)
        invalid_demand = [
            {"date": value.isoformat(), "agendaId": agenda_id, "slots": amount}
            for (value, agenda_id), amount in demand.items()
            if amount < 0
        ]
        if invalid_demand:
            return _failure(
                "INVALID_DEMAND",
                "La demanda no pot contenir valors negatius",
                outcome="model_invalid",
                details={"demand": invalid_demand},
            )

        planifiable: dict[date, list[str]] = {
            value: [member_id for member_id, member in members.items() if _is_planifiable(member, value, problem)]
            for value in planning_dates
        }

        model = cp_model.CpModel()
        assignments: dict[tuple[str, date, str], cp_model.IntVar] = {}
        management_assignments: dict[tuple[str, date], cp_model.IntVar] = {}
        unassigned: dict[tuple[str, date], cp_model.IntVar] = {}
        partial_days: dict[tuple[str, date], cp_model.IntVar] = {}
        daily_load_units: dict[tuple[str, date], Any] = {}
        base_daily_load_units: dict[tuple[str, date], Any] = {}
        vacancies: dict[tuple[date, str], cp_model.IntVar] = {}
        fixed_assignments: set[tuple[str, date, str]] = set()
        member_order = {member_id: index for index, member_id in enumerate(members)}
        agenda_order = {agenda_id: index for index, agenda_id in enumerate(agendas)}
        date_order = {value: index for index, value in enumerate(planning_dates)}
        config = problem.solver_config
        optimization_mode = str(config.get("optimizationMode", "fairness"))
        if optimization_mode != "fairness":
            return _failure(
                "INVALID_OPTIMIZATION_MODE",
                "El mode d’optimització no és vàlid",
                outcome="model_invalid",
                details={"optimizationMode": optimization_mode},
            )
        random_seed = int(config.get("randomSeed", 1))
        randomizer = Random(random_seed)
        locked_by_key = {
            (item["memberId"], date.fromisoformat(item["date"]), item["type"]): item
            for item in problem.locked_assignments
        }
        locked_types_by_day: dict[tuple[str, date], set[str]] = defaultdict(set)
        for member_id, value, event_type in locked_by_key:
            locked_types_by_day[(member_id, value)].add(event_type)
        preserved_deferred = Counter(
            (date.fromisoformat(item["deferredOriginDate"]), item["type"])
            for item in problem.locked_assignments
            if item.get("deferredOriginDate") and item.get("type") not in {"management", "no_assignment"}
        )
        guard_keys = _guard_keys(problem)

        for value, member_ids in planifiable.items():
            for member_id in member_ids:
                member = members[member_id]
                allowed = set(member.get("allowedTypes", []))
                candidates = [
                    agenda_id
                    for agenda_id in agendas
                    if agenda_id in allowed
                    and (
                        demand[(value, agenda_id)] > 0
                        or agenda_id in locked_types_by_day.get((member_id, value), set())
                    )
                    and (
                        not _is_telework_day(member, value)
                        or (member_id, value) in guard_keys
                        or bool(agendas[agenda_id].get("telematic", False))
                    )
                ]
                variables: list[cp_model.IntVar] = []
                for agenda_id in candidates:
                    variable = model.new_bool_var(
                        f"x_p{member_order[member_id]}_d{date_order[value]}_a{agenda_order[agenda_id]}"
                    )
                    assignments[(member_id, value, agenda_id)] = variable
                    variables.append(variable)
                management = None
                if int(member.get("managementQuota", 0)) > 0:
                    management = model.new_bool_var(f"management_p{member_order[member_id]}_d{date_order[value]}")
                    management_assignments[(member_id, value)] = management
                no_assignment = model.new_bool_var(f"unassigned_p{member_order[member_id]}_d{date_order[value]}")
                unassigned[(member_id, value)] = no_assignment
                partial_day = model.new_bool_var(f"partial_p{member_order[member_id]}_d{date_order[value]}")
                partial_days[(member_id, value)] = partial_day
                assigned_units = sum(
                    assignments[(member_id, value, agenda_id)] * agenda_load_units[agenda_id]
                    for agenda_id in candidates
                )
                daily_units = assigned_units + (2 * management if management is not None else 0)
                base_daily_load_units[(member_id, value)] = daily_units
                daily_load_units[(member_id, value)] = daily_units
                model.add(no_assignment + partial_day <= 1)

        for (member_id, value, event_type), item in locked_by_key.items():
            if value not in planning_dates or member_id not in planifiable.get(value, []):
                return _failure(
                    "LOCKED_ASSIGNMENT_CONFLICT",
                    "Una assignació manual ja no és compatible amb la disponibilitat",
                    details={"id": item.get("id"), "memberId": member_id, "date": value.isoformat()},
                )
            locked_variable: cp_model.IntVar | None
            if event_type == "no_assignment":
                locked_variable = unassigned.get((member_id, value))
            elif event_type == "management":
                locked_variable = management_assignments.get((member_id, value))
            else:
                locked_variable = assignments.get((member_id, value, event_type))
            if locked_variable is None:
                return _failure(
                    "LOCKED_ASSIGNMENT_CONFLICT",
                    "Una assignació manual ja no compleix les regles actuals",
                    details={
                        "id": item.get("id"),
                        "memberId": member_id,
                        "date": value.isoformat(),
                        "type": event_type,
                    },
                )
            model.add(locked_variable == 1)

        for value in planning_dates:
            for agenda_id in agendas:
                amount = demand[(value, agenda_id)]
                variable = model.new_int_var(0, amount, f"vac_d{date_order[value]}_a{agenda_order[agenda_id]}")
                vacancies[(value, agenda_id)] = variable
                covered = [
                    assignment
                    for (member_id, assignment_date, assignment_agenda), assignment in assignments.items()
                    if assignment_date == value
                    and assignment_agenda == agenda_id
                    and not locked_by_key.get((member_id, assignment_date, assignment_agenda), {}).get("extra")
                    and not locked_by_key.get((member_id, assignment_date, assignment_agenda), {}).get(
                        "deferredOriginDate"
                    )
                ]
                model.add(sum(covered) + variable + preserved_deferred[(value, agenda_id)] == amount)

        legacy_rule_groups: dict[tuple[int, str], list[str]] = defaultdict(list)
        personal_rules: list[tuple[str, dict[str, Any]]] = []
        for member_id, member in members.items():
            weekdays: set[int] = set()
            for rule in member.get("fixedRules", []):
                weekday = int(rule["weekday"])
                if weekday in weekdays:
                    return _failure(
                        "FIXED_RULE_CONFLICT",
                        "Una persona té més d’una regla fixa aplicable el mateix dia",
                        details={"memberId": member_id, "weekday": weekday},
                    )
                weekdays.add(weekday)
                if "requiredAgendaIds" in rule or "forbiddenAgendaIds" in rule:
                    personal_rules.append((member_id, rule))
                    continue
                agenda_id = rule["type"]
                if agenda_id not in agendas or agenda_id not in member.get("allowedTypes", []):
                    return _failure(
                        "FIXED_RULE_CONFLICT",
                        "Una regla fixa utilitza una agenda no habilitada",
                        details={"memberId": member_id, "agendaId": agenda_id},
                    )
                legacy_rule_groups[(weekday, agenda_id)].append(member_id)

        shared_rule_tiebreak: list[Any] = []
        for value, member_ids in planifiable.items():
            planifiable_ids = set(member_ids)
            for (weekday, agenda_id), configured_members in legacy_rule_groups.items():
                if weekday != value.isoweekday():
                    continue
                candidates = [member_id for member_id in configured_members if member_id in planifiable_ids]
                required = min(demand[(value, agenda_id)], len(candidates))
                if required <= 0:
                    continue
                fixed_variables = []
                for member_id in candidates:
                    fixed_variable = assignments.get((member_id, value, agenda_id))
                    if fixed_variable is None:
                        return _failure(
                            "FIXED_RULE_CONFLICT",
                            "Una regla fixa no disposa d’una assignació vàlida",
                            details={"date": value.isoformat(), "memberId": member_id, "agendaId": agenda_id},
                        )
                    fixed_variables.append(fixed_variable)
                    fixed_assignments.add((member_id, value, agenda_id))
                    if len(candidates) > required:
                        shared_rule_tiebreak.append(fixed_variable * randomizer.randint(1, 1_000_000))
                model.add(sum(fixed_variables) == required)

        for member_id, rule in personal_rules:
            weekday = int(rule["weekday"])
            required_mode = rule.get("requiredMode", "all")
            required_ids = list(dict.fromkeys(rule.get("requiredAgendaIds", [])))
            forbidden_ids = list(dict.fromkeys(rule.get("forbiddenAgendaIds", [])))
            referenced_ids = set(required_ids) | set(forbidden_ids)
            if (
                required_mode not in {"all", "one"}
                or not referenced_ids
                or set(required_ids) & set(forbidden_ids)
                or not referenced_ids.issubset(agendas)
                or not referenced_ids.issubset(set(members[member_id].get("allowedTypes", [])))
            ):
                return _failure(
                    "FIXED_RULE_CONFLICT",
                    "Una regla fixa conté condicions no vàlides",
                    details={"memberId": member_id, "weekday": weekday},
                )
            for value in planning_dates:
                if value.isoweekday() != weekday or member_id not in planifiable.get(value, []):
                    continue
                active_required = [agenda_id for agenda_id in required_ids if demand.get((value, agenda_id), 0) > 0]
                required_variables = [
                    assignments[(member_id, value, agenda_id)]
                    for agenda_id in active_required
                    if (member_id, value, agenda_id) in assignments
                ]
                if required_mode == "all" and len(required_variables) != len(active_required):
                    return _failure(
                        "FIXED_RULE_CONFLICT",
                        "Una agenda obligatòria no és compatible amb la persona",
                        details={
                            "memberId": member_id,
                            "date": value.isoformat(),
                        },
                    )
                if required_mode == "all":
                    for agenda_id, variable in zip(active_required, required_variables, strict=True):
                        model.add(variable == 1)
                        fixed_assignments.add((member_id, value, agenda_id))
                elif required_variables:
                    model.add(sum(required_variables) == 1)
                    fixed_assignments.update(
                        (member_id, value, agenda_id)
                        for agenda_id in active_required
                        if (member_id, value, agenda_id) in assignments
                    )
                elif active_required:
                    return _failure(
                        "FIXED_RULE_CONFLICT",
                        "Cap alternativa obligatòria és compatible amb la persona",
                        details={
                            "memberId": member_id,
                            "date": value.isoformat(),
                        },
                    )
                for agenda_id in forbidden_ids:
                    forbidden_variable = assignments.get((member_id, value, agenda_id))
                    if forbidden_variable is not None:
                        model.add(forbidden_variable == 0)

        for (weekday, agenda_id), configured_members in legacy_rule_groups.items():
            recurring_weekdays = {
                int(recurrence["weekday"]) for recurrence in agendas[agenda_id].get("recurrences", [])
            }
            if (
                configured_members
                and int(problem.coverage.get(str(weekday), {}).get(agenda_id, 0)) <= 0
                and weekday not in recurring_weekdays
            ):
                return _failure(
                    "FIXED_RULE_CAPACITY",
                    "Una regla fixa no disposa de demanda",
                    details={
                        "weekday": weekday,
                        "agendaId": agenda_id,
                    },
                )

        # A deferred assignment consumes free capacity on a later working day.
        # It never moves an existing assignment: it only uses a still-uncovered
        # telematic vacancy and a member/date that can accept the agenda.
        deferred_assignments: dict[tuple[date, str, date, str], cp_model.IntVar] = {}
        deferred_by_source: dict[tuple[date, str], list[cp_model.IntVar]] = defaultdict(list)
        deferred_by_target: dict[tuple[str, date], list[tuple[cp_model.IntVar, str]]] = defaultdict(list)
        deferred_by_target_agenda: dict[tuple[str, date, str], list[cp_model.IntVar]] = defaultdict(list)
        for (origin, agenda_id), _vacancy in vacancies.items():
            agenda = agendas[agenda_id]
            if not bool(agenda.get("telematic", False)) or demand[(origin, agenda_id)] <= 0:
                continue
            for target in planning_dates:
                if target <= origin or target > origin + timedelta(days=6):
                    continue
                # A deferred slot is only a spare telematic slot on a day
                # without that same agenda in the normal demand. This avoids
                # displacing an ordinary assignment to manufacture a deferment.
                if demand[(target, agenda_id)] > 0:
                    continue
                for member_id in planifiable.get(target, []):
                    if agenda_id not in members[member_id].get("allowedTypes", []):
                        continue
                    target_locked = [
                        item
                        for (locked_member, locked_date, _locked_type), item in locked_by_key.items()
                        if locked_member == member_id and locked_date == target
                    ]
                    if any(
                        item.get("type") in {"no_assignment", "management"}
                        or item.get("deferredOriginDate")
                        or item.get("extra")
                        or item.get("manuallyModified")
                        for item in target_locked
                    ):
                        continue
                    deferred = model.new_bool_var(
                        "deferred_"
                        f"o{date_order[origin]}_a{agenda_order[agenda_id]}"
                        f"_d{date_order[target]}_p{member_order[member_id]}"
                    )
                    key = (origin, agenda_id, target, member_id)
                    deferred_assignments[key] = deferred
                    deferred_by_source[(origin, agenda_id)].append(deferred)
                    deferred_by_target[(member_id, target)].append((deferred, agenda_id))
                    deferred_by_target_agenda[(member_id, target, agenda_id)].append(deferred)

        for source, source_variables in deferred_by_source.items():
            model.add(sum(source_variables) <= vacancies[source])

        for target_day_key, target_variables in deferred_by_target.items():
            member_id, target = target_day_key
            deferred_load = sum(
                variable * agenda_load_units[agenda_id]
                for variable, agenda_id in target_variables
            )
            total_load = base_daily_load_units[target_day_key] + deferred_load
            daily_load_units[target_day_key] = total_load
            model.add(total_load == 2 - (2 * unassigned[target_day_key]) - partial_days[target_day_key])
        for base_key, base_load in base_daily_load_units.items():
            if base_key not in deferred_by_target:
                model.add(base_load == 2 - (2 * unassigned[base_key]) - partial_days[base_key])

        for target_agenda_key, target_agenda_variables in deferred_by_target_agenda.items():
            ordinary_assignment = assignments.get(target_agenda_key)
            if ordinary_assignment is not None:
                model.add(ordinary_assignment + sum(target_agenda_variables) <= 1)

        automatic_deferred_phase = (
            _Phase(
                "automatic-deferred-telematic-coverage",
                sum(
                    vacancy - sum(source_variables)
                    for source, source_variables in deferred_by_source.items()
                    for vacancy in [vacancies[source]]
                ),
                False,
            )
            if deferred_by_source
            else None
        )

        phases: list[_Phase] = []
        capacity_phases: list[_Phase] = []
        vacancy_by_priority: dict[int, list[cp_model.IntVar]] = defaultdict(list)
        vacancy_by_group: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
        for (value, agenda_id), variable in vacancies.items():
            priority = int(agendas[agenda_id].get("priority", 3))
            if priority not in {1, 2, 3, 4}:
                return _failure(
                    "INVALID_AGENDA_PRIORITY",
                    "La prioritat d’una agenda no és vàlida",
                    outcome="model_invalid",
                    details={"agendaId": agenda_id, "priority": priority},
                )
            if demand[(value, agenda_id)] > 0:
                vacancy_by_priority[priority].append(variable)
                modality = "telematic" if bool(agendas[agenda_id].get("telematic", False)) else "onsite"
                vacancy_by_group[(modality, priority)].append(variable)
        uncovered_by_group: dict[tuple[str, int], list[cp_model.IntVar]] = defaultdict(list)
        for (value, agenda_id), vacancy in vacancies.items():
            amount = demand[(value, agenda_id)]
            if amount <= 0:
                continue
            uncovered = model.new_bool_var(f"uncovered_d{date_order[value]}_a{agenda_order[agenda_id]}")
            model.add(vacancy == amount).only_enforce_if(uncovered)
            model.add(vacancy <= amount - 1).only_enforce_if(uncovered.Not())
            priority = int(agendas[agenda_id].get("priority", 3))
            modality = "telematic" if bool(agendas[agenda_id].get("telematic", False)) else "onsite"
            uncovered_by_group[(modality, priority)].append(uncovered)

        def append_coverage_phases(modality: str, priority: int) -> None:
            priority_vacancies = vacancy_by_group.get((modality, priority), [])
            if priority_vacancies:
                phases.append(
                    _Phase(
                        f"{modality}-priority-{priority}-vacancies",
                        sum(priority_vacancies),
                        True,
                    )
                )
            priority_uncovered = uncovered_by_group.get((modality, priority), [])
            if priority_uncovered:
                phases.append(
                    _Phase(
                        f"{modality}-priority-{priority}-uncovered-agenda-days",
                        sum(priority_uncovered),
                        True,
                    )
                )

        for priority in (1, 2, 3, 4):
            append_coverage_phases("onsite", priority)

        guard_without_onsite: list[Any] = []
        for member_id, value in sorted(
            guard_keys,
            key=lambda item: (item[1], member_order.get(item[0], -1)),
        ):
            if member_id not in members or member_id not in planifiable.get(value, []):
                continue
            onsite_variables = [
                variable
                for (
                    person_id,
                    assignment_date,
                    agenda_id,
                ), variable in assignments.items()
                if person_id == member_id
                and assignment_date == value
                and not bool(agendas[agenda_id].get("telematic", False))
            ]
            if not onsite_variables:
                guard_without_onsite.append(1)
                continue
            has_onsite = model.new_bool_var(f"guard_onsite_p{member_order[member_id]}_d{date_order[value]}")
            model.add_max_equality(has_onsite, onsite_variables)
            guard_without_onsite.append(1 - has_onsite)
        guard_onsite_phase = (
            _Phase("guard-onsite-days", sum(guard_without_onsite), False) if guard_without_onsite else None
        )

        months = sorted({value.strftime("%Y-%m") for value in planning_dates})
        management_counts: dict[tuple[str, str], cp_model.IntVar] = {}
        management_reached: dict[int, list[cp_model.IntVar]] = defaultdict(list)
        for member_id, member in members.items():
            quota = int(member.get("managementQuota", 0))
            if quota <= 0:
                continue
            for month in months:
                month_variables = [
                    variable
                    for (person_id, value), variable in management_assignments.items()
                    if person_id == member_id and value.strftime("%Y-%m") == month
                ]
                weekly_variables: dict[tuple[int, int], list[cp_model.IntVar]] = defaultdict(list)
                for (person_id, value), variable in management_assignments.items():
                    if person_id == member_id and value.strftime("%Y-%m") == month:
                        weekly_variables[value.isocalendar()[:2]].append(variable)
                weekly_cap = _management_weekly_cap(quota, month)
                for variables in weekly_variables.values():
                    model.add(sum(variables) <= weekly_cap)
                count = model.new_int_var(
                    0,
                    min(quota, len(month_variables)),
                    f"management_count_p{member_order[member_id]}_{month.replace('-', '')}",
                )
                model.add(count == sum(month_variables))
                management_counts[(member_id, month)] = count
                for level in range(1, quota + 1):
                    reached = model.new_bool_var(
                        f"management_level_{level}_p{member_order[member_id]}_{month.replace('-', '')}"
                    )
                    model.add(count >= level).only_enforce_if(reached)
                    model.add(count <= level - 1).only_enforce_if(reached.Not())
                    management_reached[level].append(reached)
        for level in range(1, 6):
            reached_variables = management_reached.get(level, [])
            if reached_variables:
                phases.append(
                    _Phase(
                        f"management-round-{level}",
                        len(reached_variables) - sum(reached_variables),
                        True,
                    )
                )

        for priority in (1, 2, 3, 4):
            append_coverage_phases("telematic", priority)

        if partial_days:
            capacity_phases.append(
                _Phase(
                    "partial-person-days",
                    sum(partial_days.values()),
                    True,
                )
            )

        priority_weighted_partial_assignments: list[Any] = []
        for (member_id, value, agenda_id), assignment in assignments.items():
            if agenda_load_units[agenda_id] != 1:
                continue
            partial_assignment = model.new_bool_var(
                f"partial_assignment_p{member_order[member_id]}_d{date_order[value]}_a{agenda_order[agenda_id]}"
            )
            partial_day = partial_days[(member_id, value)]
            model.add(partial_assignment <= assignment)
            model.add(partial_assignment <= partial_day)
            model.add(partial_assignment >= assignment + partial_day - 1)
            priority_weight = 5 - int(agendas[agenda_id].get("priority", 3))
            priority_weighted_partial_assignments.append(partial_assignment * priority_weight)
        if priority_weighted_partial_assignments:
            capacity_phases.append(
                _Phase(
                    "priority-weighted-partial-person-days",
                    sum(priority_weighted_partial_assignments),
                    True,
                )
            )

        if unassigned:
            capacity_phases.append(
                _Phase(
                    "unassigned-person-days",
                    sum(unassigned.values()),
                    True,
                )
            )

        time_limit = max(float(config.get("timeLimitSeconds", 120)), 0.1)
        workers = max(int(config.get("workers", 1)), 1)
        deadline = monotonic() + time_limit
        polishing_reserve = _polishing_reserve(time_limit)
        solver_deadline = deadline
        polishing_deadline = deadline
        phase_metrics: list[dict[str, Any]] = []
        last_solver: cp_model.CpSolver | None = None
        all_phases_optimal = True
        diagnostics: list[str] = []

        def retain_solution_as_hint(solver: cp_model.CpSolver) -> None:
            model.clear_hints()  # type: ignore[no-untyped-call]
            for variable_index in range(len(model.proto.variables)):
                variable = model.get_int_var_from_proto_index(variable_index)
                model.add_hint(variable, int(solver.value(variable)))

        def run_phases(stage_phases: list[_Phase]) -> ScheduleResult | None:
            nonlocal last_solver, all_phases_optimal
            for phase_index, phase in enumerate(stage_phases):
                remaining = solver_deadline - monotonic()
                if remaining <= 0:
                    if phase.requires_optimum or last_solver is None:
                        return _failure(
                            "SCHEDULER_LIMIT_REACHED",
                            "No s’ha pogut demostrar la prioritat correcta dins del temps disponible",
                            outcome="unknown",
                            details={
                                "phase": phase.name,
                                "completedPhases": phase_metrics,
                            },
                            diagnostics=[f"Temps esgotat abans de {phase.name}"],
                        )
                    all_phases_optimal = False
                    diagnostics.append(f"Temps esgotat abans d’optimitzar {phase.name}")
                    break
                model.minimize(phase.expression)
                solver = cp_model.CpSolver()
                phase_time_limit = _phase_time_budget(stage_phases, phase_index, remaining)
                solver.parameters.max_time_in_seconds = phase_time_limit
                solver.parameters.num_search_workers = workers
                solver.parameters.random_seed = random_seed
                status = solver.solve(model)
                status_name = solver.status_name(status)
                phase_metric: dict[str, Any] = {
                    "name": phase.name,
                    "status": status_name,
                    "timeLimitSeconds": round(phase_time_limit, 4),
                    "wallTimeSeconds": round(solver.wall_time, 4),
                    "conflicts": solver.num_conflicts,
                    "branches": solver.num_branches,
                }
                if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
                    objective_value = int(solver.value(phase.expression))
                    phase_metric.update(
                        {
                            "value": objective_value,
                            "bestBound": round(float(solver.best_objective_bound), 4),
                        }
                    )
                    phase_metrics.append(phase_metric)
                    last_solver = solver
                    if status == cp_model.OPTIMAL:
                        model.add(phase.expression == objective_value)
                        model.clear_objective()  # type: ignore[no-untyped-call]
                        retain_solution_as_hint(solver)
                        continue
                    all_phases_optimal = False
                    if phase.requires_optimum:
                        return _failure(
                            "SCHEDULER_LIMIT_REACHED",
                            "No s’ha pogut demostrar la prioritat correcta dins del temps disponible",
                            outcome="unknown",
                            details={
                                "phase": phase.name,
                                "completedPhases": phase_metrics,
                            },
                            diagnostics=[f"La fase {phase.name} només ha trobat una solució no provada"],
                        )
                    diagnostics.append(f"La fase {phase.name} ha quedat en una solució factible")
                    model.add(phase.expression <= objective_value)
                    model.clear_objective()  # type: ignore[no-untyped-call]
                    retain_solution_as_hint(solver)
                    continue
                phase_metrics.append(phase_metric)
                if status == cp_model.INFEASIBLE:
                    return _failure(
                        "NO_FEASIBLE_SCHEDULE",
                        "No existeix cap calendari que compleixi totes les regles",
                        details={"phase": phase.name},
                    )
                if status == cp_model.MODEL_INVALID:
                    return _failure(
                        "SCHEDULER_MODEL_INVALID",
                        "El model de planificació no és vàlid",
                        outcome="model_invalid",
                        details={"phase": phase.name},
                    )
                if last_solver is not None and not phase.requires_optimum:
                    all_phases_optimal = False
                    diagnostics.append(f"No s’ha pogut millorar la fase {phase.name}")
                    break
                return _failure(
                    "SCHEDULER_LIMIT_REACHED",
                    "No s’ha trobat una solució dins del temps disponible",
                    outcome="unknown",
                    details={"phase": phase.name},
                )
            return None

        if not phases:
            phases.append(_Phase("feasibility", 0, True))
        hard_phases = phases
        phases = []

        def build_telematic_balance() -> tuple[
            dict[str, cp_model.IntVar],
            dict[str, cp_model.IntVar],
            dict[str, cp_model.IntVar],
            cp_model.IntVar | None,
            Any | None,
            list[_Phase],
        ]:
            balance_phases: list[_Phase] = []
            telematic_counts: dict[str, cp_model.IntVar] = {}
            total_counts: dict[str, cp_model.IntVar] = {}
            percentages: dict[str, cp_model.IntVar] = {}
            has_activity: dict[str, cp_model.IntVar] = {}
            for member_id in members:
                member_dates = [value for value in planning_dates if member_id in planifiable.get(value, [])]
                if not member_dates:
                    continue
                assigned_days: list[cp_model.IntVar] = []
                telematic_days: list[cp_model.IntVar] = []
                for value in member_dates:
                    assigned_day = model.new_bool_var(
                        f"assigned_day_p{member_order[member_id]}_d{date_order[value]}"
                    )
                    model.add(assigned_day + unassigned[(member_id, value)] == 1)
                    onsite_variables = [
                        variable
                        for (person_id, assignment_date, agenda_id), variable in assignments.items()
                        if person_id == member_id
                        and assignment_date == value
                        and not bool(agendas[agenda_id].get("telematic", False))
                    ]
                    onsite_day = model.new_bool_var(
                        f"onsite_day_p{member_order[member_id]}_d{date_order[value]}"
                    )
                    if onsite_variables:
                        model.add_max_equality(onsite_day, onsite_variables)
                    else:
                        model.add(onsite_day == 0)
                    telematic_day = model.new_bool_var(
                        f"telematic_day_p{member_order[member_id]}_d{date_order[value]}"
                    )
                    model.add(telematic_day == assigned_day - onsite_day)
                    assigned_days.append(assigned_day)
                    telematic_days.append(telematic_day)

                maximum_assignments = len(member_dates)
                total_count = model.new_int_var(
                    0,
                    maximum_assignments,
                    f"assigned_day_count_p{member_order[member_id]}",
                )
                model.add(total_count == sum(assigned_days))
                telematic_count = model.new_int_var(
                    0,
                    maximum_assignments,
                    f"telematic_day_count_p{member_order[member_id]}",
                )
                model.add(telematic_count == sum(telematic_days))
                active = model.new_bool_var(
                    f"has_activity_p{member_order[member_id]}"
                )
                model.add(total_count >= 1).only_enforce_if(active)
                model.add(total_count == 0).only_enforce_if(active.Not())
                safe_total = model.new_int_var(
                    1,
                    max(maximum_assignments, 1),
                    f"safe_activity_count_p{member_order[member_id]}",
                )
                model.add_max_equality(safe_total, [total_count, 1])
                percentage = model.new_int_var(
                    0,
                    10_000,
                    f"telematic_percentage_p{member_order[member_id]}",
                )
                model.add_division_equality(
                    percentage,
                    telematic_count * 10_000,
                    safe_total,
                )
                telematic_counts[member_id] = telematic_count
                total_counts[member_id] = total_count
                percentages[member_id] = percentage
                has_activity[member_id] = active

            balance_range: cp_model.IntVar | None = None
            total_dispersion: Any | None = None
            pairwise_differences: list[cp_model.IntVar] = []
            percentage_members = list(percentages)
            for left_index, left_id in enumerate(percentage_members):
                for right_id in percentage_members[left_index + 1 :]:
                    difference = model.new_int_var(
                        0,
                        10_000,
                        "telematic_percentage_difference_"
                        f"p{member_order[left_id]}_p{member_order[right_id]}",
                    )
                    model.add_abs_equality(
                        difference,
                        percentages[left_id] - percentages[right_id],
                    )
                    comparable = model.new_bool_var(
                        "telematic_percentage_comparable_"
                        f"p{member_order[left_id]}_p{member_order[right_id]}"
                    )
                    model.add(comparable <= has_activity[left_id])
                    model.add(comparable <= has_activity[right_id])
                    model.add(
                        comparable
                        >= has_activity[left_id] + has_activity[right_id] - 1
                    )
                    effective_difference = model.new_int_var(
                        0,
                        10_000,
                        "telematic_percentage_effective_difference_"
                        f"p{member_order[left_id]}_p{member_order[right_id]}",
                    )
                    model.add(effective_difference == difference).only_enforce_if(
                        comparable
                    )
                    model.add(effective_difference == 0).only_enforce_if(
                        comparable.Not()
                    )
                    pairwise_differences.append(effective_difference)
            if pairwise_differences:
                balance_range = model.new_int_var(
                    0, 10_000, "telematic_percentage_range"
                )
                model.add_max_equality(balance_range, pairwise_differences)
                balance_phases.append(
                    _Phase("telematic-percentage-range", balance_range, False)
                )

                total_dispersion = sum(pairwise_differences)
                balance_phases.append(
                    _Phase(
                        "telematic-percentage-dispersion",
                        total_dispersion,
                        False,
                    )
                )
            return (
                telematic_counts,
                total_counts,
                percentages,
                balance_range,
                total_dispersion,
                balance_phases,
            )

        historical_totals = {
            member_id: sum(int(value) for value in problem.historical_counts.get(member_id, {}).values())
            for member_id in members
        }
        maximum_profile_totals = {
            member_id: 2 * sum(member_id in planifiable[value] for value in planning_dates)
            + historical_totals[member_id]
            for member_id in members
        }
        profile_counts: dict[tuple[str, str], Any] = {}
        for member_id in members:
            for agenda_id in agendas:
                new_count = sum(
                    (
                        assignments[(member_id, value, agenda_id)] * agenda_load_units[agenda_id]
                        for value in planning_dates
                        if (member_id, value, agenda_id) in assignments
                    ),
                    0,
                )
                new_count += sum(
                    variable * agenda_load_units[agenda_id]
                    for (origin, deferred_agenda_id, target, person_id), variable in deferred_assignments.items()
                    if person_id == member_id and deferred_agenda_id == agenda_id
                )
                profile_counts[(member_id, agenda_id)] = (
                    int(problem.historical_counts.get(member_id, {}).get(agenda_id, 0)) + new_count
                )
        fairness = add_operational_fairness(
            model,
            member_ids=list(members),
            agenda_ids=list(agendas),
            capabilities={member_id: set(member.get("allowedTypes", [])) for member_id, member in members.items()},
            counts=profile_counts,
            maximum_totals=maximum_profile_totals,
            member_order=member_order,
            agenda_order=agenda_order,
            maximum_distance_when_empty=set(problem.first_generation_member_ids),
        )
        person_distances = fairness.person_distances
        worst_fairness = fairness.worst_distance
        if worst_fairness is not None:
            phases.extend(
                [
                    _Phase("worst-historical-distance", worst_fairness, False),
                    _Phase("total-historical-distance", sum(person_distances.values()), False),
                ]
            )

        consecutive_clinical_agendas: list[cp_model.IntVar] = []
        for member_id in members:
            for agenda_id in agendas:
                for value in planning_dates:
                    following = value + timedelta(days=1)
                    current_variables = [assignments[(member_id, value, agenda_id)]] if (
                        member_id, value, agenda_id
                    ) in assignments else []
                    current_variables.extend(
                        deferred_by_target_agenda.get((member_id, value, agenda_id), [])
                    )
                    next_variables = [assignments[(member_id, following, agenda_id)]] if (
                        member_id, following, agenda_id
                    ) in assignments else []
                    next_variables.extend(
                        deferred_by_target_agenda.get((member_id, following, agenda_id), [])
                    )
                    if not current_variables or not next_variables:
                        continue
                    current = model.new_bool_var(
                        "agenda_day_"
                        f"p{member_order[member_id]}_d{date_order[value]}_a{agenda_order[agenda_id]}"
                    )
                    next_assignment = model.new_bool_var(
                        "agenda_day_"
                        f"p{member_order[member_id]}_d{date_order.get(following, len(date_order))}"
                        f"_a{agenda_order[agenda_id]}"
                    )
                    model.add_max_equality(current, current_variables)
                    model.add_max_equality(next_assignment, next_variables)
                    repeated = model.new_bool_var(
                        "consecutive_clinical_"
                        f"p{member_order[member_id]}_d{date_order[value]}_a{agenda_order[agenda_id]}"
                    )
                    model.add(repeated <= current)
                    model.add(repeated <= next_assignment)
                    model.add(repeated >= current + next_assignment - 1)
                    consecutive_clinical_agendas.append(repeated)
        if consecutive_clinical_agendas:
            phases.append(
                _Phase(
                    "consecutive-clinical-agendas",
                    sum(consecutive_clinical_agendas),
                    False,
                )
            )

        if management_assignments:
            management_vacancy_pressure: list[cp_model.IntVar] = []
            for value in planning_dates:
                day_vacancies = [
                    variable
                    for (vacancy_date, agenda_id), variable in vacancies.items()
                    if vacancy_date == value and demand[(vacancy_date, agenda_id)] > 0
                ]
                maximum_daily_vacancies = sum(
                    demand[(value, agenda_id)] for agenda_id in agendas if demand[(value, agenda_id)] > 0
                )
                if not day_vacancies or maximum_daily_vacancies <= 0:
                    continue
                daily_vacancies = model.new_int_var(
                    0,
                    maximum_daily_vacancies,
                    f"daily_vacancies_d{date_order[value]}",
                )
                model.add(daily_vacancies == sum(day_vacancies))
                for (
                    member_id,
                    management_date,
                ), management in management_assignments.items():
                    if management_date != value:
                        continue
                    exposed_vacancies = model.new_int_var(
                        0,
                        maximum_daily_vacancies,
                        f"management_vacancy_pressure_p{member_order[member_id]}_d{date_order[value]}",
                    )
                    model.add(exposed_vacancies == daily_vacancies).only_enforce_if(management)
                    model.add(exposed_vacancies == 0).only_enforce_if(management.Not())
                    management_vacancy_pressure.append(exposed_vacancies)
            if management_vacancy_pressure:
                phases.append(
                    _Phase(
                        "management-low-vacancy-days",
                        sum(management_vacancy_pressure),
                        False,
                    )
                )
            non_friday = [
                variable for (_member_id, value), variable in management_assignments.items() if value.isoweekday() != 5
            ]
            after_monday = [
                variable
                for (_member_id, value), variable in management_assignments.items()
                if value.isoweekday() not in {1, 5}
            ]
            phases.extend(
                [
                    _Phase("management-fridays", sum(non_friday), False),
                    _Phase("management-mondays", sum(after_monday), False),
                ]
            )

        if shared_rule_tiebreak:
            phases.append(_Phase("shared-fixed-rule-random-tiebreak", sum(shared_rule_tiebreak), False))

        legacy_soft_phases = phases
        hard_failure = run_phases(hard_phases)
        if hard_failure is not None:
            return hard_failure
        solver_deadline = max(monotonic(), deadline - polishing_reserve)

        phases = []
        if guard_onsite_phase is not None:
            phases.append(guard_onsite_phase)
        if automatic_deferred_phase is not None:
            phases.append(automatic_deferred_phase)
        phases.extend(capacity_phases)
        (
            telematic_assignment_counts,
            total_assignment_counts,
            telematic_percentages,
            telematic_range,
            telematic_total_dispersion,
            telematic_balance_phases,
        ) = build_telematic_balance()
        phases.extend(telematic_balance_phases)
        phases.extend(legacy_soft_phases)
        if not phases:
            phases.append(_Phase("post-feasibility", 0, False))
        soft_failure = run_phases(phases)
        if soft_failure is not None:
            return soft_failure

        if last_solver is None:  # pragma: no cover - every valid model has a feasibility phase
            return _failure("SCHEDULER_ERROR", "El planificador no ha retornat cap solució", outcome="unknown")

        result_assignments: list[dict[str, Any]] = []
        for (member_id, value, agenda_id), variable in assignments.items():
            if last_solver.value(variable) != 1:
                continue
            locked_item = locked_by_key.get((member_id, value, agenda_id))
            result_assignments.append(
                {
                    "id": locked_by_key.get((member_id, value, agenda_id), {}).get("id") or uuid4().hex,
                    "date": value.isoformat(),
                    "memberId": member_id,
                    "type": agenda_id,
                    **(
                        {
                            key: locked_item[key]
                            for key in (
                                "locked",
                                "extra",
                                "peonada",
                                "deferredOriginDate",
                                "manuallyModified",
                            )
                            if key in locked_item
                        }
                        if locked_item
                        else {}
                    ),
                    **({"fixed": True} if (member_id, value, agenda_id) in fixed_assignments else {}),
                }
            )
        selected_deferred_by_source: Counter[tuple[date, str]] = Counter()
        automatic_deferred_assignments: list[dict[str, Any]] = []
        for (origin, agenda_id, target, member_id), variable in deferred_assignments.items():
            if last_solver.value(variable) != 1:
                continue
            selected_deferred_by_source[(origin, agenda_id)] += 1
            automatic_deferred_assignments.append(
                {
                    "id": uuid4().hex,
                    "date": target.isoformat(),
                    "memberId": member_id,
                    "type": agenda_id,
                    "deferredOriginDate": origin.isoformat(),
                }
            )
        result_assignments.extend(automatic_deferred_assignments)
        for (member_id, value), variable in management_assignments.items():
            if last_solver.value(variable) != 1:
                continue
            result_assignments.append(
                {
                    "id": locked_by_key.get((member_id, value, "management"), {}).get("id") or uuid4().hex,
                    "date": value.isoformat(),
                    "memberId": member_id,
                    "type": "management",
                    "management": True,
                    "telematic": True,
                    **locked_by_key.get((member_id, value, "management"), {}),
                }
            )
        for (member_id, value), variable in unassigned.items():
            if last_solver.value(variable) != 1:
                continue
            result_assignments.append(
                {
                    "id": locked_by_key.get((member_id, value, "no_assignment"), {}).get("id") or uuid4().hex,
                    "date": value.isoformat(),
                    "memberId": member_id,
                    "type": "no_assignment",
                    **locked_by_key.get((member_id, value, "no_assignment"), {}),
                }
            )
        result_assignments.sort(
            key=lambda item: (
                item["date"],
                member_order[item["memberId"]],
                agenda_order.get(item["type"], len(agenda_order)),
            )
        )

        result_vacancies: list[dict[str, Any]] = []
        for (value, agenda_id), variable in vacancies.items():
            remaining = int(last_solver.value(variable)) - selected_deferred_by_source[(value, agenda_id)]
            result_vacancies.extend({"date": value.isoformat(), "type": agenda_id} for _ in range(remaining))
        result_vacancies.sort(key=lambda item: (item["date"], agenda_order[item["type"]]))
        daily_unit_values = {key: int(last_solver.value(expression)) for key, expression in daily_load_units.items()}
        partial_keys = {key for key, units in daily_unit_values.items() if units == 1}
        unassigned_keys = {key for key, units in daily_unit_values.items() if units == 0}

        metrics: dict[str, Any] = {
            "optimal": all_phases_optimal,
            "runtimeMs": round((monotonic() - started) * 1000),
            "solverStatus": phase_metrics[-1]["status"],
            "ortoolsVersion": ORTOOLS_VERSION,
            "modelVersion": MODEL_VERSION,
            "randomSeed": random_seed,
            "optimizationMode": optimization_mode,
            "phases": phase_metrics,
            "vacanciesByPriority": {
                str(priority): sum(
                    1
                    for item in result_vacancies
                    if int(agendas[item["type"]].get("priority", 3)) == priority
                )
                for priority in sorted(vacancy_by_priority)
            },
            "automaticDeferred": {
                "assigned": len(automatic_deferred_assignments),
                "byMember": dict(Counter(item["memberId"] for item in automatic_deferred_assignments)),
                "remainingTelematicVacancies": sum(
                    1
                    for item in result_vacancies
                    if bool(agendas.get(item["type"], {}).get("telematic", False))
                ),
            },
            "management": {
                f"{member_id}:{month}": {
                    "assignments": int(last_solver.value(expression)),
                    "quota": int(members[member_id].get("managementQuota", 0)),
                    "weeklyCap": _management_weekly_cap(
                        int(members[member_id].get("managementQuota", 0)),
                        month,
                    ),
                    "deficit": (int(members[member_id].get("managementQuota", 0)) - int(last_solver.value(expression))),
                    "fridays": sum(
                        int(last_solver.value(variable))
                        for (person_id, value), variable in management_assignments.items()
                        if person_id == member_id and value.strftime("%Y-%m") == month and value.isoweekday() == 5
                    ),
                    "mondays": sum(
                        int(last_solver.value(variable))
                        for (person_id, value), variable in management_assignments.items()
                        if person_id == member_id and value.strftime("%Y-%m") == month and value.isoweekday() == 1
                    ),
                }
                for (member_id, month), expression in management_counts.items()
            },
            "fairness": {
                "worstDistanceBasisPoints": (
                    int(last_solver.value(worst_fairness)) if worst_fairness is not None else None
                ),
                "personDistanceBasisPoints": {
                    member_id: int(last_solver.value(value)) for member_id, value in person_distances.items()
                },
            },
            "guardOnsite": {
                "guardDays": len(guard_without_onsite),
                "telematicFallbacks": sum(int(last_solver.value(value)) for value in guard_without_onsite),
            },
            "telematicBalance": {
                "telematicDaysByMember": {
                    member_id: int(last_solver.value(value))
                    for member_id, value in telematic_assignment_counts.items()
                },
                "totalAssignedDaysByMember": {
                    member_id: int(last_solver.value(value))
                    for member_id, value in total_assignment_counts.items()
                },
                "telematicAssignmentsByMember": {
                    member_id: int(last_solver.value(value))
                    for member_id, value in telematic_assignment_counts.items()
                },
                "totalAssignmentsByMember": {
                    member_id: int(last_solver.value(value))
                    for member_id, value in total_assignment_counts.items()
                },
                "percentageByMember": {
                    member_id: (
                        int(last_solver.value(telematic_percentages[member_id])) / 100
                        if int(last_solver.value(total_assignment_counts[member_id]))
                        else None
                    )
                    for member_id in telematic_percentages
                },
                "rangePercentagePoints": (
                    int(last_solver.value(telematic_range)) / 100
                    if telematic_range is not None
                    else 0.0
                ),
                "totalPairwiseDeviationBasisPoints": (
                    int(last_solver.value(telematic_total_dispersion))
                    if telematic_total_dispersion is not None
                    else 0
                ),
            },
            "consecutiveClinicalAgendas": sum(int(last_solver.value(value)) for value in consecutive_clinical_agendas),
            "unassigned": {
                "count": len(unassigned_keys),
                "loadUnits": 2 * len(unassigned_keys),
                "partialDays": len(partial_keys),
                "people": len({member_id for member_id, _value in unassigned_keys}),
            },
            "partial": {
                "count": len(partial_keys),
                "loadUnits": len(partial_keys),
                "people": len({member_id for member_id, _value in partial_keys}),
            },
        }
        result = ScheduleResult(
            outcome="solution",
            assignments=result_assignments,
            vacancies=result_vacancies,
            metrics=metrics,
            diagnostics=diagnostics,
            engine="cp-sat",
            engine_version=MODEL_VERSION,
        )
        validation_errors = validate_solution(problem, result.to_dict())
        if validation_errors:
            return _failure(
                "SCHEDULER_RESULT_INVALID",
                "El planificador ha produït un calendari invàlid",
                outcome="model_invalid",
                details={"violations": validation_errors},
            )
        polishing_started = monotonic()
        remaining_polishing_time = max(polishing_deadline - polishing_started, 0)
        operational_polishing_deadline = (
            polishing_started + remaining_polishing_time * 0.6
        )
        operationally_polished, operational_polishing_metrics = _polish_solution(
            problem,
            result.to_dict(),
            deadline=operational_polishing_deadline,
            objective="operational-fairness",
            allow_vacancies=True,
        )
        polished, telematic_polishing_metrics = _polish_solution(
            problem,
            operationally_polished,
            deadline=polishing_deadline,
            objective="telematic-percentage",
            allow_vacancies=False,
        )
        polishing_metrics = {
            "acceptedMoves": (
                operational_polishing_metrics["acceptedMoves"]
                + telematic_polishing_metrics["acceptedMoves"]
            ),
            "attemptedMoves": (
                operational_polishing_metrics["attemptedMoves"]
                + telematic_polishing_metrics["attemptedMoves"]
            ),
            "completed": (
                operational_polishing_metrics["completed"]
                and telematic_polishing_metrics["completed"]
            ),
            "wallTimeSeconds": round(monotonic() - polishing_started, 4),
            "operationalFairness": operational_polishing_metrics,
            "telematicPercentage": telematic_polishing_metrics,
        }
        polished_metrics = polished["metrics"]
        polished_metrics["polishing"] = polishing_metrics
        polished_metrics["phases"].extend(
            [
                {
                    "name": "operational-fairness-polishing",
                    "status": (
                        "COMPLETED"
                        if operational_polishing_metrics["completed"]
                        else "TIME_LIMIT"
                    ),
                    "wallTimeSeconds": operational_polishing_metrics[
                        "wallTimeSeconds"
                    ],
                    "value": operational_polishing_metrics["acceptedMoves"],
                },
                {
                    "name": "telematic-percentage-polishing",
                    "status": (
                        "COMPLETED"
                        if telematic_polishing_metrics["completed"]
                        else "TIME_LIMIT"
                    ),
                    "wallTimeSeconds": telematic_polishing_metrics[
                        "wallTimeSeconds"
                    ],
                    "value": telematic_polishing_metrics["acceptedMoves"],
                },
            ]
        )
        polished_metrics["runtimeMs"] = round((monotonic() - started) * 1000)
        fairness_score, person_distance_values = _result_fairness(problem, polished)
        polished_metrics["fairness"] = {
            "worstDistanceBasisPoints": fairness_score[0],
            "personDistanceBasisPoints": person_distance_values,
        }
        (
            telematic_score,
            polished_telematic_counts,
            polished_total_counts,
            polished_telematic_percentages,
        ) = _result_telematic_balance(problem, polished)
        comparable_percentages = [
            value / 100
            for value in polished_telematic_percentages.values()
            if value is not None
        ]
        polished_metrics["telematicBalance"] = {
            "telematicDaysByMember": polished_telematic_counts,
            "totalAssignedDaysByMember": polished_total_counts,
            "telematicAssignmentsByMember": polished_telematic_counts,
            "totalAssignmentsByMember": polished_total_counts,
            "percentageByMember": {
                member_id: value / 100 if value is not None else None
                for member_id, value in polished_telematic_percentages.items()
            },
            "rangePercentagePoints": telematic_score[0] / 100,
            "totalPairwiseDeviationBasisPoints": telematic_score[1],
            "standardDeviationPercentagePoints": (
                round(pstdev(comparable_percentages), 4)
                if comparable_percentages
                else 0.0
            ),
        }
        polished_metrics["consecutiveClinicalAgendas"] = _result_repetitions(problem, polished)
        final_validation_errors = validate_solution(problem, polished)
        if final_validation_errors:
            return _failure(
                "SCHEDULER_RESULT_INVALID",
                "El poliment ha produït un calendari invàlid",
                outcome="model_invalid",
                details={"violations": final_validation_errors},
            )
        return ScheduleResult(**polished)


def _result_fairness(
    problem: ScheduleProblem,
    result: dict[str, Any],
) -> tuple[tuple[int, int], dict[str, int]]:
    member_ids = [str(item["id"]) for item in problem.team if item.get("active", True)]
    agenda_ids = [str(item["id"]) for item in problem.agendas]
    loads = {str(item["id"]): int(item.get("loadPercentage", 100)) / 50 for item in problem.agendas}
    counts = {
        member_id: {
            agenda_id: float(problem.historical_counts.get(member_id, {}).get(agenda_id, 0)) for agenda_id in agenda_ids
        }
        for member_id in member_ids
    }
    for item in result.get("assignments", []):
        member_id = item.get("memberId")
        agenda_id = item.get("type")
        if member_id in counts and agenda_id in loads:
            counts[member_id][agenda_id] += loads[agenda_id]
    capabilities = {
        str(item["id"]): set(item.get("allowedTypes", [])) for item in problem.team if item.get("active", True)
    }
    planning_dates = _planning_dates(problem)
    members = {str(item["id"]): item for item in problem.team}
    maximum_totals = {
        member_id: sum(counts[member_id].values())
        + 2 * sum(_is_planifiable(members[member_id], value, problem) for value in planning_dates)
        for member_id in member_ids
    }
    totals = {member_id: sum(counts[member_id].values()) for member_id in member_ids}
    cohorts = {
        agenda_id: [
            member_id
            for member_id in member_ids
            if agenda_id in capabilities[member_id] and maximum_totals[member_id] > 0
        ]
        for agenda_id in agenda_ids
    }
    cohorts = {agenda_id: cohort for agenda_id, cohort in cohorts.items() if len(cohort) >= 2}
    raw_shares = {
        (member_id, agenda_id): counts[member_id][agenda_id] / max(totals[member_id], 1.0)
        for agenda_id, cohort in cohorts.items()
        for member_id in cohort
    }
    distances: dict[str, float] = {}
    for member_id in member_ids:
        comparable = [agenda_id for agenda_id, cohort in cohorts.items() if member_id in cohort]
        if not comparable:
            continue
        comparable_total = sum(counts[member_id][agenda_id] for agenda_id in comparable)
        peer_means = {
            agenda_id: sum(raw_shares[(peer_id, agenda_id)] for peer_id in cohorts[agenda_id] if peer_id != member_id)
            / (len(cohorts[agenda_id]) - 1)
            for agenda_id in comparable
        }
        reference_total = sum(peer_means.values())
        distance = (
            sum(
                abs(
                    counts[member_id][agenda_id] / max(comparable_total, 1.0)
                    - peer_means[agenda_id] / (reference_total if reference_total > 0 else 1.0)
                )
                for agenda_id in comparable
            )
            / 2
        )
        if member_id in problem.first_generation_member_ids and comparable_total <= 0:
            distance = 1.0
        distances[member_id] = min(1.0, distance)
    values = {member_id: round(value * 10_000) for member_id, value in distances.items()}
    return (max(values.values(), default=0), sum(values.values())), values


def _result_telematic_balance(
    problem: ScheduleProblem,
    result: dict[str, Any],
) -> tuple[
    tuple[int, int],
    dict[str, int],
    dict[str, int],
    dict[str, int | None],
]:
    planning_dates = _planning_dates(problem)
    members = {str(item["id"]): item for item in problem.team if item.get("active", True)}
    agendas = {str(item["id"]): item for item in problem.agendas}
    eligible = {
        member_id
        for member_id, member in members.items()
        if any(_is_planifiable(member, value, problem) for value in planning_dates)
    }
    telematic_counts = {member_id: 0 for member_id in sorted(eligible)}
    total_counts = {member_id: 0 for member_id in sorted(eligible)}
    days: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for item in result.get("assignments", []):
        member_id = str(item.get("memberId"))
        activity_type = item.get("type")
        if member_id not in eligible:
            continue
        if activity_type == "management":
            days[(member_id, str(item.get("date")))].append(True)
        elif activity_type in agendas:
            days[(member_id, str(item.get("date")))].append(
                bool(agendas[str(activity_type)].get("telematic", False))
            )
    for (member_id, _value), modalities in days.items():
        total_counts[member_id] += 1
        if modalities and all(modalities):
            telematic_counts[member_id] += 1
    percentages: dict[str, int | None] = {
        member_id: (
            telematic_counts[member_id] * 10_000 // total
            if total
            else None
        )
        for member_id, total in total_counts.items()
    }
    values = [value for value in percentages.values() if value is not None]
    if len(values) < 2:
        return (0, 0), telematic_counts, total_counts, percentages
    pairwise_differences = [
        abs(left - right)
        for index, left in enumerate(values)
        for right in values[index + 1 :]
    ]
    return (
        (max(pairwise_differences), sum(pairwise_differences)),
        telematic_counts,
        total_counts,
        percentages,
    )


def _result_guard_fallbacks(problem: ScheduleProblem, result: dict[str, Any]) -> int:
    planning_dates = set(_planning_dates(problem))
    members = {str(item["id"]): item for item in problem.team}
    agendas = {str(item["id"]): item for item in problem.agendas}
    onsite = {
        (str(item["memberId"]), date.fromisoformat(str(item["date"])))
        for item in result.get("assignments", [])
        if item.get("type") in agendas and not bool(agendas[str(item["type"])].get("telematic", False))
    }
    return sum(
        1
        for key in _guard_keys(problem)
        if key[1] in planning_dates
        and key[0] in members
        and _is_planifiable(members[key[0]], key[1], problem)
        and key not in onsite
    )


def _result_repetitions(problem: ScheduleProblem, result: dict[str, Any]) -> int:
    agenda_ids = {str(item["id"]) for item in problem.agendas}
    assignments = {
        (str(item["memberId"]), date.fromisoformat(str(item["date"])), str(item["type"]))
        for item in result.get("assignments", [])
        if item.get("type") in agenda_ids
    }
    return sum(
        (member_id, value + timedelta(days=1), agenda_id) in assignments for member_id, value, agenda_id in assignments
    )


def _result_coverage(problem: ScheduleProblem, result: dict[str, Any]) -> tuple[int, ...]:
    agendas = {str(item["id"]): item for item in problem.agendas}
    demand = _daily_demand(problem, _planning_dates(problem))
    vacancies = Counter(
        (date.fromisoformat(str(item["date"])), str(item["type"])) for item in result.get("vacancies", [])
    )
    values: list[int] = []
    for telematic in (False, True):
        for priority in (1, 2, 3, 4):
            keys = [
                key
                for key, amount in demand.items()
                if amount > 0
                and key[1] in agendas
                and bool(agendas[key[1]].get("telematic", False)) == telematic
                and int(agendas[key[1]].get("priority", 3)) == priority
            ]
            values.append(sum(vacancies[key] for key in keys))
            values.append(sum(vacancies[key] == demand[key] for key in keys))
    return tuple(values)


def _polish_solution(
    problem: ScheduleProblem,
    result: dict[str, Any],
    *,
    deadline: float,
    objective: str = "operational-fairness",
    allow_vacancies: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if objective not in {"operational-fairness", "telematic-percentage"}:
        raise ValueError(f"Unsupported polishing objective: {objective}")
    started = monotonic()
    current = deepcopy(result)
    agendas = {str(item["id"]): item for item in problem.agendas}
    accepted = 0
    attempted = 0
    completed = True

    def mutable(item: dict[str, Any]) -> bool:
        return item.get("type") in agendas and not any(
            item.get(flag)
            for flag in (
                "fixed",
                "locked",
                "extra",
                "peonada",
                "deferredOriginDate",
                "manuallyModified",
            )
        )

    def scores(candidate: dict[str, Any]) -> tuple[tuple[int, ...], int, tuple[int, int], tuple[int, int], int]:
        fairness, _distances = _result_fairness(problem, candidate)
        telematic, _telematic, _total, _percentages = _result_telematic_balance(
            problem, candidate
        )
        return (
            _result_coverage(problem, candidate),
            _result_guard_fallbacks(problem, candidate),
            telematic,
            fairness,
            _result_repetitions(problem, candidate),
        )

    while monotonic() < deadline:
        baseline = scores(current)
        assignments = current.get("assignments", [])
        vacancies = current.get("vacancies", [])
        best: dict[str, Any] | None = None
        best_score: tuple[tuple[int, ...], int, tuple[int, int], tuple[int, int], int] | None = None

        def consider(candidate: dict[str, Any]) -> None:
            nonlocal attempted, best, best_score
            attempted += 1
            if monotonic() >= deadline or validate_solution(problem, candidate):
                return
            candidate_score = scores(candidate)
            coverage, guard, telematic, fairness, repetitions = candidate_score
            if any(after > before for before, after in zip(baseline[0], coverage, strict=True)):
                return
            if guard > baseline[1]:
                return
            if repetitions > baseline[4]:
                return
            rank: tuple[Any, ...]
            best_rank: tuple[Any, ...] | None
            if objective == "operational-fairness":
                if (
                    telematic[0] > baseline[2][0]
                    or telematic[1] > baseline[2][1]
                ):
                    return
                improves = fairness < baseline[3] or (
                    fairness == baseline[3] and repetitions < baseline[4]
                )
                rank = (fairness, repetitions, telematic, coverage, guard)
                best_rank = (
                    (
                        best_score[3],
                        best_score[4],
                        best_score[2],
                        best_score[0],
                        best_score[1],
                    )
                    if best_score is not None
                    else None
                )
            else:
                if fairness > baseline[3]:
                    return
                improves = telematic < baseline[2]
                rank = (telematic, fairness, repetitions, coverage, guard)
                best_rank = (
                    (
                        best_score[2],
                        best_score[3],
                        best_score[4],
                        best_score[0],
                        best_score[1],
                    )
                    if best_score is not None
                    else None
                )
            if not improves:
                return
            if best_rank is None or rank < best_rank:
                best = candidate
                best_score = candidate_score

        for source_index, source in enumerate(assignments):
            if monotonic() >= deadline:
                completed = False
                break
            if not mutable(source):
                continue
            source_agenda = agendas[str(source["type"])]
            for target_index in range(source_index + 1, len(assignments)):
                target = assignments[target_index]
                if (
                    not mutable(target)
                    or target.get("date") != source.get("date")
                    or target.get("memberId") == source.get("memberId")
                    or target.get("type") == source.get("type")
                ):
                    continue
                target_agenda = agendas[str(target["type"])]
                if int(source_agenda.get("loadPercentage", 100)) != int(target_agenda.get("loadPercentage", 100)):
                    continue
                candidate = deepcopy(current)
                candidate["assignments"][source_index]["type"] = target["type"]
                candidate["assignments"][target_index]["type"] = source["type"]
                consider(candidate)
            for vacancy_index, vacancy in enumerate(
                vacancies if allow_vacancies else []
            ):
                if (
                    vacancy.get("date") != source.get("date")
                    or vacancy.get("type") not in agendas
                    or vacancy.get("type") == source.get("type")
                ):
                    continue
                target_agenda = agendas[str(vacancy["type"])]
                if int(source_agenda.get("loadPercentage", 100)) != int(target_agenda.get("loadPercentage", 100)):
                    continue
                if not bool(source_agenda.get("telematic", False)) and bool(target_agenda.get("telematic", False)):
                    continue
                candidate = deepcopy(current)
                candidate["assignments"][source_index]["type"] = vacancy["type"]
                candidate["vacancies"][vacancy_index]["type"] = source["type"]
                consider(candidate)
        if not completed or best is None:
            break
        current = best
        accepted += 1

    if monotonic() >= deadline:
        completed = False
    return current, {
        "objective": objective,
        "acceptedMoves": accepted,
        "attemptedMoves": attempted,
        "remainingImprovingMoves": 0 if completed else None,
        "completed": completed,
        "wallTimeSeconds": round(monotonic() - started, 4),
    }


def validate_solution(problem: ScheduleProblem, result: dict[str, Any]) -> list[str]:
    if result.get("outcome") != "solution":
        return []
    planning_dates = _planning_dates(problem)
    demand = _daily_demand(problem, planning_dates)
    members = {item["id"]: item for item in problem.team}
    agendas = {item["id"]: item for item in problem.agendas}
    guard_keys = _guard_keys(problem)
    expected = {
        (member_id, value.isoformat())
        for value in planning_dates
        for member_id, member in members.items()
        if _is_planifiable(member, value, problem)
    }
    actual_load: Counter[tuple[str, str]] = Counter()
    assigned_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    assignment_keys: Counter[tuple[str, str, str]] = Counter()
    covered: Counter[tuple[str, str]] = Counter()
    management_counts: Counter[tuple[str, str]] = Counter()
    management_week_counts: Counter[tuple[str, str, int, int]] = Counter()
    errors: list[str] = []
    for item in result.get("assignments", []):
        member_id = item.get("memberId")
        value = item.get("date")
        agenda_id = item.get("type")
        if isinstance(member_id, str) and isinstance(value, str) and isinstance(agenda_id, str):
            assigned_types[(member_id, value)].add(agenda_id)
            assignment_keys[(member_id, value, agenda_id)] += 1
            if agenda_id == "no_assignment":
                actual_load[(member_id, value)] += 100
            elif agenda_id == "management":
                actual_load[(member_id, value)] += 100
                management_counts[(member_id, value[:7])] += 1
                iso_year, iso_week, _ = date.fromisoformat(value).isocalendar()
                management_week_counts[(member_id, value[:7], iso_year, iso_week)] += 1
            elif agenda_id in agendas:
                actual_load[(member_id, value)] += int(agendas[agenda_id].get("loadPercentage", 100))
        if (member_id, value) not in expected:
            errors.append(f"unexpected assignment {member_id}:{value}")
        if agenda_id == "management" and int(members.get(member_id, {}).get("managementQuota", 0)) <= 0:
            errors.append(f"management not enabled {member_id}:{value}")
        elif agenda_id not in {"no_assignment", "management"} and (
            agenda_id not in agendas or agenda_id not in members.get(member_id, {}).get("allowedTypes", [])
        ):
            errors.append(f"invalid capability {member_id}:{agenda_id}")
        if (
            agenda_id in agendas
            and isinstance(member_id, str)
            and isinstance(value, str)
            and _is_telework_day(members.get(member_id, {}), date.fromisoformat(value))
            and (member_id, date.fromisoformat(value)) not in guard_keys
            and not bool(agendas[agenda_id].get("telematic", False))
        ):
            errors.append(f"onsite agenda on telework day {member_id}:{value}:{agenda_id}")
        if agenda_id not in {"no_assignment", "management"}:
            coverage_date = item.get("deferredOriginDate") or value
            covered[(coverage_date, agenda_id)] += 1
    if set(actual_load) != expected or any(value not in {50, 100} for value in actual_load.values()):
        errors.append("daily assignment load is not 50 or 100 percent")
    if any(value > 1 for value in assignment_keys.values()):
        errors.append("duplicate agenda assignment for person and date")
    for (member_id, month), count in management_counts.items():
        if count > int(members.get(member_id, {}).get("managementQuota", 0)):
            errors.append(f"management quota exceeded {member_id}:{month}")
    for (member_id, month, iso_year, iso_week), count in management_week_counts.items():
        quota = int(members.get(member_id, {}).get("managementQuota", 0))
        if count > _management_weekly_cap(quota, month):
            errors.append(f"management weekly limit exceeded {member_id}:{month}:{iso_year}-W{iso_week}")
    legacy_rule_groups: dict[tuple[int, str], list[str]] = defaultdict(list)
    personal_rules: list[tuple[str, dict[str, Any]]] = []
    for member_id, member in members.items():
        weekdays: set[int] = set()
        for rule in member.get("fixedRules", []):
            weekday = int(rule["weekday"])
            if weekday in weekdays:
                errors.append(f"multiple fixed rules {member_id}:{weekday}")
            weekdays.add(weekday)
            if "requiredAgendaIds" in rule or "forbiddenAgendaIds" in rule:
                personal_rules.append((member_id, rule))
            else:
                legacy_rule_groups[(weekday, rule["type"])].append(member_id)
    for value in planning_dates:
        key = value.isoformat()
        for (weekday, agenda_id), configured_members in legacy_rule_groups.items():
            if weekday != value.isoweekday():
                continue
            candidates = [
                member_id for member_id in configured_members if _is_planifiable(members[member_id], value, problem)
            ]
            required = min(demand.get((value, agenda_id), 0), len(candidates))
            actual = sum(agenda_id in assigned_types.get((member_id, key), set()) for member_id in candidates)
            if actual != required:
                errors.append(f"shared fixed rule mismatch {agenda_id}:{key}:{actual}/{required}")
        for member_id, rule in personal_rules:
            if int(rule["weekday"]) != value.isoweekday() or not _is_planifiable(members[member_id], value, problem):
                continue
            required_ids = list(dict.fromkeys(rule.get("requiredAgendaIds", [])))
            forbidden_ids = list(dict.fromkeys(rule.get("forbiddenAgendaIds", [])))
            active_required = [agenda_id for agenda_id in required_ids if demand.get((value, agenda_id), 0) > 0]
            assigned = assigned_types.get((member_id, key), set())
            actual_required = sum(agenda_id in assigned for agenda_id in active_required)
            if rule.get("requiredMode", "all") == "all" and actual_required != len(active_required):
                errors.append(f"personal fixed all mismatch {member_id}:{key}")
            if rule.get("requiredMode", "all") == "one" and active_required and actual_required != 1:
                errors.append(f"personal fixed one mismatch {member_id}:{key}")
            if any(agenda_id in assigned for agenda_id in forbidden_ids):
                errors.append(f"personal fixed forbidden mismatch {member_id}:{key}")
    vacancy_counts = Counter((item.get("date"), item.get("type")) for item in result.get("vacancies", []))
    valid_demand_keys = {(value.isoformat(), agenda_id) for value, agenda_id in demand}
    for demand_key in set(covered) | set(vacancy_counts):
        if demand_key not in valid_demand_keys:
            errors.append(f"unexpected demand key {demand_key[0]}:{demand_key[1]}")
    for (value, agenda_id), amount in demand.items():
        demand_key = (value.isoformat(), agenda_id)
        if covered[demand_key] + vacancy_counts[demand_key] != amount:
            errors.append(f"demand mismatch {demand_key[0]}:{agenda_id}")
    return errors


def solve_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return CpSatScheduler().solve(ScheduleProblem.from_dict(snapshot)).to_dict()
