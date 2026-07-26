from __future__ import annotations

import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pinendar.application.state import DomainError, bump_revision, month_end, uid
from pinendar.infrastructure.models import (
    Assignment,
    Guard,
    Member,
    MemberAlias,
)

ROLE_TOKENS = {
    "resident",
    "residents",
    "residente",
    "residentes",
    "residenta",
    "adjunt",
    "adjunta",
    "adjuntos",
    "adjuntes",
    "adjunto",
    "dr",
    "dra",
    "doctor",
    "doctora",
}
ACCEPT_SCORE = 92
REVIEW_SCORE = 78


def guard_normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = "".join(char for char in unicodedata.normalize("NFD", value) if unicodedata.category(char) != "Mn")
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    tokens = [token for token in value.split() if token not in ROLE_TOKENS]
    return " ".join(tokens)


def _tokens(value: str) -> list[str]:
    return guard_normalized(value).split()


def _similarity(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if left == right:
        return 100
    window = max(len(left), len(right)) // 2 - 1
    left_matches = [False] * len(left)
    right_matches = [False] * len(right)
    matches = 0
    for index, char in enumerate(left):
        start = max(0, index - window)
        end = min(index + window + 1, len(right))
        for other in range(start, end):
            if not right_matches[other] and char == right[other]:
                left_matches[index] = True
                right_matches[other] = True
                matches += 1
                break
    if not matches:
        return 0
    left_order = [char for index, char in enumerate(left) if left_matches[index]]
    right_order = [char for index, char in enumerate(right) if right_matches[index]]
    transpositions = sum(
        left_char != right_char for left_char, right_char in zip(left_order, right_order, strict=True)
    ) // 2
    jaro = (matches / len(left) + matches / len(right) + (matches - transpositions) / matches) / 3
    prefix = 0
    for left_char, right_char in zip(left, right, strict=False):
        if left_char != right_char or prefix == 4:
            break
        prefix += 1
    jaro_winkler = jaro + prefix * 0.1 * (1 - jaro)
    return round(max(jaro_winkler, SequenceMatcher(None, left, right).ratio()) * 100)


def _candidate_score(raw: str, member: Member) -> tuple[int, str]:
    source = guard_normalized(raw)
    source_tokens = _tokens(raw)
    member_name = guard_normalized(member.name)
    member_tokens = _tokens(member.name)
    if source == member_name:
        return 100, "nombre completo exacto"
    if source_tokens and source_tokens == member_tokens:
        return 100, "tokens exactos"
    if source_tokens and member_tokens and source_tokens[-1] == member_tokens[-1]:
        if len(source_tokens) == 1:
            return 97, "apellido exacto"
        if len(source_tokens[0]) == 1 and source_tokens[0] == member_tokens[0][0]:
            return 99, "inicial y apellido exactos"
        return 95, "apellido exacto"
    if source_tokens and member_tokens:
        surname_score = _similarity(source_tokens[-1], member_tokens[-1])
        full_score = _similarity(source, member_name)
        if len(source_tokens) == 1:
            return surname_score, "apellido parecido"
        return round(surname_score * 0.7 + full_score * 0.3), "nombre parecido"
    return 0, "sin texto"


def _candidate_payload(member: Member, score: int, reason: str) -> dict[str, Any]:
    return {"memberId": member.id, "name": member.name, "score": score, "reason": reason}


def _resolve_name(raw: str, members: list[Member], aliases: dict[str, list[Member]]) -> dict[str, Any]:
    clean = guard_normalized(raw)
    if not clean:
        return {"rawName": raw, "status": "ignored", "reason": "nombre vacío", "candidates": []}
    email_key = f"email:{raw.strip().casefold()}" if "@" in raw else ""
    alias_matches = aliases.get(email_key or clean, [])
    if len(alias_matches) == 1:
        member = alias_matches[0]
        return {
            "rawName": raw,
            "status": "accepted",
            "memberId": member.id,
            "memberName": member.name,
            "score": 100,
            "reason": "alias confirmado",
            "candidates": [_candidate_payload(member, 100, "alias confirmado")],
        }
    if len(alias_matches) > 1:
        return {
            "rawName": raw,
            "status": "review",
            "score": 100,
            "reason": "alias asociado a varias personas",
            "candidates": [_candidate_payload(member, 100, "alias asociado a varias personas") for member in alias_matches],
        }
    scored = sorted(
        ((*_candidate_score(raw, member), member) for member in members),
        key=lambda item: (-item[0], item[2].name.casefold()),
    )
    scored = [item for item in scored if item[0] >= REVIEW_SCORE]
    candidates = [_candidate_payload(member, score, reason) for score, reason, member in scored[:5]]
    if not scored:
        return {"rawName": raw, "status": "ignored", "reason": "persona no registrada", "candidates": []}
    best_score, best_reason, best_member = scored[0]
    margin = best_score - scored[1][0] if len(scored) > 1 else best_score
    if best_score >= ACCEPT_SCORE and margin >= 8:
        return {
            "rawName": raw,
            "status": "accepted",
            "memberId": best_member.id,
            "memberName": best_member.name,
            "score": best_score,
            "reason": best_reason,
            "candidates": candidates,
        }
    return {
        "rawName": raw,
        "status": "review",
        "score": best_score,
        "reason": "coincidencia ambigua o débil",
        "candidates": candidates,
    }


def _period_bounds(
    start_month: str,
    end_month: str,
    exact_start: str | None = None,
    exact_end: str | None = None,
) -> tuple[str, str]:
    try:
        start_date = date.fromisoformat(exact_start or f"{start_month}-01")
        end_date = date.fromisoformat(exact_end) if exact_end else month_end(end_month)
        if (
            end_date < start_date
            or (end_date - start_date).days + 1 > 31
            or start_date.strftime("%Y-%m") != end_date.strftime("%Y-%m")
            or start_date.strftime("%Y-%m") != start_month
            or end_date.strftime("%Y-%m") != end_month
        ):
            raise ValueError
        return start_date.isoformat(), end_date.isoformat()
    except (ValueError, TypeError) as error:
        raise DomainError("INVALID_PERIOD", "El período seleccionado no es válido", field="startMonth") from error


def preview_guard_import(
    session: Session,
    start_month: str,
    end_month: str,
    rows: list[dict[str, Any]],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    bounds_start, bounds_end = _period_bounds(start_month, end_month, start_date, end_date)
    members = list(
        session.scalars(
            select(Member)
            .where(Member.archived_at.is_(None), Member.is_active.is_(True))
            .order_by(Member.name)
        )
    )
    aliases: dict[str, list[Member]] = {}
    member_by_id = {member.id: member for member in members}
    for alias in session.scalars(select(MemberAlias).where(MemberAlias.member_id.in_(member_by_id))):
        member = member_by_id.get(alias.member_id)
        if member:
            aliases.setdefault(alias.normalized_alias, []).append(member)
    for member in members:
        aliases.setdefault(f"email:{member.email.strip().casefold()}", []).append(member)

    output_rows: list[dict[str, Any]] = []
    accepted_by_date: dict[str, dict[str, Any]] = {}
    summary = {"accepted": 0, "ignored": 0, "review": 0, "outOfRange": 0, "empty": 0}
    period_start = date.fromisoformat(bounds_start)
    period_end = date.fromisoformat(bounds_end)
    for raw_row in rows:
        row_number = int(raw_row.get("rowNumber", 0))
        date_value = str(raw_row.get("date") or "")
        names = [str(name).strip() for name in raw_row.get("names", []) if str(name).strip()]
        try:
            parsed_date = date.fromisoformat(date_value)
        except ValueError:
            parsed_date = None
        if parsed_date is None:
            summary["outOfRange"] += 1
            output_rows.append({"rowNumber": row_number, "date": date_value, "status": "invalid_date", "items": []})
            continue
        if parsed_date < period_start or parsed_date > period_end:
            summary["outOfRange"] += 1
            output_rows.append({"rowNumber": row_number, "date": date_value, "status": "out_of_range", "items": []})
            continue
        if not names:
            summary["empty"] += 1
            output_rows.append({"rowNumber": row_number, "date": date_value, "status": "empty", "items": []})
            continue
        items = [_resolve_name(name, members, aliases) for name in names]
        for item in items:
            summary[item["status"]] += 1
            if item["status"] == "accepted":
                accepted_by_date.setdefault(date_value, {})[item["memberId"]] = item
        output_rows.append({"rowNumber": row_number, "date": date_value, "status": "ready", "items": items})

    conflicts = [
        {"date": date_value, "members": list(member_items.values())}
        for date_value, member_items in accepted_by_date.items()
        if len(member_items) > 1
    ]
    return {
        "rows": output_rows,
        "conflicts": conflicts,
        "summary": summary,
        "canConfirm": summary["review"] == 0 and not conflicts,
    }


def create_member_alias(session: Session, member_id: str, alias: str) -> dict[str, Any]:
    member = session.scalar(
        select(Member).where(
            Member.id == member_id,
            Member.archived_at.is_(None),
            Member.is_active.is_(True),
        )
    )
    clean = alias.strip()
    normalized_alias = guard_normalized(clean)
    if not member:
        raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="memberId")
    if not normalized_alias:
        raise DomainError("ALIAS_REQUIRED", "L’alias no pot estar buit", field="alias")
    existing = list(session.scalars(select(MemberAlias).where(MemberAlias.normalized_alias == normalized_alias)))
    if any(item.member_id != member_id for item in existing):
        raise DomainError("ALIAS_AMBIGUOUS", "Aquest alias ja està associat a una altra persona", field="alias")
    current = next((item for item in existing if item.member_id == member_id), None)
    if current:
        return {"id": current.id, "memberId": member_id, "alias": current.alias}
    item = MemberAlias(id=uid(), member_id=member_id, alias=clean, normalized_alias=normalized_alias)
    session.add(item)
    session.flush()
    return {"id": item.id, "memberId": member_id, "alias": item.alias}


def _assert_guard_import_safe(session: Session, guard_dates: set[date]) -> None:
    post_guard_dates = {value.fromordinal(value.toordinal() + 1) for value in guard_dates}
    if post_guard_dates and session.scalar(
        select(Assignment.id).where(Assignment.date.in_(post_guard_dates)).limit(1)
    ):
        raise DomainError(
            "GUARD_OPERATION_REQUIRED",
            "Amb un calendari generat, modifica les guàrdies mitjançant una cessió o un intercanvi",
        )


def add_guards(session: Session, guards: list[dict[str, Any]]) -> dict[str, Any]:
    active_member_ids = set(
        session.scalars(select(Member.id).where(Member.archived_at.is_(None), Member.is_active.is_(True)))
    )
    existing = {item.date: item for item in session.scalars(select(Guard))}
    added: list[Guard] = []
    pending_dates: set[date] = set()
    normalized_guards: list[tuple[dict[str, Any], str, date]] = []
    for raw_guard in guards:
        member_id = raw_guard.get("memberId") or raw_guard.get("member_id")
        guard_date = raw_guard.get("date")
        if member_id not in active_member_ids:
            raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="guards")
        if not isinstance(guard_date, date):
            try:
                guard_date = date.fromisoformat(str(guard_date))
            except (TypeError, ValueError) as error:
                raise DomainError("INVALID_DATE", "La data de la guàrdia no és vàlida", field="guards") from error
        normalized_guards.append((raw_guard, member_id, guard_date))
    _assert_guard_import_safe(session, {item[2] for item in normalized_guards})
    for raw_guard, member_id, guard_date in normalized_guards:
        current = existing.get(guard_date)
        if current or guard_date in pending_dates:
            current_member_id = current.member_id if current else next(
                item.member_id for item in added if item.date == guard_date
            )
            if current_member_id != member_id:
                raise DomainError(
                    "DUPLICATE_GUARD_DATE",
                    f"Només hi pot haver una persona de guàrdia el {guard_date.isoformat()}",
                    field="guards",
                )
            continue
        item = Guard(
            id=raw_guard.get("id") or uid(),
            member_id=member_id,
            date=guard_date,
        )
        session.add(item)
        added.append(item)
        pending_dates.add(guard_date)

    if added:
        session.flush()
        bump_revision(session)
    all_guards = sorted([*existing.values(), *added], key=lambda item: (item.date, item.id))
    return {
        "added": len(added),
        "guards": [
            {"id": item.id, "memberId": item.member_id, "date": item.date.isoformat()}
            for item in all_guards
        ],
    }


def replace_guards(session: Session, guards: list[dict[str, Any]]) -> dict[str, Any]:
    active_member_ids = set(
        session.scalars(select(Member.id).where(Member.archived_at.is_(None), Member.is_active.is_(True)))
    )
    desired: dict[date, str] = {}
    for raw_guard in guards:
        raw_member_id = raw_guard.get("memberId") or raw_guard.get("member_id")
        member_id = str(raw_member_id) if raw_member_id is not None else ""
        try:
            raw_date = raw_guard.get("date")
            guard_date: date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
        except (TypeError, ValueError) as error:
            raise DomainError("INVALID_DATE", "La data de la guàrdia no és vàlida", field="guards") from error
        if member_id not in active_member_ids:
            raise DomainError("MEMBER_NOT_FOUND", "Persona no trobada", field="guards")
        if guard_date in desired:
            raise DomainError("DUPLICATE_GUARD_DATE", f"Només hi pot haver una persona de guàrdia el {guard_date.isoformat()}", field="guards")
        desired[guard_date] = member_id
    _assert_guard_import_safe(session, set(desired))
    if not desired:
        return {"guards": []}
    range_start, range_end = min(desired), max(desired)
    existing = {
        item.date: item
        for item in session.scalars(
            select(Guard).where(Guard.date >= range_start, Guard.date <= range_end)
        )
    }
    changed = False
    for guard_date, member_id in desired.items():
        item = existing.pop(guard_date, None)
        if item is None:
            session.add(Guard(id=uid(), member_id=member_id, date=guard_date))
            changed = True
        elif item.member_id != member_id:
            item.member_id = member_id
            changed = True
    if existing:
        session.execute(delete(Guard).where(Guard.id.in_([item.id for item in existing.values()])))
        changed = True
    if changed:
        session.flush()
        bump_revision(session)
    items = list(
        session.scalars(
            select(Guard)
            .where(Guard.date >= range_start, Guard.date <= range_end)
            .order_by(Guard.date)
        )
    )
    return {"guards": [{"id": item.id, "memberId": item.member_id, "date": item.date.isoformat()} for item in items]}
