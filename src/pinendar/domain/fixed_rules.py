from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass


@dataclass(frozen=True)
class FixedRulePartition:
    ordinary_ids: tuple[str, ...]
    peonada_ids: tuple[str, ...]
    total_load: int


def partition_fixed_rule_load(
    required_ids: Sequence[str],
    configured_peonada_ids: Set[str],
    loads: Mapping[str, int],
) -> FixedRulePartition:
    active_ids = tuple(dict.fromkeys(required_ids))
    total_load = sum(loads[agenda_id] for agenda_id in active_ids)
    if total_load <= 100:
        return FixedRulePartition(active_ids, (), total_load)
    peonada_ids = tuple(
        agenda_id for agenda_id in active_ids if agenda_id in configured_peonada_ids
    )
    ordinary_ids = tuple(
        agenda_id for agenda_id in active_ids if agenda_id not in configured_peonada_ids
    )
    return FixedRulePartition(ordinary_ids, peonada_ids, total_load)


def fixed_rule_load_error(
    *,
    required_mode: str,
    required_ids: Sequence[str],
    peonada_ids: Sequence[str],
    occurrences: Mapping[str, Set[int]],
    loads: Mapping[str, int],
) -> str | None:
    required = tuple(dict.fromkeys(required_ids))
    peonada = set(peonada_ids)
    if len(peonada) != len(peonada_ids) or not peonada.issubset(required):
        return "Les agendes de peonada han de formar part de les agendes obligatòries"
    if peonada and required_mode != "all":
        return "Les peonades fixes només es poden definir amb «Ha de fer totes»"
    if required_mode != "all":
        return None

    has_overload = False
    for ordinal in range(1, 6):
        active = [agenda_id for agenda_id in required if ordinal in occurrences.get(agenda_id, set())]
        total = sum(loads[agenda_id] for agenda_id in active)
        if total > 200:
            return "Les agendes obligatòries superen el 200% de càrrega diària"
        if total <= 100:
            continue
        has_overload = True
        partition = partition_fixed_rule_load(active, peonada, loads)
        ordinary_load = sum(loads[agenda_id] for agenda_id in partition.ordinary_ids)
        peonada_load = sum(loads[agenda_id] for agenda_id in partition.peonada_ids)
        if ordinary_load != 100 or peonada_load != total - 100:
            return (
                "En cada coincidència superior al 100%, la càrrega ordinària ha de sumar "
                "exactament 100% i la resta ha d’estar marcada com a peonada"
            )
    if peonada and not has_overload:
        return "Només es poden marcar peonades quan alguna coincidència supera el 100%"
    if has_overload and not peonada:
        return "Cal indicar quines agendes obligatòries seran peonada"
    return None
