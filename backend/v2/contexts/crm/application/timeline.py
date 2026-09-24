"""The unified family timeline read (People CRM spec §5, roadmap L4a/L4b).

``GetFamilyTimeline`` proves the id is a family of the caller's academy (the
family index, #664), resolves the parent's aliases, and asks every source for
its newest entries at once (``asyncio.gather``). Each source is read with a
limit of :data:`SOURCE_LIMIT`; a source that fails adds
``"<name>_unavailable"`` to ``warnings`` and the feed is built from the rest
(never a silent gap, never a 500). The merged feed is deduped, sorted, cut to
:data:`TIMELINE_CAP` and paged with an opaque cursor.

Sources owned here (the owning contexts are handed in by
``composition/family_timeline.py``; the CRM imports none of them):

* :class:`BillingTimelineSource`: billing's own family timeline
  (``build_timeline`` via the family billing read model: invoices, payments,
  failures, dunning, billing admin actions, enrollment lifecycle events of
  every enrollment of the family's children, invoice and notice emails). It
  is called as one source and not extended (spec §5).
* :class:`CoachNotesTimelineSource`: the notes a coach shared with the family
  (#665), read-only, with the coach's name.
* the Mongo sources in ``infrastructure/family_timeline_sources.py``:
  attendance, requests, the ``audit_logs`` allowlist with "moved family"
  entries, and the CRM's own notes, follow-ups and contacts.

Money amounts are redacted at the interface for callers who may not see
them (``can_view_family_money``); this use case always returns amounts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol, cast

from backend.v2.contexts.crm.application.ports import ParentAliasResolver
from backend.v2.contexts.crm.domain.errors import FamilyNotFound
from backend.v2.contexts.crm.domain.family_index import FamilyRecord
from backend.v2.contexts.crm.domain.timeline import (
    AUDIT_ACTION_ALLOWLIST,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SOURCE_LIMIT,
    TIMELINE_CAP,
    TIMELINE_KINDS,
    TimelineCursor,
    TimelineEntry,
    TimelineKind,
    as_utc,
    merge_timeline,
    paginate,
    redact_money,
)

log = logging.getLogger(__name__)

# Re-exported for the admin BFF (interfaces may not import the domain).
__all__ = [
    "AUDIT_ACTION_ALLOWLIST",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "BillingTimelineSource",
    "CoachNotesTimelineSource",
    "FamilyTimelinePage",
    "FamilyTimelineScope",
    "GetFamilyTimeline",
    "TimelineCursor",
    "TimelineEntry",
    "TimelineSourceResult",
    "redact_money",
]


@dataclass(frozen=True)
class FamilyTimelineScope:
    """Everything a source needs to find the family's rows in one academy."""

    academy_id: str
    family_id: str
    #: Every id the parent is stored under (canonical id first).
    parent_aliases: tuple[str, ...]
    student_ids: tuple[str, ...]
    student_names: Mapping[str, str]
    #: Canonical family id -> parent name, for "Moved from family X".
    family_names: Mapping[str, str | None] = field(default_factory=dict)
    #: Only rows at or before this instant are needed (the page cursor).
    before: datetime | None = None


@dataclass(frozen=True)
class TimelineSourceResult:
    entries: Sequence[TimelineEntry]
    warnings: Sequence[str] = ()


class FamilyTimelineSource(Protocol):
    @property
    def name(self) -> str: ...

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult: ...


class FamilyRecordDirectory(Protocol):
    async def find_record(self, academy_id: str, family_id: str) -> FamilyRecord | None: ...

    async def names(self, academy_id: str) -> Mapping[str, str | None]: ...


@dataclass(frozen=True)
class FamilyTimelinePage:
    family_id: str
    entries: list[TimelineEntry]
    next_cursor: str | None
    warnings: list[str]


class GetFamilyTimeline:
    def __init__(
        self,
        families: FamilyRecordDirectory,
        aliases: ParentAliasResolver,
        sources: Sequence[FamilyTimelineSource],
    ) -> None:
        self._families = families
        self._aliases = aliases
        self._sources = tuple(sources)

    async def execute(
        self,
        *,
        academy_id: str,
        parent_id: str,
        before: TimelineCursor | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> FamilyTimelinePage:
        record = await self._families.find_record(academy_id, parent_id)
        if record is None:
            raise FamilyNotFound("family not found", parent_id=parent_id)
        warnings: list[str] = []
        scope = FamilyTimelineScope(
            academy_id=academy_id,
            family_id=record.family_id,
            parent_aliases=await self._parent_aliases(record.family_id, warnings),
            student_ids=tuple(c.student_id for c in record.children),
            student_names={c.student_id: c.name for c in record.children},
            family_names=await self._family_names(academy_id, warnings),
            before=before.at if before is not None else None,
        )
        results = await asyncio.gather(*(self._fetch(s, scope) for s in self._sources))
        batches: list[Sequence[TimelineEntry]] = []
        for result in results:
            if result is None:
                continue
            batches.append(result.entries)
            warnings.extend(result.warnings)
        for source, result in zip(self._sources, results, strict=True):
            if result is None:
                warnings.append(f"{source.name}_unavailable")
        merged = merge_timeline(batches, cap=TIMELINE_CAP)
        page, cursor = paginate(merged, before=before, limit=limit)
        return FamilyTimelinePage(
            family_id=record.family_id,
            entries=page,
            next_cursor=cursor.encode() if cursor is not None else None,
            warnings=list(dict.fromkeys(warnings)),
        )

    async def _fetch(
        self, source: FamilyTimelineSource, scope: FamilyTimelineScope
    ) -> TimelineSourceResult | None:
        try:
            return await source.fetch(scope)
        except Exception:
            log.warning("family timeline: %s source failed", source.name, exc_info=True)
            return None

    async def _parent_aliases(self, family_id: str, warnings: list[str]) -> tuple[str, ...]:
        try:
            resolved = (await self._aliases.resolve_parent_aliases([family_id])).get(family_id)
        except Exception:
            log.warning("family timeline: parent aliases failed", exc_info=True)
            warnings.append("parent_aliases_unavailable")
            resolved = None
        rest = sorted(a for a in (resolved.aliases if resolved else ()) if a and a != family_id)
        return (family_id, *rest)

    async def _family_names(self, academy_id: str, warnings: list[str]) -> Mapping[str, str | None]:
        try:
            return await self._families.names(academy_id)
        except Exception:
            log.warning("family timeline: family names failed", exc_info=True)
            warnings.append("family_names_unavailable")
            return {}


# ------------------------------------------------------------------ billing


class FamilyBillingTimelineReader(Protocol):
    """Billing's family view (``GET /admin/families/{id}/billing``'s builder)."""

    async def build(self, parent_id: str) -> dict[str, Any] | None: ...


def _parse_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, str) and value:
        try:
            return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _kind(value: Any) -> TimelineKind:
    return cast(TimelineKind, value) if value in TIMELINE_KINDS else "admin"


def _opt(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _opt_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class BillingTimelineSource:
    """Billing's own family timeline, as one source (spec §5: not extended)."""

    name = "billing"

    def __init__(self, reader: FamilyBillingTimelineReader) -> None:
        self._reader = reader

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        view = await self._reader.build(scope.family_id)
        if view is None:
            return TimelineSourceResult(entries=())
        entries: list[TimelineEntry] = []
        for raw in view.get("timeline") or []:
            at = _parse_at(raw.get("at"))
            if at is None:
                continue
            code = str(raw.get("code") or "")
            summary = str(raw.get("summary") or "")
            invoice_id = _opt(raw.get("invoice_id"))
            digest = hashlib.sha1(summary.encode(), usedforsecurity=False).hexdigest()[:10]
            entries.append(
                TimelineEntry(
                    entry_id=f"billing:{code}:{at.isoformat()}:{invoice_id or ''}:{digest}",
                    at=at,
                    kind=_kind(raw.get("kind")),
                    code=code,
                    summary=summary,
                    source=self.name,
                    student_name=_opt(raw.get("student_name")),
                    enrollment_id=_opt(raw.get("enrollment_id")),
                    invoice_id=invoice_id,
                    invoice_ids=tuple(str(i) for i in raw.get("invoice_ids") or ()),
                    actor_id=_opt(raw.get("actor_id")),
                    reason=_opt(raw.get("reason")),
                    amount_cents=_opt_int(raw.get("amount_cents")),
                    refunded_cents=_opt_int(raw.get("refunded_cents")),
                    muted=bool(raw.get("muted")),
                )
            )
        warnings = [str(w) for w in view.get("warnings") or ()]
        return TimelineSourceResult(entries=entries, warnings=warnings)


# ------------------------------------------------------------------ coach notes


class SharedCoachNoteLike(Protocol):
    @property
    def note_id(self) -> str: ...

    @property
    def session_title(self) -> str | None: ...

    @property
    def coach_id(self) -> str | None: ...

    @property
    def coach_name(self) -> str | None: ...

    @property
    def body(self) -> str: ...

    @property
    def created_at(self) -> datetime: ...


class SharedCoachNotesPort(Protocol):
    """Coaching's shared coach notes (#665): the set the family already sees."""

    async def execute(
        self, *, academy_id: str, student_id: str, limit: int = ...
    ) -> Sequence[SharedCoachNoteLike]: ...


class CoachNotesTimelineSource:
    """Coach notes, read-only, with the coach's name (owner decision 2026-09-20)."""

    name = "coach_notes"

    def __init__(self, notes: SharedCoachNotesPort) -> None:
        self._notes = notes

    async def _for_student(
        self, scope: FamilyTimelineScope, student_id: str
    ) -> list[TimelineEntry]:
        notes = await self._notes.execute(
            academy_id=scope.academy_id, student_id=student_id, limit=SOURCE_LIMIT
        )
        child = scope.student_names.get(student_id) or "Child"
        out: list[TimelineEntry] = []
        for n in notes:
            coach = n.coach_name or "a coach"
            where = f" · {n.session_title}" if n.session_title else ""
            out.append(
                TimelineEntry(
                    entry_id=f"coach_note:{n.note_id}",
                    at=as_utc(n.created_at),
                    kind="coach",
                    code="coach:note",
                    summary=f"Coach note from {coach} · {child}{where}",
                    source=self.name,
                    detail=n.body,
                    student_id=student_id,
                    student_name=child,
                    actor_id=n.coach_id,
                    actor_name=n.coach_name,
                )
            )
        return out

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        per_child = await asyncio.gather(
            *(self._for_student(scope, sid) for sid in scope.student_ids)
        )
        return TimelineSourceResult(entries=[e for batch in per_child for e in batch])


def day_label(value: date) -> str:
    """``Sep 24`` for a follow-up due date (no year: the timeline shows it)."""
    return f"{value:%b} {value.day}"
