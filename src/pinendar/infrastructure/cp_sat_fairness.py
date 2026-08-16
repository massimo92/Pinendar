from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Any

from ortools.sat.python import cp_model

PERCENT_SCALE = 10_000


@dataclass(frozen=True)
class CpSatFairness:
    person_distances: dict[str, cp_model.IntVar]
    worst_distance: cp_model.IntVar | None


def add_operational_fairness(
    model: cp_model.CpModel,
    *,
    member_ids: Sequence[str],
    agenda_ids: Sequence[str],
    capabilities: Mapping[str, Set[str]],
    counts: Mapping[tuple[str, str], Any],
    maximum_totals: Mapping[str, int],
    member_order: Mapping[str, int],
    agenda_order: Mapping[str, int],
    maximum_distance_when_empty: Set[str] = frozenset(),
    prefix: str = "fairness",
) -> CpSatFairness:
    safe_profile_totals: dict[str, cp_model.IntVar] = {}
    for member_id in member_ids:
        maximum = maximum_totals[member_id]
        total = model.new_int_var(0, maximum, f"{prefix}_profile_total_p{member_order[member_id]}")
        model.add(total == sum((counts[(member_id, agenda_id)] for agenda_id in agenda_ids), 0))
        safe_total = model.new_int_var(1, max(maximum, 1), f"{prefix}_safe_profile_total_p{member_order[member_id]}")
        model.add_max_equality(safe_total, [total, 1])
        safe_profile_totals[member_id] = safe_total

    comparable_by_agenda = {
        agenda_id: [
            member_id
            for member_id in member_ids
            if agenda_id in capabilities[member_id] and maximum_totals[member_id] > 0
        ]
        for agenda_id in agenda_ids
    }
    comparable_by_agenda = {
        agenda_id: cohort
        for agenda_id, cohort in comparable_by_agenda.items()
        if len(cohort) >= 2
    }

    raw_shares: dict[tuple[str, str], cp_model.IntVar] = {}
    for agenda_id, cohort in comparable_by_agenda.items():
        for member_id in cohort:
            share = model.new_int_var(
                0,
                PERCENT_SCALE,
                f"{prefix}_raw_share_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
            )
            model.add_division_equality(
                share,
                PERCENT_SCALE * counts[(member_id, agenda_id)],
                safe_profile_totals[member_id],
            )
            raw_shares[(member_id, agenda_id)] = share

    person_distances: dict[str, cp_model.IntVar] = {}
    for member_id in member_ids:
        comparable_agendas = [
            agenda_id
            for agenda_id, cohort in comparable_by_agenda.items()
            if member_id in cohort
        ]
        if not comparable_agendas:
            continue
        maximum = maximum_totals[member_id]
        comparable_total = model.new_int_var(
            0,
            maximum,
            f"{prefix}_comparable_total_p{member_order[member_id]}",
        )
        model.add(
            comparable_total
            == sum((counts[(member_id, agenda_id)] for agenda_id in comparable_agendas), 0)
        )
        safe_comparable_total = model.new_int_var(
            1,
            max(maximum, 1),
            f"{prefix}_safe_comparable_total_p{member_order[member_id]}",
        )
        model.add_max_equality(safe_comparable_total, [comparable_total, 1])

        actual_shares: dict[str, cp_model.IntVar] = {}
        peer_means: dict[str, cp_model.IntVar] = {}
        for agenda_id in comparable_agendas:
            cohort = comparable_by_agenda[agenda_id]
            actual = model.new_int_var(
                0,
                PERCENT_SCALE,
                f"{prefix}_actual_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
            )
            model.add_division_equality(
                actual,
                PERCENT_SCALE * counts[(member_id, agenda_id)],
                safe_comparable_total,
            )
            actual_shares[agenda_id] = actual
            peer_mean = model.new_int_var(
                0,
                PERCENT_SCALE,
                f"{prefix}_peer_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
            )
            model.add_division_equality(
                peer_mean,
                sum(raw_shares[(peer_id, agenda_id)] for peer_id in cohort if peer_id != member_id),
                len(cohort) - 1,
            )
            peer_means[agenda_id] = peer_mean

        maximum_reference = len(comparable_agendas) * PERCENT_SCALE
        reference_total = model.new_int_var(
            0,
            maximum_reference,
            f"{prefix}_reference_total_p{member_order[member_id]}",
        )
        model.add(reference_total == sum(peer_means.values()))
        safe_reference_total = model.new_int_var(
            1,
            max(maximum_reference, 1),
            f"{prefix}_safe_reference_total_p{member_order[member_id]}",
        )
        model.add_max_equality(safe_reference_total, [reference_total, 1])

        deviations: list[cp_model.IntVar] = []
        for agenda_id in comparable_agendas:
            expected = model.new_int_var(
                0,
                PERCENT_SCALE,
                f"{prefix}_expected_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
            )
            model.add_division_equality(
                expected,
                PERCENT_SCALE * peer_means[agenda_id],
                safe_reference_total,
            )
            deviation = model.new_int_var(
                0,
                PERCENT_SCALE,
                f"{prefix}_deviation_p{member_order[member_id]}_a{agenda_order[agenda_id]}",
            )
            model.add_abs_equality(deviation, actual_shares[agenda_id] - expected)
            deviations.append(deviation)

        normal_distance = model.new_int_var(
            0,
            PERCENT_SCALE,
            f"{prefix}_normal_distance_p{member_order[member_id]}",
        )
        model.add_division_equality(normal_distance, sum(deviations), 2)
        if member_id in maximum_distance_when_empty:
            has_comparable_load = model.new_bool_var(
                f"{prefix}_has_comparable_load_p{member_order[member_id]}"
            )
            model.add(comparable_total >= 1).only_enforce_if(has_comparable_load)
            model.add(comparable_total == 0).only_enforce_if(
                has_comparable_load.negated()
            )
            distance = model.new_int_var(
                0,
                PERCENT_SCALE,
                f"{prefix}_distance_p{member_order[member_id]}",
            )
            model.add(distance == normal_distance).only_enforce_if(
                has_comparable_load
            )
            model.add(distance == PERCENT_SCALE).only_enforce_if(
                has_comparable_load.negated()
            )
        else:
            distance = normal_distance
        person_distances[member_id] = distance

    worst_distance: cp_model.IntVar | None = None
    if person_distances:
        worst_distance = model.new_int_var(0, PERCENT_SCALE, f"{prefix}_worst_distance")
        model.add_max_equality(worst_distance, list(person_distances.values()))
    return CpSatFairness(person_distances, worst_distance)
