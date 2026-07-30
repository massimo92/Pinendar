from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.metadata import version
from random import Random
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

MODEL_VERSION = "17"
PERCENT_SCALE = 10_000
ORTOOLS_VERSION = version("ortools")


@dataclass(frozen=True)
class _Phase:
    name: str
    expression: Any
    requires_optimum: bool


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
    calendar_weeks = len({
        value.isocalendar()[:2]
        for value in period_dates(month, month)
    })
    return max(1, (quota + calendar_weeks - 1) // calendar_weeks)


def _member_absences(member: dict[str, Any], problem: ScheduleProblem) -> list[dict[str, Any]]:
    return [
        *member.get("vacations", member.get("absences", [])),
        *(
            item
            for item in problem.conditions.get("absences", [])
            if item.get("memberId") == member.get("id")
        ),
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


def _is_present(member: dict[str, Any], value: date, problem: ScheduleProblem) -> bool:
    if not member.get("active", True):
        return False
    key = value.isoformat()
    if any(item["start"] <= key <= item["end"] for item in _member_absences(member, problem)):
        return False
    guards = [*problem.guards, *problem.conditions.get("guards", [])]
    return not any(
        item.get("memberId") == member.get("id")
        and date.fromisoformat(item["date"]) + timedelta(days=1) == value
        for item in guards
    )


def _daily_demand(
    problem: ScheduleProblem, planning_dates: list[date]
) -> dict[tuple[date, str], int]:
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
        if problem.schema_version not in {1, 2, 3, 4, 5, 6, 7}:
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
        agenda_load = {
            agenda_id: int(agenda.get("loadPercentage", 100))
            for agenda_id, agenda in agendas.items()
        }
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
        assigned_load_units: dict[tuple[str, date], Any] = {}
        daily_load_units: dict[tuple[str, date], Any] = {}
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
                    management = model.new_bool_var(
                        f"management_p{member_order[member_id]}_d{date_order[value]}"
                    )
                    management_assignments[(member_id, value)] = management
                no_assignment = model.new_bool_var(
                    f"unassigned_p{member_order[member_id]}_d{date_order[value]}"
                )
                unassigned[(member_id, value)] = no_assignment
                partial_day = model.new_bool_var(
                    f"partial_p{member_order[member_id]}_d{date_order[value]}"
                )
                partial_days[(member_id, value)] = partial_day
                assigned_units = sum(
                    assignments[(member_id, value, agenda_id)]
                    * agenda_load_units[agenda_id]
                    for agenda_id in candidates
                )
                assigned_load_units[(member_id, value)] = assigned_units
                daily_units = assigned_units + (2 * management if management is not None else 0)
                daily_load_units[(member_id, value)] = daily_units
                model.add(no_assignment + partial_day <= 1)
                model.add(daily_units == 2 - (2 * no_assignment) - partial_day)

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
                variable = model.new_int_var(
                    0, amount, f"vac_d{date_order[value]}_a{agenda_order[agenda_id]}"
                )
                vacancies[(value, agenda_id)] = variable
                covered = [
                    assignment
                    for (member_id, assignment_date, assignment_agenda), assignment in assignments.items()
                    if assignment_date == value and assignment_agenda == agenda_id
                    and not locked_by_key.get(
                        (member_id, assignment_date, assignment_agenda), {}
                    ).get("extra")
                ]
                model.add(sum(covered) + variable == amount)

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
                if (
                    agenda_id not in agendas
                    or agenda_id not in member.get("allowedTypes", [])
                ):
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
                or not referenced_ids.issubset(
                    set(members[member_id].get("allowedTypes", []))
                )
            ):
                return _failure(
                    "FIXED_RULE_CONFLICT",
                    "Una regla fixa conté condicions no vàlides",
                    details={"memberId": member_id, "weekday": weekday},
                )
            for value in planning_dates:
                if (
                    value.isoweekday() != weekday
                    or member_id not in planifiable.get(value, [])
                ):
                    continue
                active_required = [
                    agenda_id
                    for agenda_id in required_ids
                    if demand.get((value, agenda_id), 0) > 0
                ]
                required_variables = [
                    assignments[(member_id, value, agenda_id)]
                    for agenda_id in active_required
                    if (member_id, value, agenda_id) in assignments
                ]
                if required_mode == "all" and len(required_variables) != len(
                    active_required
                ):
                    return _failure(
                        "FIXED_RULE_CONFLICT",
                        "Una agenda obligatòria no és compatible amb la persona",
                        details={
                            "memberId": member_id,
                            "date": value.isoformat(),
                        },
                    )
                if required_mode == "all":
                    for agenda_id, variable in zip(
                        active_required, required_variables, strict=True
                    ):
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
                    forbidden_variable = assignments.get(
                        (member_id, value, agenda_id)
                    )
                    if forbidden_variable is not None:
                        model.add(forbidden_variable == 0)

        for (weekday, agenda_id), configured_members in legacy_rule_groups.items():
            recurring_weekdays = {
                int(recurrence["weekday"])
                for recurrence in agendas[agenda_id].get("recurrences", [])
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

        phases: list[_Phase] = []
        vacancy_by_priority: dict[int, list[cp_model.IntVar]] = defaultdict(list)
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
        uncovered_by_priority: dict[int, list[cp_model.IntVar]] = defaultdict(list)
        for (value, agenda_id), vacancy in vacancies.items():
            amount = demand[(value, agenda_id)]
            if amount <= 0:
                continue
            uncovered = model.new_bool_var(
                f"uncovered_d{date_order[value]}_a{agenda_order[agenda_id]}"
            )
            model.add(vacancy == amount).only_enforce_if(uncovered)
            model.add(vacancy <= amount - 1).only_enforce_if(uncovered.Not())
            priority = int(agendas[agenda_id].get("priority", 3))
            uncovered_by_priority[priority].append(uncovered)

        def append_priority_phases(priority: int) -> None:
            priority_vacancies = vacancy_by_priority.get(priority, [])
            if priority_vacancies:
                phases.append(
                    _Phase(
                        f"priority-{priority}-vacancies",
                        sum(priority_vacancies),
                        True,
                    )
                )
            priority_uncovered = uncovered_by_priority.get(priority, [])
            if priority_uncovered:
                phases.append(
                    _Phase(
                        f"priority-{priority}-uncovered-agenda-days",
                        sum(priority_uncovered),
                        True,
                    )
                )

        append_priority_phases(1)

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

        for priority in (2, 3, 4):
            append_priority_phases(priority)

        if partial_days:
            phases.append(
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
                f"partial_assignment_p{member_order[member_id]}"
                f"_d{date_order[value]}_a{agenda_order[agenda_id]}"
            )
            partial_day = partial_days[(member_id, value)]
            model.add(partial_assignment <= assignment)
            model.add(partial_assignment <= partial_day)
            model.add(partial_assignment >= assignment + partial_day - 1)
            priority_weight = 5 - int(agendas[agenda_id].get("priority", 3))
            priority_weighted_partial_assignments.append(
                partial_assignment * priority_weight
            )
        if priority_weighted_partial_assignments:
            phases.append(
                _Phase(
                    "priority-weighted-partial-person-days",
                    sum(priority_weighted_partial_assignments),
                    True,
                )
            )

        if unassigned:
            phases.append(
                _Phase(
                    "unassigned-person-days",
                    sum(unassigned.values()),
                    True,
                )
            )

        share_variables: dict[tuple[str, str], cp_model.IntVar] = {}
        comparable_by_agenda: dict[str, list[str]] = {}
        historical_totals = {
            member_id: sum(int(value) for value in problem.historical_counts.get(member_id, {}).values())
            for member_id in members
        }
        maximum_profile_totals = {
            member_id: 2 * sum(member_id in planifiable[value] for value in planning_dates)
            + historical_totals[member_id]
            for member_id in members
        }
        safe_profile_totals: dict[str, cp_model.IntVar] = {}
        for member_id in members:
            maximum = maximum_profile_totals[member_id]
            total = model.new_int_var(
                historical_totals[member_id],
                maximum,
                f"profile_total_p{member_order[member_id]}",
            )
            model.add(
                total
                == historical_totals[member_id]
                + sum(
                    (
                        assigned_load_units[(member_id, value)]
                        for value in planning_dates
                        if (member_id, value) in assigned_load_units
                    ),
                    0,
                )
            )
            safe_total = model.new_int_var(
                1,
                max(maximum, 1),
                f"safe_profile_total_p{member_order[member_id]}",
            )
            model.add_max_equality(safe_total, [total, 1])
            safe_profile_totals[member_id] = safe_total
        for agenda_id in agendas:
            cohort = [
                member_id
                for member_id, member in members.items()
                if agenda_id in member.get("allowedTypes", [])
                and maximum_profile_totals[member_id] > 0
            ]
            if len(cohort) >= 2:
                comparable_by_agenda[agenda_id] = cohort
        for agenda_id, cohort in comparable_by_agenda.items():
            for member_id in cohort:
                new_count = sum(
                    (
                        assignments[(member_id, value, agenda_id)] * agenda_load_units[agenda_id]
                        for value in planning_dates
                        if (member_id, value, agenda_id) in assignments
                    ),
                    0,
                )
                historical = int(problem.historical_counts.get(member_id, {}).get(agenda_id, 0))
                share = model.new_int_var(
                    0,
                    PERCENT_SCALE,
                    f"share_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
                )
                model.add_division_equality(
                    share,
                    PERCENT_SCALE * (historical + new_count),
                    safe_profile_totals[member_id],
                )
                share_variables[(member_id, agenda_id)] = share

        deviations: dict[tuple[str, str], cp_model.IntVar] = {}
        for agenda_id, cohort in comparable_by_agenda.items():
            for member_id in cohort:
                peer_mean = model.new_int_var(
                    0,
                    PERCENT_SCALE,
                    f"peer_mean_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
                )
                model.add_division_equality(
                    peer_mean,
                    sum(
                        share_variables[(peer_id, agenda_id)]
                        for peer_id in cohort
                        if peer_id != member_id
                    ),
                    len(cohort) - 1,
                )
                deviation = model.new_int_var(
                    0,
                    PERCENT_SCALE,
                    f"deviation_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
                )
                model.add_abs_equality(
                    deviation,
                    share_variables[(member_id, agenda_id)] - peer_mean,
                )
                deviations[(member_id, agenda_id)] = deviation

        person_distances: dict[str, cp_model.IntVar] = {}
        for member_id in members:
            own = [value for (person_id, _agenda_id), value in deviations.items() if person_id == member_id]
            if not own:
                continue
            distance = model.new_int_var(0, PERCENT_SCALE, f"distance_p{member_order[member_id]}")
            model.add_division_equality(distance, sum(own), len(own))
            person_distances[member_id] = distance
        worst_fairness: cp_model.IntVar | None = None
        if person_distances:
            worst_fairness = model.new_int_var(0, PERCENT_SCALE, "worst_fairness_distance")
            model.add_max_equality(worst_fairness, list(person_distances.values()))
        if worst_fairness is not None:
            phases.extend(
                [
                    _Phase("worst-historical-distance", worst_fairness, False),
                    _Phase("total-historical-distance", sum(person_distances.values()), False),
                ]
            )

        if management_assignments:
            non_friday = [
                variable
                for (_member_id, value), variable in management_assignments.items()
                if value.isoweekday() != 5
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

        time_limit = max(float(config.get("timeLimitSeconds", 120)), 0.1)
        workers = max(int(config.get("workers", 1)), 1)
        deadline = monotonic() + time_limit
        phase_metrics: list[dict[str, Any]] = []
        last_solver: cp_model.CpSolver | None = None
        all_phases_optimal = True
        diagnostics: list[str] = []

        if not phases:
            phases.append(_Phase("feasibility", 0, True))

        def retain_solution_as_hint(solver: cp_model.CpSolver) -> None:
            model.clear_hints()  # type: ignore[no-untyped-call]
            for variable_index in range(len(model.proto.variables)):
                variable = model.get_int_var_from_proto_index(variable_index)
                model.add_hint(variable, int(solver.value(variable)))

        for phase_index, phase in enumerate(phases):
            remaining = deadline - monotonic()
            if remaining <= 0:
                if phase.requires_optimum or last_solver is None:
                    return _failure(
                        "SCHEDULER_LIMIT_REACHED",
                        "No s’ha pogut demostrar la prioritat correcta dins del temps disponible",
                        outcome="unknown",
                        diagnostics=[f"Temps esgotat abans de {phase.name}"],
                    )
                all_phases_optimal = False
                diagnostics.append(f"Temps esgotat abans d’optimitzar {phase.name}")
                break
            model.minimize(phase.expression)
            solver = cp_model.CpSolver()
            phase_time_limit = remaining
            if not phase.requires_optimum:
                remaining_phases = len(phases) - phase_index
                phase_time_limit = min(
                    remaining,
                    max(0.05, remaining / remaining_phases),
                )
            solver.parameters.max_time_in_seconds = phase_time_limit
            solver.parameters.num_search_workers = workers
            solver.parameters.random_seed = random_seed
            status = solver.solve(model)
            status_name = solver.status_name(status)
            phase_metric: dict[str, Any] = {
                "name": phase.name,
                "status": status_name,
                "wallTimeSeconds": round(solver.wall_time, 4),
                "conflicts": solver.num_conflicts,
                "branches": solver.num_branches,
            }
            if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
                objective_value = int(solver.value(phase.expression))
                phase_metric.update(
                    {"value": objective_value, "bestBound": round(float(solver.best_objective_bound), 4)}
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

        if last_solver is None:  # pragma: no cover - every valid model has a feasibility phase
            return _failure("SCHEDULER_ERROR", "El planificador no ha retornat cap solució", outcome="unknown")

        result_assignments: list[dict[str, Any]] = []
        for (member_id, value, agenda_id), variable in assignments.items():
            if last_solver.value(variable) != 1:
                continue
            locked_item = locked_by_key.get((member_id, value, agenda_id))
            result_assignments.append(
                {
                    "id": locked_by_key.get((member_id, value, agenda_id), {}).get("id")
                    or uuid4().hex,
                    "date": value.isoformat(),
                    "memberId": member_id,
                    "type": agenda_id,
                    **(
                        {
                            key: locked_item[key]
                            for key in ("locked", "extra", "manuallyModified")
                            if key in locked_item
                        }
                        if locked_item
                        else {}
                    ),
                    **({"fixed": True} if (member_id, value, agenda_id) in fixed_assignments else {}),
                }
            )
        for (member_id, value), variable in management_assignments.items():
            if last_solver.value(variable) != 1:
                continue
            result_assignments.append(
                {
                    "id": locked_by_key.get((member_id, value, "management"), {}).get("id")
                    or uuid4().hex,
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
                    "id": locked_by_key.get((member_id, value, "no_assignment"), {}).get("id")
                    or uuid4().hex,
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
            result_vacancies.extend(
                {"date": value.isoformat(), "type": agenda_id}
                for _ in range(int(last_solver.value(variable)))
            )
        result_vacancies.sort(key=lambda item: (item["date"], agenda_order[item["type"]]))
        daily_unit_values = {
            key: int(last_solver.value(expression))
            for key, expression in daily_load_units.items()
        }
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
                str(priority): sum(int(last_solver.value(value)) for value in variables)
                for priority, variables in vacancy_by_priority.items()
            },
            "management": {
                f"{member_id}:{month}": {
                    "assignments": int(last_solver.value(expression)),
                    "quota": int(members[member_id].get("managementQuota", 0)),
                    "weeklyCap": _management_weekly_cap(
                        int(members[member_id].get("managementQuota", 0)),
                        month,
                    ),
                    "deficit": (
                        int(members[member_id].get("managementQuota", 0))
                        - int(last_solver.value(expression))
                    ),
                    "fridays": sum(
                        int(last_solver.value(variable))
                        for (person_id, value), variable in management_assignments.items()
                        if person_id == member_id
                        and value.strftime("%Y-%m") == month
                        and value.isoweekday() == 5
                    ),
                    "mondays": sum(
                        int(last_solver.value(variable))
                        for (person_id, value), variable in management_assignments.items()
                        if person_id == member_id
                        and value.strftime("%Y-%m") == month
                        and value.isoweekday() == 1
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
        return result


def validate_solution(problem: ScheduleProblem, result: dict[str, Any]) -> list[str]:
    if result.get("outcome") != "solution":
        return []
    planning_dates = _planning_dates(problem)
    demand = _daily_demand(problem, planning_dates)
    members = {item["id"]: item for item in problem.team}
    agendas = {item["id"]: item for item in problem.agendas}
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
        if agenda_id == "management" and int(
            members.get(member_id, {}).get("managementQuota", 0)
        ) <= 0:
            errors.append(f"management not enabled {member_id}:{value}")
        elif agenda_id not in {"no_assignment", "management"} and (
            agenda_id not in agendas
            or agenda_id not in members.get(member_id, {}).get("allowedTypes", [])
        ):
            errors.append(f"invalid capability {member_id}:{agenda_id}")
        if (
            agenda_id in agendas
            and isinstance(member_id, str)
            and isinstance(value, str)
            and _is_telework_day(members.get(member_id, {}), date.fromisoformat(value))
            and not bool(agendas[agenda_id].get("telematic", False))
        ):
            errors.append(f"onsite agenda on telework day {member_id}:{value}:{agenda_id}")
        if agenda_id not in {"no_assignment", "management"}:
            covered[(value, agenda_id)] += 1
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
            errors.append(
                f"management weekly limit exceeded {member_id}:{month}:{iso_year}-W{iso_week}"
            )
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
                member_id
                for member_id in configured_members
                if _is_planifiable(members[member_id], value, problem)
            ]
            required = min(demand.get((value, agenda_id), 0), len(candidates))
            actual = sum(agenda_id in assigned_types.get((member_id, key), set()) for member_id in candidates)
            if actual != required:
                errors.append(f"shared fixed rule mismatch {agenda_id}:{key}:{actual}/{required}")
        for member_id, rule in personal_rules:
            if (
                int(rule["weekday"]) != value.isoweekday()
                or not _is_planifiable(members[member_id], value, problem)
            ):
                continue
            required_ids = list(dict.fromkeys(rule.get("requiredAgendaIds", [])))
            forbidden_ids = list(
                dict.fromkeys(rule.get("forbiddenAgendaIds", []))
            )
            active_required = [
                agenda_id
                for agenda_id in required_ids
                if demand.get((value, agenda_id), 0) > 0
            ]
            assigned = assigned_types.get((member_id, key), set())
            actual_required = sum(
                agenda_id in assigned for agenda_id in active_required
            )
            if (
                rule.get("requiredMode", "all") == "all"
                and actual_required != len(active_required)
            ):
                errors.append(
                    f"personal fixed all mismatch {member_id}:{key}"
                )
            if (
                rule.get("requiredMode", "all") == "one"
                and active_required
                and actual_required != 1
            ):
                errors.append(
                    f"personal fixed one mismatch {member_id}:{key}"
                )
            if any(agenda_id in assigned for agenda_id in forbidden_ids):
                errors.append(
                    f"personal fixed forbidden mismatch {member_id}:{key}"
                )
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
