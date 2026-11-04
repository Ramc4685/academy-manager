"""``GetFamilyTimeline``: the family index decides "is this a family here"
(404 otherwise, #664), every source is asked with the canonical id, the
children and the parent's aliases, a failing source is a warning (never a
500 and never a silent gap), and billing's own timeline and the shared coach
notes are adapted as sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.crm.application.timeline import (
    BillingTimelineSource,
    CoachNotesTimelineSource,
    FamilyTimelineScope,
    GetFamilyTimeline,
    TimelineCursor,
    TimelineEntry,
    TimelineSourceResult,
)
from backend.v2.contexts.crm.domain.errors import FamilyNotFound
from backend.v2.contexts.crm.domain.family_index import FamilyChild, FamilyRecord

A = "acad-a"
T0 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)


def _record(family_id: str = "p-1") -> FamilyRecord:
    return FamilyRecord(
        family_id=family_id,
        parent_name="Testparent One",
        email=None,
        phone=None,
        has_account=True,
        children=(
            FamilyChild(student_id="s-1", name="Kid Alpha", lifecycle="active"),
            FamilyChild(student_id="s-2", name="Kid Beta", lifecycle="paused"),
        ),
        stage="active",
    )


class Directory:
    def __init__(self) -> None:
        self.rows = {(A, "p-1"): _record(), (A, "fb-p-1"): _record()}

    async def find_record(self, academy_id: str, family_id: str) -> FamilyRecord | None:
        return self.rows.get((academy_id, family_id))

    async def names(self, academy_id: str) -> Mapping[str, str | None]:
        return {"p-1": "Testparent One", "p-2": "Testparent Two"} if academy_id == A else {}


@dataclass(frozen=True)
class Resolved:
    canonical_id: str
    aliases: frozenset[str]
    display_name: str | None = None
    email: str | None = None


class Aliases:
    async def resolve_parent_aliases(self, raw_ids: Sequence[str]) -> Mapping[str, Any]:
        return {i: Resolved(i, frozenset({i, "fb-p-1"})) for i in raw_ids}


class Source:
    def __init__(self, name: str, entries: Sequence[TimelineEntry] = (), fail: bool = False):
        self.name = name
        self.entries = entries
        self.fail = fail
        self.scopes: list[FamilyTimelineScope] = []

    async def fetch(self, scope: FamilyTimelineScope) -> TimelineSourceResult:
        self.scopes.append(scope)
        if self.fail:
            raise RuntimeError("down")
        return TimelineSourceResult(entries=self.entries)


def _e(entry_id: str, minutes: int) -> TimelineEntry:
    return TimelineEntry(
        entry_id=entry_id,
        at=T0 + timedelta(minutes=minutes),
        kind="crm",
        code="crm:note_added",
        summary=entry_id,
        source="x",
    )


async def test_alias_resolves_to_the_family_and_sources_get_the_scope() -> None:
    src = Source("one", [_e("a", 1), _e("b", 2)])
    uc = GetFamilyTimeline(Directory(), Aliases(), [src])
    page = await uc.execute(academy_id=A, parent_id="fb-p-1")
    assert page.family_id == "p-1"
    assert [e.entry_id for e in page.entries] == ["b", "a"]
    scope = src.scopes[0]
    assert scope.academy_id == A
    assert scope.parent_aliases == ("p-1", "fb-p-1")
    assert scope.student_ids == ("s-1", "s-2")
    assert scope.student_names["s-2"] == "Kid Beta"
    assert scope.family_names["p-2"] == "Testparent Two"
    assert page.next_cursor is None and page.warnings == []


async def test_another_academys_family_is_not_found() -> None:
    uc = GetFamilyTimeline(Directory(), Aliases(), [Source("one")])
    with pytest.raises(FamilyNotFound):
        await uc.execute(academy_id="acad-b", parent_id="p-1")


async def test_a_failing_source_is_a_warning_and_the_rest_still_show() -> None:
    uc = GetFamilyTimeline(
        Directory(), Aliases(), [Source("good", [_e("a", 1)]), Source("attendance", fail=True)]
    )
    page = await uc.execute(academy_id=A, parent_id="p-1")
    assert [e.entry_id for e in page.entries] == ["a"]
    assert page.warnings == ["attendance_unavailable"]


async def test_paging_passes_the_cursor_time_to_sources() -> None:
    src = Source("one", [_e(f"e{i}", i) for i in range(5)])
    uc = GetFamilyTimeline(Directory(), Aliases(), [src])
    first = await uc.execute(academy_id=A, parent_id="p-1", limit=2)
    assert [e.entry_id for e in first.entries] == ["e4", "e3"]
    assert first.next_cursor
    cursor = TimelineCursor.decode(first.next_cursor)
    second = await uc.execute(academy_id=A, parent_id="p-1", before=cursor, limit=2)
    assert [e.entry_id for e in second.entries] == ["e2", "e1"]
    assert src.scopes[-1].before == T0 + timedelta(minutes=3)


class BillingReader:
    def __init__(self, view: dict[str, Any] | None) -> None:
        self.view = view
        self.asked: list[str] = []

    async def build(self, parent_id: str) -> dict[str, Any] | None:
        self.asked.append(parent_id)
        return self.view


def _scope() -> FamilyTimelineScope:
    return FamilyTimelineScope(
        academy_id=A,
        family_id="p-1",
        parent_aliases=("p-1",),
        student_ids=("s-1",),
        student_names={"s-1": "Kid Alpha"},
    )


async def test_billing_timeline_is_one_source_with_stable_ids() -> None:
    reader = BillingReader(
        {
            "timeline": [
                {
                    "at": "2026-08-04T14:00:00Z",
                    "kind": "money",
                    "code": "payment_received",
                    "summary": "$60 received · Visa ••4242",
                    "invoice_id": None,
                    "invoice_ids": ["inv-aug"],
                    "enrollment_id": None,
                    "amount_cents": 6000,
                    "refunded_cents": 0,
                    "muted": False,
                },
                {"at": None, "kind": "money", "code": "broken", "summary": "x"},
            ],
            "warnings": ["audit_unavailable"],
        }
    )
    source = BillingTimelineSource(reader)
    first = await source.fetch(_scope())
    again = await source.fetch(_scope())
    assert reader.asked == ["p-1", "p-1"]
    assert len(first.entries) == 1
    entry = first.entries[0]
    assert entry.kind == "money" and entry.amount_cents == 6000
    assert entry.invoice_ids == ("inv-aug",)
    assert entry.at == datetime(2026, 8, 4, 14, 0, tzinfo=UTC)
    assert entry.entry_id == again.entries[0].entry_id
    assert list(first.warnings) == ["audit_unavailable"]

    assert (await BillingTimelineSource(BillingReader(None)).fetch(_scope())).entries == ()


@dataclass(frozen=True)
class Note:
    note_id: str
    session_title: str | None
    coach_id: str | None
    coach_name: str | None
    body: str
    created_at: datetime


class CoachNotes:
    async def execute(self, *, academy_id: str, student_id: str, limit: int = 50) -> list[Note]:
        assert academy_id == A
        return [Note("n-1", "Sat Beginners", "c-1", "Coach Testcoach", "Great footwork", T0)]


async def test_coach_notes_show_read_only_with_the_coachs_name() -> None:
    result = await CoachNotesTimelineSource(CoachNotes()).fetch(_scope())
    (entry,) = result.entries
    assert entry.kind == "coach"
    assert entry.summary == "Coach note from Coach Testcoach · Kid Alpha · Sat Beginners"
    assert entry.detail == "Great footwork"
    assert entry.actor_name == "Coach Testcoach"
