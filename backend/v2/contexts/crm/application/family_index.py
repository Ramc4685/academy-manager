"""Querying the family index: filter, search, sort, paginate, summarise.

People CRM spec §3.2. The read model builds the whole academy's index once
(a fixed number of batched reads, cached briefly); everything here is pure
and runs over that in-memory index, so a keystroke never costs a Mongo round
trip per family. Sort always runs before pagination.

Money is computed once and gated at serialization (``can_view_family_money``
in :mod:`money_visibility`); :func:`query_family_index` takes the gate's
answer so a caller who may not see money can neither read amounts nor infer
them by sorting on balance.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

from backend.v2.contexts.crm.domain.family_index import (
    FamilyChild,
    FamilyIndex,
    FamilyMoney,
    FamilyRecord,
    SearchHit,
    search_family,
)
from backend.v2.contexts.crm.domain.family_stage import (
    FAMILY_STAGE_PRECEDENCE,
    FAMILY_STAGES,
    SCOPE_STAGES,
    stage_rank,
)

#: Re-exported for the interface layer, which may not import the domain.
__all__ = [
    "FAMILY_STAGES",
    "FamilyChild",
    "FamilyIndex",
    "FamilyIndexPage",
    "FamilyIndexQuery",
    "FamilyIndexRow",
    "FamilyIndexSummary",
    "FamilyIndexUnavailable",
    "FamilyMoney",
    "FamilyRecord",
    "find_family_record",
    "normalize_stages",
    "query_family_index",
    "summarize_family_index",
]

FamilySort = Literal["name", "stage", "balance", "children"]
FAMILY_SORTS: Final[frozenset[str]] = frozenset(get_args(FamilySort))
DEFAULT_PAGE_SIZE: Final[int] = 50
MAX_PAGE_SIZE: Final[int] = 200


class FamilyIndexUnavailable(RuntimeError):
    """A primary source (students, memberships, parents, lifecycles) failed."""


@dataclass(frozen=True)
class FamilyIndexQuery:
    search: str | None = None
    #: A Families scope tile: ``active``, ``leaving`` or ``left``.
    scope: str | None = None
    #: Exact family stages; empty means every stage.
    stages: tuple[str, ...] = ()
    #: Families with a child holding a seat in this session.
    class_id: str | None = None
    #: Card filter chip ("No card", spec §3.2): False keeps families without one.
    card_on_file: bool | None = None
    #: The Overdue chip: an open invoice past its due date. Money-gated.
    overdue: bool | None = None
    sort: str = "name"
    #: None means the sort's natural order: balance largest first, the rest ascending.
    descending: bool | None = None
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


@dataclass(frozen=True)
class FamilyIndexRow:
    record: FamilyRecord
    hit: SearchHit | None = None


@dataclass(frozen=True)
class FamilyIndexPage:
    rows: tuple[FamilyIndexRow, ...]
    total: int
    page: int
    page_size: int
    warnings: tuple[str, ...] = ()
    #: False when money was hidden from this caller (every money field null).
    money_visible: bool = True


@dataclass(frozen=True)
class FamilyIndexSummary:
    total_families: int
    #: Scope tiles over the UNFILTERED index, each family counted once.
    tiles: dict[str, int] = field(default_factory=dict)
    counts_by_stage: dict[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    #: The "No card" chip's count: the families ``card_on_file=false`` keeps.
    no_card_families: int = 0
    #: The Overdue chip's count: the families ``overdue=true`` keeps. Money
    #: derived, so the view drops it for a caller who may not see money.
    overdue_families: int = 0


def _primary_key(sort: str, money_visible: bool) -> Callable[[FamilyIndexRow], Any] | None:
    if sort == "stage":
        return lambda row: stage_rank(row.record.stage)
    if sort == "children":
        return lambda row: len(row.record.children)
    if sort == "balance" and money_visible:
        return lambda row: row.record.money.balance_cents if row.record.money is not None else -1
    return None


def query_family_index(
    index: FamilyIndex, query: FamilyIndexQuery, *, money_visible: bool
) -> FamilyIndexPage:
    page_size = max(1, min(query.page_size, MAX_PAGE_SIZE))
    page = max(1, query.page)
    wanted: set[str] = set(query.stages)
    if query.scope:
        wanted = (wanted & SCOPE_STAGES[query.scope]) if wanted else set(SCOPE_STAGES[query.scope])

    rows: list[FamilyIndexRow] = []
    for record in index.families:
        if (query.scope or query.stages) and record.stage not in wanted:
            continue
        if query.class_id and not any(
            query.class_id in child.session_ids for child in record.children
        ):
            continue
        if query.card_on_file is not None and record.card_on_file is not query.card_on_file:
            continue
        if query.overdue is not None:
            # Hidden money cannot be filtered on either: that would leak it.
            if not money_visible or record.money is None:
                continue
            if (record.money.overdue_invoice_count > 0) is not query.overdue:
                continue
        hit: SearchHit | None = None
        if query.search and query.search.strip():
            hit = search_family(record, query.search)
            if hit is None:
                continue
        rows.append(FamilyIndexRow(record=record, hit=hit))

    sort = query.sort if query.sort in FAMILY_SORTS else "name"
    descending = (
        query.descending if query.descending is not None else sort == "balance" and money_visible
    )
    # Two stable passes: ties always fall back to parent name ascending,
    # whichever way the primary column runs.
    rows.sort(key=lambda row: row.record.sort_key)
    primary = _primary_key(sort, money_visible)
    if primary is not None:
        rows.sort(key=primary, reverse=descending)
    elif descending:
        rows.reverse()
    start = (page - 1) * page_size
    return FamilyIndexPage(
        rows=tuple(rows[start : start + page_size]),
        total=len(rows),
        page=page,
        page_size=page_size,
        warnings=index.warnings,
        money_visible=money_visible,
    )


def summarize_family_index(index: FamilyIndex) -> FamilyIndexSummary:
    counts: dict[str, int] = {stage: 0 for stage in FAMILY_STAGE_PRECEDENCE}
    for record in index.families:
        counts[record.stage] = counts.get(record.stage, 0) + 1
    tiles = {
        scope: sum(counts.get(stage, 0) for stage in stages)
        for scope, stages in SCOPE_STAGES.items()
    }
    return FamilyIndexSummary(
        total_families=len(index.families),
        tiles=tiles,
        counts_by_stage=counts,
        warnings=index.warnings,
        # The same predicates query_family_index applies for these chips.
        no_card_families=sum(1 for r in index.families if r.card_on_file is False),
        overdue_families=sum(
            1 for r in index.families if r.money is not None and r.money.overdue_invoice_count > 0
        ),
    )


def normalize_stages(values: Sequence[str]) -> tuple[str, ...]:
    """Comma-separated or repeated ``stage`` params, de-duplicated."""
    out: list[str] = []
    for value in values:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(dict.fromkeys(out))


def find_family_record(index: FamilyIndex, family_id: str) -> FamilyRecord | None:
    """One family record by its canonical id or any alias of it.

    The family record page's Overview header and stage (People CRM spec §4),
    read from the same index row the Families view shows so the two can never
    disagree. Student pages link to ``/admin/families/{student.parent_id}``,
    which may be the parent's ``firebase_uid``, ``auth_uid`` or users ``_id``
    rather than the canonical id, so the id is first resolved through the
    index's own alias map (built from this academy's rows only: another
    academy's alias is never found). The returned record carries the
    canonical ``family_id``.
    """
    wanted = family_id.strip()
    if not wanted:
        return None
    canonical = index.family_by_alias.get(wanted, wanted)
    return next((record for record in index.families if record.family_id == canonical), None)
