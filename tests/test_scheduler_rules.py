from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from multiprocessing import get_context
from time import monotonic
from typing import Any

import pytest

from pinendar.domain.scheduler import ScheduleProblem
from pinendar.infrastructure.cp_sat_scheduler import (
    CpSatScheduler,
    _Phase,
    _phase_time_budget,
    _polish_solution,
    _polishing_reserve,
    solve_snapshot,
    validate_solution,
)


def agenda(
    agenda_id: str,
    *,
    priority: int = 3,
    telematic: bool = False,
    load_percentage: int = 100,
    recurrences: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    return {
        "id": agenda_id,
        "priority": priority,
        "telematic": telematic,
        "loadPercentage": load_percentage,
        "recurrences": recurrences or [],
    }


def member(
    member_id: str,
    allowed: list[str],
    *,
    available: list[int] | None = None,
    tele: list[int] | None = None,
    fixed: list[dict[str, Any]] | None = None,
    absences: list[dict[str, str]] | None = None,
    quota: int = 0,
    work_pattern: dict[str, Any] | None = None,
    preferences: dict[str, int] | None = None,
) -> dict[str, Any]:
    value = {
        "id": member_id,
        "availableDays": available or [1],
        "teleDays": tele or [],
        "allowedTypes": allowed,
        "fixedRules": fixed or [],
        "absences": absences or [],
        "managementQuota": quota,
        "agendaPreferences": preferences or {},
    }
    if work_pattern:
        value["workPattern"] = work_pattern
    return value


def problem(
    agendas: list[dict[str, Any]],
    team: list[dict[str, Any]],
    coverage: dict[str, dict[str, int]],
    *,
    holidays: list[str] | None = None,
    guards: list[dict[str, str]] | None = None,
    conditions: dict[str, list[dict[str, Any]]] | None = None,
    historical: dict[str, dict[str, int]] | None = None,
    historical_telematic_days: dict[str, int] | None = None,
    historical_assigned_days: dict[str, int] | None = None,
    optimization_mode: str = "fairness",
    schema_version: int = 2,
    start_month: str = "2027-01",
    end_month: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    first_generation_member_ids: list[str] | None = None,
) -> ScheduleProblem:
    return ScheduleProblem(
        schema_version=schema_version,
        planning_revision=1,
        start_month=start_month,
        end_month=end_month or start_month,
        team=team,
        agendas=agendas,
        coverage={str(day): coverage.get(str(day), {}) for day in range(1, 6)},
        holidays=holidays or [],
        guards=guards or [],
        conditions=conditions or {"guards": [], "absences": []},
        historical_counts=historical
        or {item["id"]: {entry["id"]: 0 for entry in agendas} for item in team},
        locked_assignments=[],
        historical_telematic_days=historical_telematic_days or {},
        historical_assigned_days=historical_assigned_days or {},
        first_generation_member_ids=first_generation_member_ids or [],
        start_date=start_date,
        end_date=end_date,
        solver_config={
            "timeLimitSeconds": 5,
            "workers": 1,
            "randomSeed": 1,
            "optimizationMode": optimization_mode,
        },
    )


def test_solver_prioritizes_time_for_fairness_phases() -> None:
    phases = [
        _Phase("worst-historical-distance", 0, False),
        _Phase("total-historical-distance", 0, False),
        _Phase("consecutive-clinical-agendas", 0, False),
        _Phase("management-fridays", 0, False),
    ]

    assert _phase_time_budget(phases, 0, 120) == pytest.approx(72)
    assert _phase_time_budget(phases, 1, 48) == pytest.approx(36)
    assert _phase_time_budget(phases, 2, 12) == pytest.approx(10.8)
    assert _phase_time_budget(phases, 3, 1.2) == pytest.approx(1.2)


def test_final_phase_share_is_split_between_all_final_adjustments() -> None:
    phases = [
        _Phase("worst-historical-distance", 0, False),
        _Phase("total-historical-distance", 0, False),
        _Phase("consecutive-clinical-agendas", 0, False),
        _Phase("management-low-vacancy-days", 0, False),
        _Phase("management-fridays", 0, False),
        _Phase("management-mondays", 0, False),
    ]

    assert _phase_time_budget(phases, 0, 900) == pytest.approx(540)
    assert _phase_time_budget(phases, 1, 360) == pytest.approx(270)
    assert _phase_time_budget(phases, 2, 90) == pytest.approx(81)
    assert _phase_time_budget(phases, 3, 9) == pytest.approx(3)


@pytest.mark.parametrize(
    ("time_limit", "expected"),
    [(60, 3), (120, 6), (300, 15), (900, 45), (1800, 90)],
)
def test_polishing_reserves_five_percent_of_generation_time(
    time_limit: float,
    expected: float,
) -> None:
    assert _polishing_reserve(time_limit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("telematic", "modality"),
    [(False, "onsite"), (True, "telematic")],
)
def test_scheduler_covers_higher_priority_agenda_first(
    telematic: bool,
    modality: str,
) -> None:
    agendas = [
        agenda("lower", priority=4, telematic=telematic),
        agenda("higher", priority=1, telematic=telematic),
    ]
    team = [member("member-1", ["lower", "higher"])]
    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"lower": 1, "higher": 1}}))

    assert result.outcome == "solution"
    assert [phase["name"] for phase in result.metrics["phases"][:2]] == [
        f"{modality}-priority-1-vacancies",
        f"{modality}-priority-1-uncovered-agenda-days",
    ]
    monday_assignments = [
        item for item in result.assignments
        if item["date"] == "2027-01-04" and item["type"] != "no_assignment"
    ]
    monday_vacancies = [
        item for item in result.vacancies if item["date"] == "2027-01-04"
    ]
    assert [item["type"] for item in monday_assignments] == ["higher"]
    assert [item["type"] for item in monday_vacancies] == ["lower"]


def test_scheduler_covers_onsite_before_higher_priority_telematic() -> None:
    agendas = [
        agenda("onsite", priority=4),
        agenda("remote", priority=1, telematic=True),
    ]
    team = [member("member-1", ["onsite", "remote"])]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"onsite": 1, "remote": 1}},
            start_date="2027-01-04",
            end_date="2027-01-04",
        )
    )

    assert result.outcome == "solution"
    assert [phase["name"] for phase in result.metrics["phases"][:2]] == [
        "onsite-priority-4-vacancies",
        "onsite-priority-4-uncovered-agenda-days",
    ]
    assert [item["type"] for item in result.assignments] == ["onsite"]
    assert result.vacancies == [{"date": "2027-01-04", "type": "remote"}]


def test_locked_deferred_assignment_covers_its_origin_demand() -> None:
    agendas = [agenda("remote", priority=1, telematic=True)]
    team = [member("member-1", ["remote"], available=[1, 2])]
    base = problem(
        agendas,
        team,
        {"1": {"remote": 1}},
        schema_version=8,
    )
    snapshot = {
        **base.to_dict(),
        "start_date": "2027-01-04",
        "end_date": "2027-01-05",
        "locked_assignments": [
            {
                "id": "deferred-locked",
                "date": "2027-01-05",
                "memberId": "member-1",
                "type": "remote",
                "locked": True,
                "manuallyModified": True,
                "deferredOriginDate": "2027-01-04",
            }
        ],
    }

    result = CpSatScheduler().solve(ScheduleProblem.from_dict(snapshot))

    assert result.outcome == "solution", result.error
    assert result.vacancies == []
    assert next(
        item for item in result.assignments if item["id"] == "deferred-locked"
    )["deferredOriginDate"] == "2027-01-04"


def test_scheduler_assigns_a_telematic_vacancy_as_deferred_on_a_later_free_day() -> None:
    agendas = [agenda("remote", priority=1, telematic=True)]
    team = [member("person", ["remote"], available=[2])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"remote": 1}},
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    assert result.outcome == "solution"
    assert result.vacancies == []
    assert result.metrics["automaticDeferred"] == {
        "assigned": 1,
        "byMember": {"person": 1},
        "remainingTelematicVacancies": 0,
    }
    assert result.assignments == [
        {
            "id": result.assignments[0]["id"],
            "date": "2027-01-05",
            "memberId": "person",
            "type": "remote",
            "deferredOriginDate": "2027-01-04",
        }
    ]
    phase_names = [phase["name"] for phase in result.metrics["phases"]]
    assert phase_names.index("automatic-deferred-priority-1-coverage") < phase_names.index(
        "operational-fairness-polishing"
    )


def test_automatic_deferred_coverage_preserves_original_agenda_priority() -> None:
    agendas = [
        agenda("urgent-remote", priority=1, telematic=True),
        agenda("low-remote", priority=4, telematic=True),
    ]
    team = [member("person", ["urgent-remote", "low-remote"], available=[2])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"urgent-remote": 1, "low-remote": 1}},
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    deferred = next(item for item in result.assignments if item.get("deferredOriginDate"))
    phase_names = [phase["name"] for phase in result.metrics["phases"]]
    assert result.outcome == "solution"
    assert deferred["type"] == "urgent-remote"
    assert result.vacancies == [{"date": "2027-01-04", "type": "low-remote"}]
    assert phase_names.index("automatic-deferred-priority-1-coverage") < phase_names.index(
        "automatic-deferred-priority-4-coverage"
    )


def test_scheduler_keeps_a_half_day_deferred_assignment_within_capacity() -> None:
    agendas = [agenda("remote-half", priority=1, telematic=True, load_percentage=50)]
    team = [member("person", ["remote-half"], available=[2])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"remote-half": 1}},
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    assert result.outcome == "solution"
    assert result.vacancies == []
    assert [item["deferredOriginDate"] for item in result.assignments] == ["2027-01-04"]
    assert result.metrics["partial"]["count"] == 1


def test_deferred_telematic_slot_keeps_a_guard_day_onsite_when_combined_with_half_day() -> None:
    agendas = [
        agenda("remote-half", priority=1, telematic=True, load_percentage=50),
        agenda("onsite-half", priority=1, load_percentage=50),
    ]
    team = [member("guard", ["remote-half", "onsite-half"], available=[2])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"remote-half": 1}, "2": {"onsite-half": 1}},
            guards=[{"memberId": "guard", "date": "2027-01-05"}],
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    assert result.outcome == "solution"
    target_assignments = [item for item in result.assignments if item["date"] == "2027-01-05"]
    assert {item["type"] for item in target_assignments} == {"remote-half", "onsite-half"}
    assert next(item for item in target_assignments if item["type"] == "remote-half")["deferredOriginDate"] == "2027-01-04"
    assert next(phase for phase in result.metrics["phases"] if phase["name"] == "guard-onsite-days")["value"] == 0


def test_scheduler_does_not_defer_into_a_day_with_the_same_normal_demand() -> None:
    agendas = [agenda("remote", priority=1, telematic=True)]
    team = [member("person", ["remote"], available=[2])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"remote": 1}, "2": {"remote": 1}},
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    assert result.outcome == "solution"
    assert result.metrics["automaticDeferred"]["assigned"] == 0
    assert len(result.vacancies) == 1


def test_scheduler_adds_nth_working_weekday_recurrence() -> None:
    agendas = [agenda("periodic", priority=1, recurrences=[{"ordinal": 3, "weekday": 1, "slots": 1}])]
    result = CpSatScheduler().solve(problem(agendas, [], {}))

    assert result.outcome == "solution"
    assert any(item["date"] == "2027-01-18" and item["type"] == "periodic" for item in result.vacancies)
    assert not any(item["date"] == "2027-01-11" for item in result.vacancies)


def test_fixed_rule_only_applies_when_monthly_recurring_demand_exists() -> None:
    agendas = [
        agenda(
            "periodic",
            priority=1,
            recurrences=[{"ordinal": 3, "weekday": 3, "slots": 1}],
        )
    ]
    team = [
        member(
            "member-1",
            ["periodic"],
            available=[3],
            fixed=[{"weekday": 3, "type": "periodic"}],
        )
    ]

    result = CpSatScheduler().solve(problem(agendas, team, {}))

    assert result.outcome == "solution"
    assert [
        (item["date"], item["type"], item["fixed"])
        for item in result.assignments
        if item["type"] != "no_assignment"
    ] == [("2027-01-20", "periodic", True)]


def test_guard_creates_post_guard_absence_on_next_natural_day() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [member("member-1", ["clinical"])]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"clinical": 1}},
            guards=[{"memberId": "member-1", "date": "2027-01-03"}],
        )
    )

    assert result.outcome == "solution"
    assert {item["date"] for item in result.vacancies} == {"2027-01-04"}
    assert any(item["date"] == "2027-01-11" for item in result.assignments)


def test_each_guard_on_the_same_date_creates_its_own_post_guard_absence() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [
        member("member-1", ["clinical"]),
        member("member-2", ["clinical"]),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"clinical": 2}},
            guards=[
                {"memberId": "member-1", "date": "2027-01-03"},
                {"memberId": "member-2", "date": "2027-01-03"},
            ],
        )
    )

    assert result.outcome == "solution"
    assert [
        item for item in result.vacancies if item["date"] == "2027-01-04"
    ] == [
        {"date": "2027-01-04", "type": "clinical"},
        {"date": "2027-01-04", "type": "clinical"},
    ]


def test_guard_prefers_onsite_agenda_even_on_configured_telework_day() -> None:
    agendas = [agenda("onsite", priority=1), agenda("remote", priority=1, telematic=True)]
    team = [
        member("guarded", ["onsite", "remote"], tele=[1]),
        member("peer", ["onsite", "remote"]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"onsite": 1, "remote": 1}},
            guards=[{"memberId": "guarded", "date": "2027-01-04"}],
        )
    )

    guarded = [item for item in result.assignments if item["memberId"] == "guarded"]
    assert result.outcome == "solution"
    assert [item["type"] for item in guarded if item["date"] == "2027-01-04"] == ["onsite"]
    assert next(
        phase for phase in result.metrics["phases"] if phase["name"] == "guard-onsite-days"
    )["value"] == 0


def test_guard_falls_back_to_telematic_when_no_onsite_agenda_is_possible() -> None:
    agendas = [agenda("remote", priority=1, telematic=True)]
    team = [member("guarded", ["remote"], tele=[1])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"remote": 1}},
            guards=[{"memberId": "guarded", "date": "2027-01-04"}],
        )
    )

    assert result.outcome == "solution"
    assert any(item["type"] == "remote" for item in result.assignments)
    assert next(
        phase for phase in result.metrics["phases"] if phase["name"] == "guard-onsite-days"
    )["value"] == 1


def test_telematic_days_are_spread_evenly_between_members() -> None:
    agendas = [agenda("onsite", priority=1), agenda("remote", priority=1, telematic=True)]
    team = [
        member("person-1", ["onsite", "remote"]),
        member("person-2", ["onsite", "remote"]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"onsite": 1, "remote": 1}},
            start_date="2027-01-04",
            end_date="2027-01-11",
        )
    )

    assert result.outcome == "solution"
    assert result.metrics["telematicBalance"]["telematicAssignmentsByMember"] == {
        "person-1": 1.0,
        "person-2": 1.0,
    }
    assert result.metrics["telematicBalance"]["percentageByMember"] == {
        "person-1": 50.0,
        "person-2": 50.0,
    }
    assert result.metrics["telematicBalance"]["rangePercentagePoints"] == 0.0
    phase_names = [phase["name"] for phase in result.metrics["phases"]]
    assert phase_names.index("telematic-percentage-range") < phase_names.index(
        "worst-historical-distance"
    )
    assert phase_names[-2:] == [
        "operational-fairness-polishing",
        "telematic-percentage-polishing",
    ]


def test_telematic_balance_uses_percentages_not_absolute_assignment_counts() -> None:
    agendas = [
        agenda("onsite", priority=1),
        agenda("remote", priority=1, telematic=True),
    ]
    team = [
        member("short-week", ["onsite", "remote"], available=[1]),
        member("long-week", ["onsite", "remote"], available=[1, 2]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {
                "1": {"onsite": 1, "remote": 1},
                "2": {"onsite": 1},
            },
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    assert result.outcome == "solution"
    remote = next(item for item in result.assignments if item["type"] == "remote")
    assert remote["memberId"] == "long-week"
    assert result.metrics["telematicBalance"]["percentageByMember"] == {
        "short-week": 0.0,
        "long-week": 50.0,
    }
    assert result.metrics["telematicBalance"]["rangePercentagePoints"] == 50.0


def test_telematic_balance_combines_historical_days_with_new_schedule() -> None:
    agendas = [
        agenda("onsite", priority=1),
        agenda("remote", priority=1, telematic=True),
    ]
    team = [
        member("historically-remote", ["onsite", "remote"]),
        member("historically-onsite", ["onsite", "remote"]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"onsite": 1, "remote": 1}},
            start_date="2027-01-04",
            end_date="2027-01-04",
            historical_telematic_days={
                "historically-remote": 8,
                "historically-onsite": 2,
            },
            historical_assigned_days={
                "historically-remote": 10,
                "historically-onsite": 10,
            },
        )
    )

    assignments = {item["memberId"]: item["type"] for item in result.assignments}
    assert result.outcome == "solution"
    assert assignments == {
        "historically-remote": "onsite",
        "historically-onsite": "remote",
    }
    assert result.metrics["telematicBalance"]["telematicDaysByMember"] == {
        "historically-remote": 8,
        "historically-onsite": 3,
    }
    assert result.metrics["telematicBalance"]["totalAssignedDaysByMember"] == {
        "historically-remote": 11,
        "historically-onsite": 11,
    }


def test_onsite_half_day_makes_the_whole_assigned_day_onsite() -> None:
    agendas = [
        agenda("onsite-half", priority=1, load_percentage=50),
        agenda("remote-half", priority=1, telematic=True, load_percentage=50),
    ]
    team = [
        member("mixed", ["onsite-half", "remote-half"]),
        member("remote", ["remote-half"]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"onsite-half": 1, "remote-half": 3}},
            start_date="2027-01-04",
            end_date="2027-01-04",
        )
    )

    assert result.outcome == "solution"
    assert result.metrics["telematicBalance"]["telematicAssignmentsByMember"] == {
        "mixed": 0,
        "remote": 1,
    }
    assert result.metrics["telematicBalance"]["telematicDaysByMember"] == {
        "mixed": 0,
        "remote": 1,
    }
    assert result.metrics["telematicBalance"]["totalAssignedDaysByMember"] == {
        "mixed": 1,
        "remote": 1,
    }
    assert result.metrics["telematicBalance"]["percentageByMember"] == {
        "mixed": 0.0,
        "remote": 100.0,
    }


def test_management_counts_as_a_full_telematic_day() -> None:
    team = [member("manager", [], quota=1), member("peer", [])]

    result = CpSatScheduler().solve(
        problem(
            [],
            team,
            {},
            start_date="2027-01-04",
            end_date="2027-01-04",
        )
    )

    assert result.outcome == "solution"
    assert result.metrics["telematicBalance"]["telematicAssignmentsByMember"] == {
        "manager": 1,
        "peer": 0,
    }
    assert result.metrics["telematicBalance"]["percentageByMember"] == {
        "manager": 100.0,
        "peer": None,
    }


def test_scheduler_repeats_member_work_pattern_weeks() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [
        member(
            "member-1",
            ["clinical"],
            work_pattern={
                "weeks": [
                    {"workingDays": [1, 2, 3], "teleDays": []},
                    {"workingDays": [1, 2, 3, 4], "teleDays": []},
                ],
            },
        )
    ]
    result = CpSatScheduler().solve(problem(agendas, team, {"4": {"clinical": 1}}))

    thursday_assignments = {
        item["date"] for item in result.assignments if item["type"] == "clinical"
    }
    thursday_vacancies = {
        item["date"] for item in result.vacancies if item["type"] == "clinical"
    }
    assert thursday_assignments == {"2027-01-14", "2027-01-28"}
    assert thursday_vacancies == {"2027-01-07", "2027-01-21"}


def test_explicit_absence_blocks_assignments() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [
        member(
            "member-1",
            ["clinical"],
            absences=[{"start": "2027-01-11", "end": "2027-01-18"}],
        )
    ]
    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"clinical": 1}}))

    assert result.outcome == "solution"
    assert {item["date"] for item in result.vacancies} == {"2027-01-11", "2027-01-18"}


def test_excess_people_creates_no_assignment_events() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [member("member-1", ["clinical"]), member("member-2", ["clinical"])]
    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"clinical": 1}}))

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert Counter(item["type"] for item in monday) == Counter({"clinical": 1, "no_assignment": 1})
    assert result.metrics["unassigned"]["people"] == 2


def test_half_agendas_fill_one_person_with_two_assignments() -> None:
    agendas = [
        agenda("half-a", priority=1, load_percentage=50),
        agenda("half-b", priority=1, load_percentage=50),
    ]
    team = [member("member-1", ["half-a", "half-b"])]

    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {"half-a": 1, "half-b": 1}})
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["type"] for item in monday} == {"half-a", "half-b"}


def test_half_agenda_alone_is_assigned_as_an_exceptional_partial_day() -> None:
    agendas = [agenda("half", priority=1, load_percentage=50)]
    team = [member("member-1", ["half"])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"half": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert [item["type"] for item in monday] == ["half"]
    assert not result.vacancies
    assert result.metrics["partial"]["count"] == 1
    assert result.metrics["unassigned"]["count"] == 0


def test_two_half_agendas_stay_together_instead_of_creating_two_partial_days() -> None:
    agendas = [
        agenda("half-a", priority=1, load_percentage=50),
        agenda("half-b", priority=1, load_percentage=50),
    ]
    team = [
        member("member-1", ["half-a", "half-b"]),
        member("member-2", ["half-a", "half-b"]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"half-a": 1, "half-b": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    clinical = [item for item in monday if item["type"] != "no_assignment"]
    assert result.outcome == "solution"
    assert len({item["memberId"] for item in clinical}) == 1
    assert Counter(item["type"] for item in clinical) == Counter({"half-a": 1, "half-b": 1})
    assert result.metrics["partial"]["count"] == 0
    assert result.metrics["unassigned"]["count"] == 1


def test_two_slots_of_the_same_half_agenda_require_distinct_people() -> None:
    agendas = [
        agenda("committee", priority=1, load_percentage=50),
        agenda("complement", priority=4, load_percentage=50),
    ]
    team = [member("member-1", ["committee", "complement"])]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"committee": 2, "complement": 1}},
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert Counter(item["type"] for item in monday) == Counter(
        {"committee": 1, "complement": 1}
    )
    assert Counter(
        item["type"] for item in result.vacancies if item["date"] == "2027-01-04"
    ) == Counter({"committee": 1})


def test_unavailable_people_do_not_appear_as_unassigned() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [member("member-1", ["clinical"], available=[2])]

    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"clinical": 1}}))

    assert result.outcome == "solution"
    assert not any(
        item["memberId"] == "member-1"
        and item["date"] == "2027-01-04"
        for item in result.assignments
    )


def test_half_fixed_rule_requires_a_second_half_agenda() -> None:
    agendas = [
        agenda("fixed-half", priority=4, load_percentage=50),
        agenda("other-half", priority=1, load_percentage=50),
    ]
    team = [
        member(
            "member-1",
            ["fixed-half", "other-half"],
            fixed=[{"weekday": 1, "type": "fixed-half"}],
        )
    ]

    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {"fixed-half": 1, "other-half": 1}})
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["type"] for item in monday} == {"fixed-half", "other-half"}
    assert next(item for item in monday if item["type"] == "fixed-half")["fixed"] is True


def test_fixed_rule_is_mandatory_when_member_is_planifiable() -> None:
    agendas = [agenda("fixed", priority=4), agenda("other", priority=1)]
    team = [
        member(
            "member-1",
            ["fixed", "other"],
            fixed=[{"weekday": 1, "type": "fixed"}],
        )
    ]
    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"fixed": 1, "other": 1}}))

    monday = next(item for item in result.assignments if item["date"] == "2027-01-04")
    assert monday["type"] == "fixed"
    assert monday["fixed"] is True


def test_shared_fixed_rule_uses_all_available_holders_up_to_demand() -> None:
    agendas = [agenda("shared", priority=1)]
    team = [
        member("jorge", ["shared"], fixed=[{"weekday": 1, "type": "shared"}]),
        member("laura", ["shared"], fixed=[{"weekday": 1, "type": "shared"}]),
        member("other", ["shared"]),
    ]

    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"shared": 3}}))

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["memberId"] for item in monday} == {"jorge", "laura", "other"}
    assert {item["memberId"] for item in monday if item.get("fixed")} == {"jorge", "laura"}
    assert result.metrics["randomSeed"] == 1


def test_shared_fixed_rule_selects_only_as_many_holders_as_slots() -> None:
    agendas = [agenda("shared", priority=1)]
    team = [
        member("jorge", ["shared"], fixed=[{"weekday": 1, "type": "shared"}]),
        member("laura", ["shared"], fixed=[{"weekday": 1, "type": "shared"}]),
    ]

    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"shared": 1}}))

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert len([item for item in monday if item["type"] == "shared"]) == 1
    assert len([item for item in monday if item.get("fixed")]) == 1


def test_absent_shared_rule_holder_is_replaced_normally() -> None:
    agendas = [agenda("shared", priority=1)]
    team = [
        member("jorge", ["shared"], fixed=[{"weekday": 1, "type": "shared"}]),
        member(
            "laura",
            ["shared"],
            fixed=[{"weekday": 1, "type": "shared"}],
            absences=[{"start": "2027-01-01", "end": "2027-01-31"}],
        ),
        member("substitute", ["shared"]),
    ]

    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"shared": 2}}))

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["memberId"] for item in monday} == {"jorge", "substitute"}
    assert next(item for item in monday if item["memberId"] == "jorge")["fixed"] is True
    assert not next(item for item in monday if item["memberId"] == "substitute").get("fixed")


def test_personal_fixed_all_requires_every_partial_agenda() -> None:
    agendas = [
        agenda("partial-a", priority=1, load_percentage=50),
        agenda("partial-b", priority=1, load_percentage=50),
        agenda("other", priority=1),
    ]
    team = [
        member(
            "member-1",
            ["partial-a", "partial-b", "other"],
            fixed=[
                {
                    "weekday": 1,
                    "requiredMode": "all",
                    "requiredAgendaIds": ["partial-a", "partial-b"],
                    "forbiddenAgendaIds": [],
                }
            ],
        )
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"partial-a": 1, "partial-b": 1, "other": 1}},
            schema_version=7,
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["type"] for item in monday} == {"partial-a", "partial-b"}
    assert all(item["fixed"] for item in monday)


def test_personal_fixed_one_requires_exactly_one_alternative() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    team = [
        member(
            "member-1",
            ["a", "b"],
            fixed=[
                {
                    "weekday": 1,
                    "requiredMode": "one",
                    "requiredAgendaIds": ["a", "b"],
                    "forbiddenAgendaIds": [],
                }
            ],
        )
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"a": 1, "b": 1}},
            schema_version=7,
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert len(monday) == 1
    assert monday[0]["type"] in {"a", "b"}
    assert monday[0]["fixed"] is True


def test_personal_fixed_one_distributes_shared_alternatives_between_members() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    fixed = [
        {
            "weekday": 1,
            "requiredMode": "one",
            "requiredAgendaIds": ["a", "b"],
            "forbiddenAgendaIds": [],
        }
    ]
    team = [
        member("member-1", ["a", "b"], fixed=fixed),
        member("member-2", ["a", "b"], fixed=fixed),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"a": 1, "b": 1}},
            schema_version=7,
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["type"] for item in monday} == {"a", "b"}
    assert {item["memberId"] for item in monday} == {"member-1", "member-2"}
    assert all(item["fixed"] for item in monday)


def test_personal_fixed_forbidden_prevents_assignment() -> None:
    agendas = [agenda("allowed", priority=2), agenda("forbidden", priority=1)]
    team = [
        member(
            "member-1",
            ["allowed", "forbidden"],
            fixed=[
                {
                    "weekday": 1,
                    "requiredMode": "all",
                    "requiredAgendaIds": [],
                    "forbiddenAgendaIds": ["forbidden"],
                }
            ],
        )
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"allowed": 1, "forbidden": 1}},
            schema_version=7,
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert [item["type"] for item in monday] == ["allowed"]


def test_personal_fixed_rules_conflict_when_two_members_claim_one_slot() -> None:
    agendas = [agenda("fixed", priority=1)]
    fixed = [
        {
            "weekday": 1,
            "requiredMode": "all",
            "requiredAgendaIds": ["fixed"],
            "forbiddenAgendaIds": [],
        }
    ]
    team = [
        member("member-1", ["fixed"], fixed=fixed),
        member("member-2", ["fixed"], fixed=fixed),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"fixed": 1}},
            schema_version=7,
        )
    )

    assert result.outcome == "infeasible"


def test_absent_fixed_member_leaves_demand_for_another_capable_member() -> None:
    agendas = [agenda("fixed", priority=1)]
    team = [
        member(
            "absent",
            ["fixed"],
            fixed=[{"weekday": 1, "type": "fixed"}],
            absences=[{"start": "2027-01-01", "end": "2027-01-31"}],
        ),
        member("substitute", ["fixed"]),
    ]
    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"fixed": 1}}))

    monday = next(item for item in result.assignments if item["date"] == "2027-01-04")
    assert monday["memberId"] == "substitute"
    assert "fixed" not in monday


def test_personal_telework_days_only_allow_telematic_agendas() -> None:
    agendas = [agenda("onsite", priority=1, telematic=False)]
    team = [member("member-1", ["onsite"], tele=[1])]
    result = CpSatScheduler().solve(problem(agendas, team, {"1": {"onsite": 1}}))

    assert result.outcome == "solution"
    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert [item["type"] for item in monday] == ["no_assignment"]
    assert {item["type"] for item in result.vacancies if item["date"] == "2027-01-04"} == {
        "onsite"
    }


def test_scheduler_avoids_repeating_clinical_agendas_on_consecutive_dates() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    team = [
        member("member-1", ["a", "b"], available=[1, 2, 3]),
        member("member-2", ["a", "b"], available=[1, 2, 3]),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {
                "1": {"a": 1, "b": 1},
                "2": {"a": 1, "b": 1},
                "3": {"a": 1, "b": 1},
            },
            start_date="2027-01-04",
            end_date="2027-01-06",
        )
    )

    clinical_by_member = {
        member_id: sorted(
            (item for item in result.assignments if item["memberId"] == member_id),
            key=lambda item: item["date"],
        )
        for member_id in {"member-1", "member-2"}
    }
    phase_names = [phase["name"] for phase in result.metrics["phases"]]
    repetition = next(
        phase for phase in result.metrics["phases"]
        if phase["name"] == "consecutive-clinical-agendas"
    )
    assert result.outcome == "solution"
    assert all(len(clinical) == 3 for clinical in clinical_by_member.values())
    assert all(
        left["type"] != right["type"]
        for clinical in clinical_by_member.values()
        for left, right in zip(clinical, clinical[1:], strict=False)
    )
    assert phase_names.index("total-historical-distance") < phase_names.index(
        "consecutive-clinical-agendas"
    )
    assert repetition["value"] == 0


def test_scheduler_does_not_treat_friday_and_monday_as_consecutive() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [member("member-1", ["clinical"], available=[1, 5])]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"clinical": 1}, "5": {"clinical": 1}},
            start_date="2027-01-08",
            end_date="2027-01-11",
        )
    )

    assert result.outcome == "solution"
    assert [item["type"] for item in result.assignments] == ["clinical", "clinical"]
    assert "consecutive-clinical-agendas" not in {
        phase["name"] for phase in result.metrics["phases"]
    }


def test_scheduler_counts_each_repeated_partial_agenda() -> None:
    agendas = [
        agenda("half-a", priority=1, load_percentage=50),
        agenda("half-b", priority=1, load_percentage=50),
    ]
    team = [member("member-1", ["half-a", "half-b"], available=[1, 2])]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"half-a": 1, "half-b": 1}, "2": {"half-a": 1, "half-b": 1}},
            start_date="2027-01-04",
            end_date="2027-01-05",
        )
    )

    repetition = next(
        phase for phase in result.metrics["phases"]
        if phase["name"] == "consecutive-clinical-agendas"
    )
    assert result.outcome == "solution"
    assert repetition["value"] == 2


def test_coverage_assigns_the_only_capable_person_before_fairness() -> None:
    agendas = [
        agenda("committee", priority=3, load_percentage=50),
        agenda("complement", priority=4, load_percentage=50),
        agenda("full", priority=2),
    ]
    team = [
        member("specialist", ["committee", "complement", "full"]),
        member("flexible", ["full"]),
    ]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"committee": 2, "complement": 1, "full": 1}},
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert any(
        item["memberId"] == "specialist" and item["type"] == "committee"
        for item in monday
    )
    assert any(
        item["memberId"] == "specialist" and item["type"] == "complement"
        for item in monday
    )
    assert Counter(
        item["type"] for item in result.vacancies if item["date"] == "2027-01-04"
    ) == Counter({"committee": 1})


def test_partial_day_tiebreak_completes_the_person_on_the_higher_priority_agenda() -> None:
    agendas = [
        agenda("higher-half", priority=2, load_percentage=50),
        agenda("lower-half", priority=3, load_percentage=50),
        agenda("complement", priority=3, load_percentage=50),
    ]
    team = [
        member("higher-person", ["higher-half", "complement"]),
        member(
            "lower-person",
            ["lower-half", "complement"],
            fixed=[{"weekday": 1, "type": "lower-half"}],
        ),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"higher-half": 1, "lower-half": 1, "complement": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [
        item
        for item in result.assignments
        if item["date"] == "2027-01-04" and item["type"] != "no_assignment"
    ]
    assert result.outcome == "solution"
    assert {
        item["type"]
        for item in monday
        if item["memberId"] == "higher-person"
    } == {"higher-half", "complement"}
    assert {
        item["type"]
        for item in monday
        if item["memberId"] == "lower-person"
    } == {"lower-half"}


def test_management_is_distributed_in_rounds_before_anyone_accumulates_days() -> None:
    agendas = [agenda("clinical", priority=1)]
    team = [
        member("person-1", ["clinical"], quota=5),
        member("person-2", ["clinical"], quota=5),
        member("person-3", ["clinical"], quota=5),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"clinical": 2}},
        )
    )

    management = Counter(item["memberId"] for item in result.assignments if item["type"] == "management")
    assert result.outcome == "solution"
    assert sorted(management.values()) == [1, 1, 2]


@pytest.mark.parametrize("priority", [1, 2, 3, 4])
def test_management_never_displaces_onsite_coverage(priority: int) -> None:
    agendas = [agenda("clinical", priority=priority)]
    team = [member("member-1", ["clinical"], quota=5)]
    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {"clinical": 1}})
    )

    assert result.outcome == "solution"
    assert not [item for item in result.assignments if item["type"] == "management"]
    assert not result.vacancies


@pytest.mark.parametrize("priority", [1, 2, 3, 4])
def test_management_can_displace_telematic_coverage(priority: int) -> None:
    agendas = [agenda("clinical", priority=priority, telematic=True)]
    team = [member("member-1", ["clinical"], quota=1)]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"clinical": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert [item["type"] for item in monday] == ["management"]
    assert result.vacancies == [{"date": "2027-01-04", "type": "clinical"}]


def test_management_moves_to_a_day_where_a_colleague_can_take_the_agenda() -> None:
    agendas = [
        agenda("replaceable", priority=4),
        agenda("manager-only", priority=4),
    ]
    team = [
        member(
            "manager",
            ["replaceable", "manager-only"],
            available=[1, 2],
            quota=1,
        ),
        member("colleague", ["replaceable"], available=[1]),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {
                "1": {"replaceable": 1},
                "2": {"manager-only": 1},
            },
        )
    )

    management = [
        item for item in result.assignments if item["type"] == "management"
    ]
    assert result.outcome == "solution"
    assert len(management) == 1
    assert date.fromisoformat(management[0]["date"]).isoweekday() == 1
    assert not result.vacancies


def test_management_can_consolidate_half_agendas_to_free_a_full_day() -> None:
    agendas = [
        agenda("half-a", load_percentage=50),
        agenda("half-b", load_percentage=50),
    ]
    team = [
        member("manager", ["half-a", "half-b"], quota=1),
        member("colleague", ["half-a", "half-b"]),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"half-a": 1, "half-b": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert Counter(item["type"] for item in monday) == Counter(
        {"half-a": 1, "half-b": 1, "management": 1}
    )
    assert next(item for item in monday if item["type"] == "management")["memberId"] == "manager"
    assert {
        item["memberId"] for item in monday if item["type"] in {"half-a", "half-b"}
    } == {"colleague"}


def test_management_can_displace_a_telematic_half_day() -> None:
    agendas = [agenda("half", priority=4, telematic=True, load_percentage=50)]
    team = [member("manager", ["half"], quota=1)]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"half": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert [item["type"] for item in monday] == ["management"]
    assert result.vacancies == [{"date": "2027-01-04", "type": "half"}]


def test_management_prefers_friday_without_repeating_calendar_week() -> None:
    team = [member("manager", [], available=[1, 2, 5], quota=5)]
    result = CpSatScheduler().solve(
        problem([], team, {}, holidays=["2027-01-01"])
    )

    management = [
        item for item in result.assignments if item["type"] == "management"
    ]
    weekdays = Counter(date.fromisoformat(item["date"]).isoweekday() for item in management)
    weeks = Counter(date.fromisoformat(item["date"]).isocalendar()[:2] for item in management)
    assert result.outcome == "solution"
    assert weekdays == {5: 4}
    assert max(weeks.values()) == 1
    assert all(item["telematic"] for item in management)
    invalid = result.to_dict()
    repeated_week = next(
        item
        for item in invalid["assignments"]
        if item["date"] == "2027-01-04" and item["type"] == "no_assignment"
    )
    repeated_week["type"] = "management"
    assert any(
        "management weekly limit exceeded" in error
        for error in validate_solution(
            problem([], team, {}, holidays=["2027-01-01"]),
            invalid,
        )
    )


def test_management_can_repeat_a_week_when_quota_exceeds_calendar_weeks() -> None:
    team = [member("manager", [], available=[1, 2, 3, 4, 5], quota=5)]
    result = CpSatScheduler().solve(
        problem([], team, {}, start_month="2027-02")
    )

    management = [
        item for item in result.assignments if item["type"] == "management"
    ]
    weeks = Counter(date.fromisoformat(item["date"]).isocalendar()[:2] for item in management)
    assert result.outcome == "solution"
    assert len(management) == 5
    assert sorted(weeks.values()) == [1, 1, 1, 2]


def test_management_prefers_a_slack_day_before_the_preferred_weekday() -> None:
    agendas = [agenda("clinical", priority=4)]
    team = [
        member("manager", ["clinical"], available=[2, 5], quota=1),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"5": {"clinical": 1}},
        )
    )

    management = [
        item for item in result.assignments if item["type"] == "management"
    ]
    assert result.outcome == "solution"
    assert len(management) == 1
    assert date.fromisoformat(management[0]["date"]).isoweekday() == 2
    assert not result.vacancies


def test_management_prefers_the_day_with_less_existing_vacancy_pressure() -> None:
    agendas = [
        agenda("manager-work", priority=4, telematic=True),
        agenda("unfillable", priority=4),
    ]
    team = [
        member("manager", ["manager-work"], available=[2, 5], quota=1),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {
                "2": {"manager-work": 1},
                "5": {"manager-work": 1, "unfillable": 3},
            },
        )
    )

    management = [
        item for item in result.assignments if item["type"] == "management"
    ]
    assert result.outcome == "solution"
    assert len(management) == 1
    assert date.fromisoformat(management[0]["date"]).isoweekday() == 2


def test_coverage_spreads_assignments_before_leaving_an_agenda_empty() -> None:
    agendas = [agenda("double"), agenda("single")]
    team = [
        member("person-1", ["double", "single"]),
        member("person-2", ["double", "single"]),
    ]
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"double": 2, "single": 1}},
            holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
        )
    )

    monday = [item for item in result.assignments if item["date"] == "2027-01-04"]
    assert result.outcome == "solution"
    assert {item["type"] for item in monday} == {"double", "single"}
    assert Counter(
        item["type"] for item in result.vacancies if item["date"] == "2027-01-04"
    ) == {"double": 1}


def test_historical_fairness_uses_equal_weight_person_profiles() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    team = [member("veteran", ["a", "b"]), member("newcomer", ["a", "b"])]
    holidays = ["2027-01-11", "2027-01-18", "2027-01-25"]
    historical = {
        "veteran": {"a": 60, "b": 40},
        "newcomer": {"a": 4, "b": 6},
    }
    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"a": 1, "b": 1}},
            holidays=holidays,
            historical=historical,
        )
    )

    monday = {
        item["memberId"]: item["type"]
        for item in result.assignments
        if item["date"] == "2027-01-04"
    }
    assert result.outcome == "solution"
    assert monday == {"veteran": "b", "newcomer": "a"}
    assert "no_assignment" not in monday.values()


def test_first_generation_empty_history_has_maximum_distance() -> None:
    agendas = [agenda("a"), agenda("b")]
    team = [
        member("veteran", ["a", "b"]),
        member("newcomer", ["a", "b"]),
    ]
    historical = {
        "veteran": {"a": 5, "b": 5},
        "newcomer": {"a": 0, "b": 0},
    }

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {}},
            historical=historical,
            first_generation_member_ids=["newcomer"],
            schema_version=9,
        )
    )

    assert result.outcome == "solution"
    assert result.metrics["fairness"]["personDistanceBasisPoints"] == {
        "veteran": 5_000,
        "newcomer": 10_000,
    }


def test_first_generation_proposals_reduce_newcomer_distance_normally() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    team = [
        member("veteran", ["a", "b"]),
        member("newcomer", ["a", "b"]),
    ]
    historical = {
        "veteran": {"a": 4, "b": 4},
        "newcomer": {"a": 0, "b": 0},
    }

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"a": 1, "b": 1}},
            historical=historical,
            first_generation_member_ids=["newcomer"],
            schema_version=9,
        )
    )

    newcomer_assignments = [
        item["type"]
        for item in result.assignments
        if item["memberId"] == "newcomer" and item["type"] != "no_assignment"
    ]
    assert result.outcome == "solution"
    assert Counter(newcomer_assignments) == {"a": 2, "b": 2}
    assert result.metrics["fairness"]["personDistanceBasisPoints"]["newcomer"] == 0


def test_historical_fairness_excludes_each_person_from_their_reference() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    absence = [{"start": "2027-01-01", "end": "2027-01-31"}]
    team = [
        member("profile-a", ["a", "b"], absences=absence),
        member("balanced", ["a", "b"], absences=absence),
        member("profile-b", ["a", "b"], absences=absence),
    ]
    historical = {
        "profile-a": {"a": 8, "b": 2},
        "balanced": {"a": 5, "b": 5},
        "profile-b": {"a": 2, "b": 8},
    }

    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {"a": 1, "b": 1}}, historical=historical)
    )

    assert result.outcome == "solution"
    assert result.metrics["fairness"]["personDistanceBasisPoints"] == {
        "profile-a": 4500,
        "balanced": 0,
        "profile-b": 4500,
    }
    assert result.metrics["fairness"]["worstDistanceBasisPoints"] == 4500


def test_generation_fairness_renormalizes_shared_agendas_around_exclusive_work() -> None:
    agendas = [agenda("exclusive"), agenda("shared-a"), agenda("shared-b")]
    absence = [{"start": "2027-01-01", "end": "2027-01-31"}]
    team = [
        member("specialist", ["exclusive", "shared-a", "shared-b"], absences=absence),
        member("peer", ["shared-a", "shared-b"], absences=absence),
    ]
    historical = {
        "specialist": {"exclusive": 10, "shared-a": 8, "shared-b": 2},
        "peer": {"exclusive": 0, "shared-a": 16, "shared-b": 4},
    }

    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {}}, historical=historical)
    )

    assert result.outcome == "solution"
    assert result.metrics["fairness"]["personDistanceBasisPoints"] == {
        "specialist": 0,
        "peer": 0,
    }


def test_generation_fairness_uses_total_variation_across_shared_agendas() -> None:
    agendas = [agenda("a"), agenda("b"), agenda("c")]
    absence = [{"start": "2027-01-01", "end": "2027-01-31"}]
    team = [
        member("profile-a", ["a", "b", "c"], absences=absence),
        member("profile-b", ["a", "b", "c"], absences=absence),
    ]
    historical = {
        "profile-a": {"a": 8, "b": 1, "c": 1},
        "profile-b": {"a": 4, "b": 3, "c": 3},
    }

    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {}}, historical=historical)
    )

    assert result.outcome == "solution"
    assert result.metrics["fairness"]["personDistanceBasisPoints"] == {
        "profile-a": 4000,
        "profile-b": 4000,
    }


def test_polishing_swaps_two_people_when_operational_fairness_improves() -> None:
    agendas = [agenda("a"), agenda("b")]
    team = [member("person-1", ["a", "b"]), member("person-2", ["a", "b"])]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"a": 1, "b": 1}},
        historical={
            "person-1": {"a": 10, "b": 0},
            "person-2": {"a": 0, "b": 10},
        },
        start_date="2027-01-04",
        end_date="2027-01-04",
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {"id": "one", "date": "2027-01-04", "memberId": "person-1", "type": "a"},
            {"id": "two", "date": "2027-01-04", "memberId": "person-2", "type": "b"},
        ],
        "vacancies": [],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
    )

    assert {(item["memberId"], item["type"]) for item in polished["assignments"]} == {
        ("person-1", "b"),
        ("person-2", "a"),
    }
    assert metrics["acceptedMoves"] == 1
    assert metrics["remainingImprovingMoves"] == 0


def test_final_polishing_swaps_people_to_improve_telematic_percentage() -> None:
    agendas = [agenda("onsite"), agenda("remote", telematic=True)]
    team = [
        member("short-week", ["onsite", "remote"], available=[1]),
        member("long-week", ["onsite", "remote"], available=[1, 2]),
    ]
    schedule_problem = problem(
        agendas,
        team,
        {
            "1": {"onsite": 1, "remote": 1},
            "2": {"onsite": 1},
        },
        start_date="2027-01-04",
        end_date="2027-01-05",
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {
                "id": "short-remote",
                "date": "2027-01-04",
                "memberId": "short-week",
                "type": "remote",
            },
            {
                "id": "long-onsite-monday",
                "date": "2027-01-04",
                "memberId": "long-week",
                "type": "onsite",
            },
            {
                "id": "long-onsite-tuesday",
                "date": "2027-01-05",
                "memberId": "long-week",
                "type": "onsite",
            },
        ],
        "vacancies": [],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
        objective="telematic-percentage",
        allow_vacancies=False,
    )

    remote = next(item for item in polished["assignments"] if item["type"] == "remote")
    assert remote["memberId"] == "long-week"
    assert metrics["acceptedMoves"] == 1
    assert metrics["remainingImprovingMoves"] == 0


def test_telematic_polishing_can_change_automatic_deferred_recipient() -> None:
    agendas = [agenda("onsite"), agenda("remote", telematic=True)]
    team = [
        member("historically-remote", ["onsite", "remote"], available=[2]),
        member("historically-onsite", ["onsite", "remote"], available=[2]),
    ]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"remote": 1}, "2": {"onsite": 1}},
        start_date="2027-01-04",
        end_date="2027-01-05",
        historical_telematic_days={
            "historically-remote": 8,
            "historically-onsite": 2,
        },
        historical_assigned_days={
            "historically-remote": 10,
            "historically-onsite": 10,
        },
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {
                "id": "automatic-deferred",
                "date": "2027-01-05",
                "memberId": "historically-remote",
                "type": "remote",
                "deferredOriginDate": "2027-01-04",
            },
            {
                "id": "ordinary-onsite",
                "date": "2027-01-05",
                "memberId": "historically-onsite",
                "type": "onsite",
            },
        ],
        "vacancies": [],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
        objective="telematic-percentage",
        allow_vacancies=False,
    )

    deferred = next(item for item in polished["assignments"] if item.get("deferredOriginDate"))
    onsite = next(item for item in polished["assignments"] if item["type"] == "onsite")
    assert deferred["memberId"] == "historically-onsite"
    assert onsite["memberId"] == "historically-remote"
    assert metrics["acceptedMoves"] == 1


def test_telematic_polishing_can_move_automatic_deferred_to_another_legal_day() -> None:
    agendas = [agenda("remote", telematic=True)]
    team = [
        member("historically-remote", ["remote"], available=[2]),
        member("historically-onsite", ["remote"], available=[3]),
    ]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"remote": 1}},
        start_date="2027-01-04",
        end_date="2027-01-06",
        historical_telematic_days={"historically-remote": 8, "historically-onsite": 2},
        historical_assigned_days={"historically-remote": 10, "historically-onsite": 10},
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {
                "id": "automatic-deferred",
                "date": "2027-01-05",
                "memberId": "historically-remote",
                "type": "remote",
                "deferredOriginDate": "2027-01-04",
            },
            {
                "id": "free-day",
                "date": "2027-01-06",
                "memberId": "historically-onsite",
                "type": "no_assignment",
            },
        ],
        "vacancies": [],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
        objective="telematic-percentage",
        allow_vacancies=False,
    )

    deferred = next(item for item in polished["assignments"] if item.get("deferredOriginDate"))
    replacement = next(item for item in polished["assignments"] if item["type"] == "no_assignment")
    assert (deferred["memberId"], deferred["date"]) == ("historically-onsite", "2027-01-06")
    assert (replacement["memberId"], replacement["date"]) == ("historically-remote", "2027-01-05")
    assert metrics["acceptedMoves"] == 1


def test_telematic_polishing_keeps_manual_deferred_recipient_locked() -> None:
    agendas = [agenda("onsite"), agenda("remote", telematic=True)]
    team = [
        member("historically-remote", ["onsite", "remote"], available=[2]),
        member("historically-onsite", ["onsite", "remote"], available=[2]),
    ]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"remote": 1}, "2": {"onsite": 1}},
        start_date="2027-01-04",
        end_date="2027-01-05",
        historical_telematic_days={"historically-remote": 8, "historically-onsite": 2},
        historical_assigned_days={"historically-remote": 10, "historically-onsite": 10},
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {
                "id": "manual-deferred",
                "date": "2027-01-05",
                "memberId": "historically-remote",
                "type": "remote",
                "deferredOriginDate": "2027-01-04",
                "locked": True,
                "manuallyModified": True,
            },
            {
                "id": "ordinary-onsite",
                "date": "2027-01-05",
                "memberId": "historically-onsite",
                "type": "onsite",
            },
        ],
        "vacancies": [],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
        objective="telematic-percentage",
        allow_vacancies=False,
    )

    deferred = next(item for item in polished["assignments"] if item.get("deferredOriginDate"))
    assert deferred["memberId"] == "historically-remote"
    assert metrics["acceptedMoves"] == 0


def test_polishing_can_exchange_an_assignment_with_same_modality_vacancy() -> None:
    agendas = [agenda("a"), agenda("b")]
    team = [
        member("person-1", ["a", "b"]),
        member(
            "peer",
            ["a", "b"],
            absences=[{"start": "2027-01-04", "end": "2027-01-04"}],
        ),
    ]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"a": 1, "b": 1}},
        historical={
            "person-1": {"a": 10, "b": 0},
            "peer": {"a": 0, "b": 10},
        },
        start_date="2027-01-04",
        end_date="2027-01-04",
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {"id": "one", "date": "2027-01-04", "memberId": "person-1", "type": "a"},
        ],
        "vacancies": [{"date": "2027-01-04", "type": "b"}],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
    )

    assert polished["assignments"][0]["type"] == "b"
    assert polished["vacancies"] == [{"date": "2027-01-04", "type": "a"}]
    assert metrics["acceptedMoves"] == 1


def test_polishing_never_replaces_onsite_coverage_with_telematic_coverage() -> None:
    agendas = [agenda("onsite"), agenda("remote", telematic=True)]
    team = [
        member("person-1", ["onsite", "remote"]),
        member(
            "peer",
            ["onsite", "remote"],
            absences=[{"start": "2027-01-04", "end": "2027-01-04"}],
        ),
    ]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"onsite": 1, "remote": 1}},
        historical={
            "person-1": {"onsite": 10, "remote": 0},
            "peer": {"onsite": 0, "remote": 10},
        },
        start_date="2027-01-04",
        end_date="2027-01-04",
    )
    initial = {
        "outcome": "solution",
        "assignments": [
            {"id": "one", "date": "2027-01-04", "memberId": "person-1", "type": "onsite"},
        ],
        "vacancies": [{"date": "2027-01-04", "type": "remote"}],
        "metrics": {},
        "diagnostics": [],
    }

    polished, metrics = _polish_solution(
        schedule_problem,
        initial,
        deadline=monotonic() + 2,
    )

    assert polished == initial
    assert metrics["acceptedMoves"] == 0


def test_scheduler_rejects_happiness_optimization_mode() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    team = [
        member("person-1", ["a", "b"], preferences={"a": 1, "b": 1}),
        member("person-2", ["a", "b"], preferences={"a": 0, "b": 1}),
    ]
    holidays = ["2027-01-11", "2027-01-18", "2027-01-25"]

    result = CpSatScheduler().solve(
        problem(
            agendas,
            team,
            {"1": {"a": 1, "b": 1}},
            holidays=holidays,
            optimization_mode="happiness",
        )
    )

    assert result.outcome == "model_invalid"
    assert result.error["code"] == "INVALID_OPTIMIZATION_MODE"


def test_historical_fairness_keeps_capable_person_absent_for_whole_period_in_cohort() -> None:
    agendas = [agenda("a", priority=1), agenda("b", priority=1)]
    team = [
        member("working-1", ["a", "b"]),
        member("working-2", ["a", "b"]),
        member(
            "absent",
            ["a", "b"],
            absences=[{"start": "2027-01-01", "end": "2027-01-31"}],
        ),
    ]
    historical = {
        "working-1": {"a": 6, "b": 4},
        "working-2": {"a": 4, "b": 6},
        "absent": {"a": 5, "b": 5},
    }
    result = CpSatScheduler().solve(
        problem(agendas, team, {"1": {"a": 1, "b": 1}}, historical=historical)
    )

    distances = result.metrics["fairness"]["personDistanceBasisPoints"]
    assert result.outcome == "solution"
    assert "absent" in distances


def test_result_validation_rejects_broken_fixed_rule() -> None:
    agendas = [agenda("fixed", priority=1), agenda("other", priority=1)]
    team = [
        member(
            "member-1",
            ["fixed", "other"],
            fixed=[{"weekday": 1, "type": "fixed"}],
        )
    ]
    schedule_problem = problem(agendas, team, {"1": {"fixed": 1, "other": 1}})
    invalid = {
        "outcome": "solution",
        "assignments": [
            {"date": value, "memberId": "member-1", "type": "other"}
            for value in ["2027-01-04", "2027-01-11", "2027-01-18", "2027-01-25"]
        ],
        "vacancies": [
            {"date": value, "type": "fixed"}
            for value in ["2027-01-04", "2027-01-11", "2027-01-18", "2027-01-25"]
        ],
    }

    assert any("fixed rule mismatch" in error for error in validate_solution(schedule_problem, invalid))


def test_result_validation_rejects_broken_personal_fixed_conditions() -> None:
    agendas = [agenda("required", priority=1), agenda("forbidden", priority=1)]
    team = [
        member(
            "member-1",
            ["required", "forbidden"],
            fixed=[
                {
                    "weekday": 1,
                    "requiredMode": "all",
                    "requiredAgendaIds": ["required"],
                    "forbiddenAgendaIds": ["forbidden"],
                }
            ],
        )
    ]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"required": 1, "forbidden": 1}},
        schema_version=7,
    )
    invalid = {
        "outcome": "solution",
        "assignments": [
            {"date": value, "memberId": "member-1", "type": "forbidden"}
            for value in ["2027-01-04", "2027-01-11", "2027-01-18", "2027-01-25"]
        ],
        "vacancies": [
            {"date": value, "type": "required"}
            for value in ["2027-01-04", "2027-01-11", "2027-01-18", "2027-01-25"]
        ],
    }

    errors = validate_solution(schedule_problem, invalid)

    assert any("personal fixed all mismatch" in error for error in errors)
    assert any("personal fixed forbidden mismatch" in error for error in errors)


def test_result_validation_accepts_an_exceptional_partial_person_day() -> None:
    agendas = [agenda("half", priority=1, load_percentage=50)]
    team = [member("member-1", ["half"])]
    schedule_problem = problem(
        agendas,
        team,
        {"1": {"half": 1}},
        holidays=["2027-01-11", "2027-01-18", "2027-01-25"],
    )
    partial = {
        "outcome": "solution",
        "assignments": [
            {"date": "2027-01-04", "memberId": "member-1", "type": "half"},
        ],
        "vacancies": [],
    }

    assert validate_solution(schedule_problem, partial) == []


def test_solver_snapshot_runs_in_spawned_process() -> None:
    snapshot = problem([agenda("clinical", priority=1)], [], {"1": {"clinical": 1}}).to_dict()

    try:
        executor = ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn"))
    except (NotImplementedError, PermissionError):
        pytest.skip("The sandbox does not expose process semaphores")
    with executor:
        result = executor.submit(solve_snapshot, snapshot).result(timeout=30)

    assert result["outcome"] == "solution"
    assert result["engine"] == "cp-sat"
