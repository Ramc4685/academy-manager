"""Owner daily brief (issue #776)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.v2.contexts.enrollment.domain.events import EnrollmentLifecycleEventType
from backend.v2.shared.observability.owner_daily_brief import (
    DEPARTURE_EVENT_TYPES,
    collect_owner_daily_brief,
    render_owner_daily_brief,
)

NOW = datetime(2026, 9, 13, 7, 0, tzinfo=UTC)
RECENT = NOW - timedelta(hours=2)
OLD = NOW - timedelta(days=5)
ACADEMY = "acad-1"
OTHER = "acad-2"


class _FakeCollection:
    def __init__(
        self,
        docs: list[dict[str, Any]],
        *,
        aggregate_rows: list[dict[str, Any]] | None = None,
        fail: bool = False,
    ) -> None:
        self.docs = docs
        self.aggregate_rows = aggregate_rows or []
        self.fail = fail
        self.queries: list[dict[str, Any]] = []

    async def count_documents(self, query: dict[str, Any]) -> int:
        if self.fail:
            raise RuntimeError("collection unreadable")
        self.queries.append(query)
        return sum(1 for doc in self.docs if _matches(doc, query))

    def aggregate(self, pipeline: list[dict[str, Any]]) -> Any:
        """Canned group rows; each carries the tenant it was grouped from
        and is only returned when the pipeline's ``$match`` selects it."""
        rows, fail = self.aggregate_rows, self.fail
        match: dict[str, Any] = next(
            (stage["$match"] for stage in pipeline if "$match" in stage), {}
        )

        async def _iter() -> Any:
            if fail:
                raise RuntimeError("collection unreadable")
            for row in rows:
                if row.get("academy_id") == match.get("academy_id"):
                    yield {k: v for k, v in row.items() if k != "academy_id"}

        return _iter()

    async def find_one(
        self, query: dict[str, Any], _projection: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if self.fail:
            raise RuntimeError("collection unreadable")
        return next((doc for doc in self.docs if _matches(doc, query)), None)

    def find(self, query: dict[str, Any], _projection: dict[str, Any] | None = None) -> Any:
        docs, fail = self.docs, self.fail

        async def _iter() -> Any:
            if fail:
                raise RuntimeError("collection unreadable")
            for doc in docs:
                if _matches(doc, query):
                    yield doc

        return _iter()


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, branch) for branch in expected):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict):
            if "$exists" in expected and (key in doc) != expected["$exists"]:
                return False
            if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                return False
            if "$gt" in expected and (actual is None or actual <= expected["$gt"]):
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class _FakeDb:
    def __init__(self, collections: dict[str, _FakeCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection([]))


def _db(**overrides: _FakeCollection) -> Any:
    # ``Any``: the fake stands in for AsyncIOMotorDatabase at every call site.
    """One academy's signals, plus another academy's copy of every row that
    must never leak into ``ACADEMY``'s brief."""
    a, o = ACADEMY, OTHER
    collections: dict[str, _FakeCollection] = {
        "academies": _FakeCollection([{"academy_id": a, "display_name": "Alpha Academy"}]),
        "enrollments": _FakeCollection(
            [
                {"academy_id": a, "enrolled_at": RECENT},
                {"academy_id": a, "enrolled_at": OLD},
                {"academy_id": o, "enrolled_at": RECENT},
            ]
        ),
        "enrollment_events": _FakeCollection(
            [],
            aggregate_rows=[
                {"academy_id": a, "_id": "moved away", "count": 2},
                {"academy_id": a, "_id": None, "count": 1},
                {"academy_id": o, "_id": "cost", "count": 9},
            ],
        ),
        "onboarding_applications": _FakeCollection(
            [
                {"academy_id": a, "status": "PENDING_APPROVAL"},
                {"academy_id": a, "status": "APPROVED"},
                {"academy_id": o, "status": "PENDING_APPROVAL"},
            ]
        ),
        "payments": _FakeCollection(
            [
                {"academy_id": a, "status": "failed", "updated_at": RECENT},
                {"academy_id": a, "status": "failed", "updated_at": OLD},
                {"academy_id": a, "status": "succeeded", "updated_at": RECENT},
                {"academy_id": o, "status": "failed", "updated_at": RECENT},
            ]
        ),
        "invoices": _FakeCollection(
            [
                {"academy_id": a, "status": "open", "balance_due_cents": 4500},
                {"academy_id": a, "status": "paid", "balance_due_cents": 0},
                {"academy_id": a, "status": "open", "balance_due_cents": 0},
                {"academy_id": o, "status": "open", "balance_due_cents": 4500},
            ]
        ),
        "students": _FakeCollection(
            [
                {"academy_id": a, "student_id": "s-1", "parent_id": "p-1"},
                {"academy_id": a, "student_id": "s-2", "parent_id": "p-2"},
                {"academy_id": o, "student_id": "s-9", "parent_id": "p-9"},
            ]
        ),
        "waiver_acceptances": _FakeCollection([{"academy_id": a, "student_id": "s-1"}]),
        "users": _FakeCollection(
            [
                {"academy_id": a, "user_id": "p-1", "email": "p1@example.test"},
                {"academy_id": a, "user_id": "p-2", "email": "p2@example.test"},
                {"academy_id": o, "user_id": "p-9", "email": "p9@example.test"},
            ]
        ),
        "family_contacts": _FakeCollection([]),
        "email_suppressions": _FakeCollection(
            [
                {"email": "p1@example.test", "active": True, "first_seen_at": RECENT},
                {"email": "p2@example.test", "active": True, "first_seen_at": OLD},
                {"email": "p2@example.test", "active": False, "first_seen_at": RECENT},
                {"email": "p9@example.test", "active": True, "first_seen_at": RECENT},
            ]
        ),
    }
    collections.update(overrides)
    return _FakeDb(collections)


@pytest.mark.asyncio
async def test_brief_collects_every_owner_signal() -> None:
    brief = await collect_owner_daily_brief(_db(), academy_id=ACADEMY, now=NOW)

    assert brief.new_enrollments == 1
    assert brief.departures_total == 3
    assert brief.approvals_waiting == 1
    assert brief.payments_failed == 1
    # An `open` invoice with nothing left owing is settled, not outstanding.
    assert brief.invoices_open == 1
    assert brief.waivers_missing == 1
    assert brief.emails_undeliverable == 1
    assert brief.academy_name == "Alpha Academy"
    assert brief.errors == []


@pytest.mark.asyncio
async def test_brief_requires_an_academy() -> None:
    with pytest.raises(ValueError):
        await collect_owner_daily_brief(_db(), academy_id="", now=NOW)


@pytest.mark.asyncio
async def test_missing_academy_name_falls_back_to_the_id() -> None:
    brief = await collect_owner_daily_brief(
        _db(academies=_FakeCollection([])), academy_id=ACADEMY, now=NOW
    )

    assert brief.academy_name == ACADEMY
    subject, _ = render_owner_daily_brief(brief)
    assert subject.endswith(f"· {ACADEMY}")


@pytest.mark.asyncio
async def test_departures_carry_their_reason() -> None:
    brief = await collect_owner_daily_brief(_db(), academy_id=ACADEMY, now=NOW)

    assert [(row.reason, row.count) for row in brief.departures] == [
        ("moved away", 2),
        ("no reason recorded", 1),
    ]
    _, body = render_owner_daily_brief(brief)
    assert "moved away" in body


@pytest.mark.asyncio
async def test_brief_degrades_when_one_collection_is_unreadable() -> None:
    brief = await collect_owner_daily_brief(
        _db(payments=_FakeCollection([], fail=True)), academy_id=ACADEMY, now=NOW
    )

    assert brief.payments_failed == 0
    assert any("money" in err for err in brief.errors)
    # The rest of the brief still arrives.
    assert brief.approvals_waiting == 1


@pytest.mark.asyncio
async def test_a_quiet_day_does_not_claim_action_is_needed() -> None:
    quiet = _db(
        enrollment_events=_FakeCollection([], aggregate_rows=[]),
        onboarding_applications=_FakeCollection([]),
        payments=_FakeCollection([]),
        students=_FakeCollection([]),
        waiver_acceptances=_FakeCollection([]),
        email_suppressions=_FakeCollection([]),
    )
    brief = await collect_owner_daily_brief(quiet, academy_id=ACADEMY, now=NOW)

    assert brief.has_attention_items is False
    subject, body = render_owner_daily_brief(brief)
    assert "nothing waiting" in subject
    assert "Nothing is waiting on a decision today." in body


@pytest.mark.asyncio
async def test_new_enrollments_alone_never_flip_the_subject_line() -> None:
    busy = _db(
        enrollment_events=_FakeCollection([], aggregate_rows=[]),
        onboarding_applications=_FakeCollection([]),
        payments=_FakeCollection([]),
        students=_FakeCollection([]),
        waiver_acceptances=_FakeCollection([]),
        email_suppressions=_FakeCollection([]),
    )
    brief = await collect_owner_daily_brief(busy, academy_id=ACADEMY, now=NOW)

    assert brief.new_enrollments == 1
    assert brief.has_attention_items is False


def test_departure_events_match_the_domain() -> None:
    """``shared/`` may not import enrollment, so the list is duplicated.

    This pins the copy to the real literal: a new terminal transition added to
    the domain without updating the brief would silently stop being reported.
    """
    domain_types = set(EnrollmentLifecycleEventType.__args__)  # type: ignore[attr-defined]
    assert set(DEPARTURE_EVENT_TYPES) <= domain_types
