from collections.abc import Mapping, Sequence, Set


def operational_person_distances(
    member_ids: Sequence[str],
    agenda_ids: Sequence[str],
    counts: Mapping[str, Mapping[str, float]],
    capabilities: Mapping[str, Set[str]],
) -> dict[str, float]:
    totals = {
        member_id: sum(counts[member_id].get(agenda_id, 0.0) for agenda_id in agenda_ids)
        for member_id in member_ids
    }
    distances: dict[str, float] = {}
    for member_id in member_ids:
        references: list[tuple[str, float]] = []
        for agenda_id in agenda_ids:
            if agenda_id not in capabilities[member_id]:
                continue
            peers = [
                peer_id
                for peer_id in member_ids
                if peer_id != member_id
                and totals[peer_id] > 0
                and agenda_id in capabilities[peer_id]
            ]
            if not peers:
                continue
            peer_share = sum(
                counts[peer_id].get(agenda_id, 0.0) / totals[peer_id]
                for peer_id in peers
            ) / len(peers)
            references.append((agenda_id, peer_share))

        own_comparable_total = sum(
            counts[member_id].get(agenda_id, 0.0)
            for agenda_id, _peer_share in references
        )
        reference_total = sum(peer_share for _agenda_id, peer_share in references)
        if not references or own_comparable_total <= 0 or reference_total <= 0:
            continue
        distance = sum(
            abs(
                counts[member_id].get(agenda_id, 0.0) / own_comparable_total
                - peer_share / reference_total
            )
            for agenda_id, peer_share in references
        ) / 2
        distances[member_id] = min(1.0, distance)
    return distances


def operational_fairness_score(
    member_ids: Sequence[str],
    agenda_ids: Sequence[str],
    counts: Mapping[str, Mapping[str, float]],
    capabilities: Mapping[str, Set[str]],
    *,
    scale: int = 10_000,
) -> tuple[int, int]:
    distances = operational_person_distances(
        member_ids,
        agenda_ids,
        counts,
        capabilities,
    ).values()
    measured = list(distances)
    return (
        round(max(measured, default=0.0) * scale),
        round(sum(measured) * scale),
    )
