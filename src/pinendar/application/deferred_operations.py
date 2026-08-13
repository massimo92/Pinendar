from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from ortools.sat.python import cp_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pinendar.application.guard_operations import _planifiable, _telework
from pinendar.application.state import DomainError, bump_revision, month_end, uid
from pinendar.infrastructure.models import (
    Agenda,
    AppSettings,
    Assignment,
    FixedRule,
    FixedRuleAgenda,
    GenerationJob,
    Guard,
    Member,
    MemberCapability,
    Vacancy,
)

PERCENT_SCALE = 10_000
DEFERRED_WINDOW_DAYS = 6


def _assert_revision(session: Session, expected_revision: int | None) -> None:
    settings = session.get(AppSettings, 1)
    if expected_revision is not None and settings and settings.planning_revision != expected_revision:
        raise DomainError(
            "PLANNING_REVISION_CONFLICT",
            "El calendari ha canviat. Torna a revisar la proposta",
            details={
                "expectedRevision": expected_revision,
                "currentRevision": settings.planning_revision,
            },
        )


def _period_end(session: Session, vacancy: Vacancy) -> date:
    job = session.get(GenerationJob, vacancy.generation_job_id) if vacancy.generation_job_id else None
    if job:
        return job.end_date or month_end(job.end_month)
    last_event = session.scalar(select(func.max(Assignment.date)))
    return last_event if isinstance(last_event, date) else vacancy.date


def _solve_phases(
    model: cp_model.CpModel,
    phases: list[Any],
    variables: list[cp_model.IntVar],
) -> cp_model.CpSolver:
    solver: cp_model.CpSolver | None = None
    for expression in phases or [0]:
        model.minimize(expression)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 8
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 1
        status = solver.solve(model)
        if status != cp_model.OPTIMAL:
            raise DomainError(
                "DEFERRED_SUGGESTION_FAILED",
                "No s’ha pogut demostrar una proposta diferida segura",
            )
        optimum = int(solver.value(expression))
        model.add(expression == optimum)
        model.clear_objective()  # type: ignore[no-untyped-call]
        model.clear_hints()  # type: ignore[no-untyped-call]
        for variable in variables:
            model.add_hint(variable, int(solver.value(variable)))
    assert solver is not None
    return solver


def _fairness_context(session: Session) -> dict[str, Any]:
    members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.id)
        )
    )
    agendas = list(
        session.scalars(
            select(Agenda).where(Agenda.archived_at.is_(None)).order_by(Agenda.id)
        )
    )
    loads = {agenda.id: agenda.load_percentage / 100 for agenda in agendas}
    counts = {member.id: {agenda.id: 0.0 for agenda in agendas} for member in members}
    for item in session.scalars(select(Assignment).where(Assignment.agenda_id.is_not(None))):
        if item.member_id in counts and item.agenda_id in loads:
            counts[item.member_id][item.agenda_id] += item.load_percentage / 100
    capabilities = {
        member.id: set(
            session.scalars(
                select(MemberCapability.agenda_id).where(
                    MemberCapability.member_id == member.id
                )
            )
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


def _fairness_score(
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
    totals = {member_id: sum(values.values()) for member_id, values in counts.items()}
    distances: list[float] = []
    for member_id in context["memberIds"]:
        if not totals[member_id]:
            continue
        measured: list[float] = []
        for agenda_id in context["agendaIds"]:
            if agenda_id not in context["capabilities"][member_id]:
                continue
            peers = [
                peer_id
                for peer_id in context["memberIds"]
                if peer_id != member_id
                and totals[peer_id]
                and agenda_id in context["capabilities"][peer_id]
            ]
            if not peers:
                continue
            peer_mean = sum(
                counts[peer_id][agenda_id] / totals[peer_id]
                for peer_id in peers
            ) / len(peers)
            measured.append(
                abs(counts[member_id][agenda_id] / totals[member_id] - peer_mean)
            )
        if measured:
            distances.append(sum(measured) / len(measured))
    return round(max(distances, default=0) * PERCENT_SCALE), round(
        sum(distances) * PERCENT_SCALE
    )


def _fairness_result(
    baseline: tuple[int, int], projected: tuple[int, int]
) -> dict[str, Any]:
    return {
        "fairnessWorstDeltaBasisPoints": baseline[0] - projected[0],
        "fairnessDeltaBasisPoints": baseline[1] - projected[1],
        "fairnessEffect": (
            "improves"
            if projected < baseline
            else "worsens"
            if projected > baseline
            else "neutral"
        ),
    }


def _forbidden_agendas(session: Session, value: date) -> dict[str, set[str]]:
    forbidden: dict[str, set[str]] = defaultdict(set)
    rules = list(
        session.scalars(select(FixedRule).where(FixedRule.weekday == value.isoweekday()))
    )
    for rule in rules:
        for agenda_id in session.scalars(
            select(FixedRuleAgenda.agenda_id).where(
                FixedRuleAgenda.rule_id == rule.id,
                FixedRuleAgenda.effect == "forbidden",
            )
        ):
            forbidden[rule.member_id].add(agenda_id)
    return forbidden


def _solve_target(
    session: Session,
    vacancy: Vacancy,
    target_date: date,
) -> dict[str, Any] | None:
    source_agenda = session.get(Agenda, vacancy.agenda_id)
    if not source_agenda or source_agenda.archived_at or not source_agenda.telematic:
        return None
    rows = list(
        session.scalars(
            select(Assignment)
            .where(Assignment.date == target_date)
            .order_by(Assignment.id)
        )
    )
    if not rows or not any(
        row.kind == "no_assignment" or row.deferred_origin_date for row in rows
    ):
        return None

    guard_specs = [
        {"memberId": item.member_id, "date": item.date}
        for item in session.scalars(select(Guard))
    ]
    represented = {row.member_id for row in rows}
    members = {
        item.id: item
        for item in session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.id)
        )
        if item.id in represented and _planifiable(session, item, target_date, guard_specs)
    }
    if not members:
        return None
    agendas = {
        item.id: item
        for item in session.scalars(
            select(Agenda).where(Agenda.archived_at.is_(None)).order_by(Agenda.id)
        )
    }
    capabilities = {
        member_id: set(
            session.scalars(
                select(MemberCapability.agenda_id).where(
                    MemberCapability.member_id == member_id
                )
            )
        )
        for member_id in members
    }
    forbidden = _forbidden_agendas(session, target_date)
    blocked_members = {
        row.member_id
        for row in rows
        if row.kind == "no_assignment" and (row.locked or row.manually_modified)
    }
    protected = [
        row
        for row in rows
        if row.kind == "management"
        or row.management
        or row.extra
        or row.peonada
        or row.deferred_origin_date
        or row.fixed
        or row.locked
        or row.manually_modified
    ]
    modifiable = [
        row
        for row in rows
        if row.kind == "assigned"
        and row.agenda_id
        and row not in protected
    ]
    required = Counter(row.agenda_id for row in modifiable if row.agenda_id)
    old_by_key = {(row.member_id, row.agenda_id): row for row in modifiable}
    old_no_assignment = {
        row.member_id: row
        for row in rows
        if row.kind == "no_assignment" and row.member_id not in blocked_members
    }
    replaceable = [*modifiable, *old_no_assignment.values()]
    protected_types: dict[str, set[str]] = defaultdict(set)
    protected_units: Counter[str] = Counter()
    for row in protected:
        if row.kind == "no_assignment":
            continue
        protected_units[row.member_id] += row.load_percentage // 50
        if row.agenda_id:
            protected_types[row.member_id].add(row.agenda_id)
    if any(units > 2 for units in protected_units.values()):
        return None

    model = cp_model.CpModel()
    ordinary: dict[tuple[str, str], cp_model.IntVar] = {}
    deferred: dict[str, cp_model.IntVar] = {}
    partial: dict[str, cp_model.IntVar] = {}
    unassigned: dict[str, cp_model.IntVar] = {}
    daily_load: dict[str, Any] = {}
    variables: list[cp_model.IntVar] = []
    for member_id, member in members.items():
        if member_id in blocked_members:
            continue
        telework = _telework(session, member, target_date)
        for agenda_id, amount in required.items():
            agenda = agendas.get(agenda_id)
            if (
                amount
                and agenda
                and agenda_id in capabilities[member_id]
                and agenda_id not in forbidden[member_id]
                and agenda_id not in protected_types[member_id]
                and (not telework or agenda.telematic)
            ):
                variable = model.new_bool_var(f"ordinary_{member_id}_{agenda_id}")
                ordinary[(member_id, agenda_id)] = variable
                variables.append(variable)
        if (
            source_agenda.id in capabilities[member_id]
            and source_agenda.id not in forbidden[member_id]
            and source_agenda.id not in protected_types[member_id]
        ):
            deferred[member_id] = model.new_bool_var(f"deferred_{member_id}")
            variables.append(deferred[member_id])
            duplicate = ordinary.get((member_id, source_agenda.id))
            if duplicate is not None:
                model.add(duplicate + deferred[member_id] <= 1)
        load: Any = protected_units[member_id]
        load += sum(
            variable * (agendas[agenda_id].load_percentage // 50)
            for (person_id, agenda_id), variable in ordinary.items()
            if person_id == member_id
        )
        if member_id in deferred:
            load += deferred[member_id] * (source_agenda.load_percentage // 50)
        daily_load[member_id] = load
        partial[member_id] = model.new_bool_var(f"partial_{member_id}")
        unassigned[member_id] = model.new_bool_var(f"unassigned_{member_id}")
        variables.extend([partial[member_id], unassigned[member_id]])
        model.add(partial[member_id] + unassigned[member_id] <= 1)
        model.add(load == 2 - partial[member_id] - 2 * unassigned[member_id])

    if not deferred:
        return None
    model.add(sum(deferred.values()) == 1)
    for agenda_id, amount in required.items():
        candidates = [
            variable
            for (member_id, candidate_id), variable in ordinary.items()
            if candidate_id == agenda_id
        ]
        if not candidates and amount:
            return None
        model.add(sum(candidates) == amount)

    phases: list[Any] = []
    if partial:
        phases.append(sum(partial.values()))

    active_members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.id)
        )
    )
    all_capabilities = {
        member.id: set(
            session.scalars(
                select(MemberCapability.agenda_id).where(
                    MemberCapability.member_id == member.id
                )
            )
        )
        for member in active_members
    }
    base_counts: dict[str, Counter[str]] = {
        member.id: Counter() for member in active_members
    }
    modifiable_ids = {row.id for row in modifiable}
    for row in session.scalars(select(Assignment).where(Assignment.agenda_id.is_not(None))):
        if row.id not in modifiable_ids and row.member_id in base_counts and row.agenda_id:
            base_counts[row.member_id][row.agenda_id] += row.load_percentage // 50
    share: dict[tuple[str, str], cp_model.IntVar] = {}
    safe_totals: dict[str, cp_model.IntVar] = {}
    member_order = {member.id: index for index, member in enumerate(active_members)}
    agenda_order = {agenda_id: index for index, agenda_id in enumerate(agendas)}
    for member in active_members:
        member_id = member.id
        profile_additions = [
            variable * (agendas[agenda_id].load_percentage // 50)
            for (person_id, agenda_id), variable in ordinary.items()
            if person_id == member_id
        ]
        if member_id in deferred:
            profile_additions.append(deferred[member_id] * (source_agenda.load_percentage // 50))
        base_total = sum(base_counts[member_id].values())
        maximum = base_total + sum(
            agendas[agenda_id].load_percentage // 50
            for person_id, agenda_id in ordinary
            if person_id == member_id
        ) + (source_agenda.load_percentage // 50 if member_id in deferred else 0)
        total = model.new_int_var(base_total, max(base_total, maximum), f"total_{member_order[member_id]}")
        model.add(total == base_total + sum(profile_additions, 0))
        safe = model.new_int_var(1, max(maximum, 1), f"safe_total_{member_order[member_id]}")
        model.add_max_equality(safe, [total, 1])
        safe_totals[member_id] = safe
    comparable = {
        agenda_id: [
            member.id
            for member in active_members
            if agenda_id in all_capabilities[member.id]
            and (sum(base_counts[member.id].values()) > 0 or member.id in members)
        ]
        for agenda_id in agendas
    }
    for agenda_id, cohort in comparable.items():
        if len(cohort) < 2:
            continue
        for member_id in cohort:
            agenda_additions: list[Any] = []
            agenda_variable = ordinary.get((member_id, agenda_id))
            if agenda_variable is not None:
                agenda_additions.append(agenda_variable * (agendas[agenda_id].load_percentage // 50))
            if agenda_id == source_agenda.id and member_id in deferred:
                agenda_additions.append(deferred[member_id] * (source_agenda.load_percentage // 50))
            value = model.new_int_var(0, PERCENT_SCALE, f"share_{member_order[member_id]}_{agenda_order[agenda_id]}")
            model.add_division_equality(
                value,
                PERCENT_SCALE * (base_counts[member_id][agenda_id] + sum(agenda_additions, 0)),
                safe_totals[member_id],
            )
            share[(member_id, agenda_id)] = value
    person_distances: dict[str, cp_model.IntVar] = {}
    for member in active_members:
        member_id = member.id
        deviations: list[cp_model.IntVar] = []
        for agenda_id, cohort in comparable.items():
            if member_id not in cohort or len(cohort) < 2:
                continue
            peer_mean = model.new_int_var(0, PERCENT_SCALE, f"peer_{member_order[member_id]}_{agenda_order[agenda_id]}")
            model.add_division_equality(
                peer_mean,
                sum(share[(peer_id, agenda_id)] for peer_id in cohort if peer_id != member_id),
                len(cohort) - 1,
            )
            deviation = model.new_int_var(0, PERCENT_SCALE, f"deviation_{member_order[member_id]}_{agenda_order[agenda_id]}")
            model.add_abs_equality(deviation, share[(member_id, agenda_id)] - peer_mean)
            deviations.append(deviation)
        if deviations:
            distance = model.new_int_var(0, PERCENT_SCALE, f"distance_{member_order[member_id]}")
            model.add_division_equality(distance, sum(deviations), len(deviations))
            person_distances[member_id] = distance
    if person_distances:
        worst = model.new_int_var(0, PERCENT_SCALE, "worst_distance")
        model.add_max_equality(worst, list(person_distances.values()))
        phases.extend([worst, sum(person_distances.values())])

    changes: list[Any] = [
        1 - variable if key in old_by_key else variable
        for key, variable in ordinary.items()
    ]
    if changes:
        phases.append(sum(changes))
    phases.append(
        sum(
            variable * (index + 1)
            for index, variable in enumerate(sorted(variables, key=lambda item: item.name))
        )
    )
    solver = _solve_phases(model, phases, variables)

    selected = {
        key for key, variable in ordinary.items() if solver.value(variable) == 1
    }
    deferred_member_id = next(
        member_id for member_id, variable in deferred.items() if solver.value(variable) == 1
    )
    removed: dict[str, list[Assignment]] = defaultdict(list)
    added: dict[str, list[str]] = defaultdict(list)
    for row in modifiable:
        if (row.member_id, row.agenda_id) not in selected and row.agenda_id:
            removed[row.agenda_id].append(row)
    for member_id, agenda_id in selected:
        if (member_id, agenda_id) not in old_by_key:
            added[agenda_id].append(member_id)
    movements: list[dict[str, Any]] = []
    for agenda_id in sorted(set(removed) | set(added)):
        sources = sorted(removed[agenda_id], key=lambda row: (row.member_id, row.id))
        targets = sorted(added[agenda_id])
        movements.extend(
            {
                "agendaId": agenda_id,
                "fromMemberId": source.member_id,
                "toMemberId": target,
            }
            for source, target in zip(sources, targets, strict=True)
        )

    fairness_context = _fairness_context(session)
    baseline = _fairness_score(fairness_context, [])
    fairness_changes: list[tuple[str, str | None, str | None]] = []
    for movement in movements:
        fairness_changes.extend(
            [
                (movement["fromMemberId"], movement["agendaId"], None),
                (movement["toMemberId"], None, movement["agendaId"]),
            ]
        )
    fairness_changes.append((deferred_member_id, None, source_agenda.id))
    projected = _fairness_score(fairness_context, fairness_changes)

    desired_assignments = [
        {
            "id": old_by_key[key].id if key in old_by_key else uid(),
            "memberId": key[0],
            "agendaId": key[1],
            "kind": "assigned",
            "unchanged": key in old_by_key,
        }
        for key in sorted(selected)
    ]
    desired_no_assignment = [
        {
            "id": old_no_assignment[member_id].id if member_id in old_no_assignment else uid(),
            "memberId": member_id,
            "unchanged": member_id in old_no_assignment,
        }
        for member_id, variable in unassigned.items()
        if solver.value(variable) == 1
    ]
    return {
        "targetDate": target_date.isoformat(),
        "deferredMemberId": deferred_member_id,
        "movements": movements,
        "changeCount": len(movements),
        **_fairness_result(baseline, projected),
        "_replaceable": replaceable,
        "_desiredAssignments": desired_assignments,
        "_desiredNoAssignment": desired_no_assignment,
    }


def deferred_vacancy_options(session: Session, vacancy_id: int) -> dict[str, Any]:
    vacancy = session.get(Vacancy, vacancy_id)
    if not vacancy:
        raise DomainError("VACANCY_NOT_FOUND", "Vacant no trobada")
    agenda = session.get(Agenda, vacancy.agenda_id)
    settings = session.get(AppSettings, 1)
    options: list[dict[str, Any]] = []
    if agenda and agenda.telematic:
        end = min(vacancy.date + timedelta(days=DEFERRED_WINDOW_DAYS), _period_end(session, vacancy))
        current = vacancy.date + timedelta(days=1)
        while current <= end:
            try:
                option = _solve_target(session, vacancy, current)
            except DomainError as error:
                if error.code != "DEFERRED_SUGGESTION_FAILED":
                    raise
                option = None
            if option:
                options.append({key: value for key, value in option.items() if not key.startswith("_")})
            current += timedelta(days=1)
    return {
        "vacancyId": vacancy.id,
        "agendaId": vacancy.agenda_id,
        "originDate": vacancy.date.isoformat(),
        "planningRevision": settings.planning_revision if settings else 0,
        "options": options,
    }


def apply_deferred_vacancy(
    session: Session,
    vacancy_id: int,
    target_date: date,
    *,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    _assert_revision(session, expected_revision)
    vacancy = session.get(Vacancy, vacancy_id)
    if not vacancy:
        raise DomainError("VACANCY_NOT_FOUND", "Vacant no trobada")
    if not vacancy.date < target_date <= vacancy.date + timedelta(days=DEFERRED_WINDOW_DAYS):
        raise DomainError("INVALID_DEFERRED_DATE", "La data diferida no és vàlida")
    if target_date > _period_end(session, vacancy):
        raise DomainError("INVALID_DEFERRED_DATE", "La data queda fora del calendari generat")
    proposal = _solve_target(session, vacancy, target_date)
    if proposal is None:
        raise DomainError(
            "DEFERRED_OPTION_STALE",
            "La proposta diferida ja no està disponible",
        )
    agenda = session.get(Agenda, vacancy.agenda_id)
    if not agenda:
        raise DomainError("AGENDA_NOT_FOUND", "Agenda no trobada")

    existing = {row.id: row for row in proposal["_replaceable"]}
    desired = [
        *proposal["_desiredAssignments"],
        *proposal["_desiredNoAssignment"],
    ]
    desired_ids = {item["id"] for item in desired}
    for row_id, row in existing.items():
        if row_id not in desired_ids:
            session.delete(row)
    fallback_job_id = next(
        (row.generation_job_id for row in existing.values() if row.generation_job_id),
        vacancy.generation_job_id,
    )
    for item in proposal["_desiredAssignments"]:
        row = existing.get(item["id"])
        if row is None:
            row = Assignment(id=item["id"], date=target_date, member_id=item["memberId"])
            session.add(row)
        row.generation_job_id = row.generation_job_id or fallback_job_id
        row.member_id = item["memberId"]
        row.agenda_id = item["agendaId"]
        row.kind = "assigned"
        row.load_percentage = session.get(Agenda, item["agendaId"]).load_percentage  # type: ignore[union-attr]
        row.locked = row.locked if item["unchanged"] else True
        row.fixed = False
        row.extra = False
        row.peonada = False
        row.deferred_origin_date = None
        row.manually_modified = row.manually_modified if item["unchanged"] else True
        row.management = False
    for item in proposal["_desiredNoAssignment"]:
        row = existing.get(item["id"])
        if row is None:
            row = Assignment(id=item["id"], date=target_date, member_id=item["memberId"])
            session.add(row)
        row.generation_job_id = row.generation_job_id or fallback_job_id
        row.member_id = item["memberId"]
        row.agenda_id = None
        row.kind = "no_assignment"
        row.load_percentage = 0
        row.locked = row.locked if item["unchanged"] else True
        row.fixed = False
        row.extra = False
        row.peonada = False
        row.deferred_origin_date = None
        row.manually_modified = row.manually_modified if item["unchanged"] else True
        row.management = False

    deferred = Assignment(
        id=uid(),
        generation_job_id=vacancy.generation_job_id or fallback_job_id,
        date=target_date,
        member_id=proposal["deferredMemberId"],
        agenda_id=agenda.id,
        kind="assigned",
        load_percentage=agenda.load_percentage,
        locked=True,
        fixed=False,
        extra=False,
        peonada=False,
        deferred_origin_date=vacancy.date,
        manually_modified=True,
        management=False,
    )
    session.add(deferred)
    session.delete(vacancy)
    bump_revision(session)
    assert deferred.deferred_origin_date is not None
    return {
        "id": deferred.id,
        "date": deferred.date.isoformat(),
        "originDate": deferred.deferred_origin_date.isoformat(),
        "memberId": deferred.member_id,
        "agendaId": deferred.agenda_id,
        "movements": proposal["movements"],
        "fairnessEffect": proposal["fairnessEffect"],
    }
