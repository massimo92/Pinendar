from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class ScheduleProblem:
    schema_version: int
    planning_revision: int
    start_month: str
    end_month: str
    team: list[dict[str, Any]]
    agendas: list[dict[str, Any]]
    coverage: dict[str, dict[str, int]]
    holidays: list[str]
    guards: list[dict[str, Any]]
    conditions: dict[str, list[dict[str, Any]]]
    historical_counts: dict[str, dict[str, int]]
    locked_assignments: list[dict[str, Any]]
    first_generation_member_ids: list[str] = field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    solver_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ScheduleProblem:
        return cls(
            **{
                "first_generation_member_ids": [],
                "start_date": None,
                "end_date": None,
                **value,
            }
        )


@dataclass(frozen=True)
class ScheduleResult:
    outcome: str
    assignments: list[dict[str, Any]]
    vacancies: list[dict[str, Any]]
    metrics: dict[str, Any]
    diagnostics: list[str]
    engine: str
    engine_version: str
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Scheduler(Protocol):
    def solve(self, problem: ScheduleProblem) -> ScheduleResult: ...


def month_end(month: str) -> date:
    year, value = map(int, month.split("-"))
    following = date(year + (value == 12), 1 if value == 12 else value + 1, 1)
    return following - timedelta(days=1)


def period_dates(
    start_month: str,
    end_month: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[date]:
    current = date.fromisoformat(start_date or f"{start_month}-01")
    end = date.fromisoformat(end_date) if end_date else month_end(end_month)
    values: list[date] = []
    while current <= end:
        values.append(current)
        current += timedelta(days=1)
    return values


def matches_recurrence(value: date, recurrence: dict[str, Any], holidays: set[str]) -> bool:
    weekday = int(recurrence["weekday"])
    if value.isoweekday() != weekday or value.isoformat() in holidays:
        return False
    ordinal = sum(
        1
        for day in range(1, value.day + 1)
        if date(value.year, value.month, day).isoweekday() == weekday
        and date(value.year, value.month, day).isoformat() not in holidays
    )
    return ordinal == int(recurrence["ordinal"])
