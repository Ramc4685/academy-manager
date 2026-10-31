"""``attach_session_staff_names`` only names staff of the current academy.

``users`` is a global collection, so the only thing that makes a name
attachable here is an ``academy_memberships`` row in the *current* tenant.
Without that check a coach id that collides with (or is reused from) another
academy renders that academy's person on this academy's roster.
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.v2.composition.admin_session_staff import attach_session_staff_names
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_A = "acad-a"
ACADEMY_B = "acad-b"


def _matches(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, clause) for clause in expected):
                return False
            continue
        actual = doc.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class _FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs
        self.queries: list[dict[str, Any]] = []

    def find(self, query: dict[str, Any], _projection: dict[str, Any] | None = None) -> Any:
        self.queries.append(query)
        docs = self.docs

        async def _iter() -> Any:
            for doc in docs:
                if _matches(doc, query):
                    yield doc

        return _iter()


class _FakeDb:
    def __init__(self, collections: dict[str, _FakeCollection]) -> None:
        self._collections = collections

    def __getitem__(self, name: str) -> _FakeCollection:
        return self._collections.setdefault(name, _FakeCollection([]))


def _db() -> _FakeDb:
    return _FakeDb(
        {
            "users": _FakeCollection(
                [
                    {"user_id": "coach-1", "display_name": "Jamie Cross"},
                    {"user_id": "coach-2", "display_name": "Robin Lee"},
                    # Roster-keyed users row, firebase-keyed membership row.
                    {
                        "user_id": "coach-3",
                        "firebase_uid": "fb-3",
                        "display_name": "Sam Patel",
                    },
                ]
            ),
            # coach-1 belongs to academy B only; coach-2/coach-3 to academy A.
            "academy_memberships": _FakeCollection(
                [
                    {"academy_id": ACADEMY_B, "user_id": "coach-1", "roles": ["coach"]},
                    {"academy_id": ACADEMY_A, "user_id": "coach-2", "roles": ["coach"]},
                    {"academy_id": ACADEMY_A, "user_id": "fb-3", "roles": ["coach"]},
                ]
            ),
        }
    )


@pytest.mark.asyncio
async def test_coach_from_another_academy_is_not_named() -> None:
    db = _db()
    rows = [{"coach_id": "coach-1", "assistant_coach_ids": []}]

    with tenant_scope(ACADEMY_A):
        await attach_session_staff_names(db, rows)

    assert rows[0]["coach_name"] is None


@pytest.mark.asyncio
async def test_assistant_from_another_academy_is_dropped() -> None:
    db = _db()
    rows = [{"coach_id": "coach-2", "assistant_coach_ids": ["coach-1"]}]

    with tenant_scope(ACADEMY_A):
        await attach_session_staff_names(db, rows)

    assert rows[0]["coach_name"] == "Robin Lee"
    assert rows[0]["assistant_coach_names"] == []


@pytest.mark.asyncio
async def test_member_of_the_current_academy_is_named() -> None:
    db = _db()
    rows = [{"coach_id": "coach-1", "assistant_coach_ids": []}]

    with tenant_scope(ACADEMY_B):
        await attach_session_staff_names(db, rows)

    assert rows[0]["coach_name"] == "Jamie Cross"


@pytest.mark.asyncio
async def test_reads_are_batched_and_tenant_filtered() -> None:
    db = _db()
    rows = [
        {"coach_id": "coach-2", "assistant_coach_ids": ["coach-1"]},
        {"coach_id": "coach-2", "assistant_coach_ids": []},
    ]

    with tenant_scope(ACADEMY_A):
        await attach_session_staff_names(db, rows)

    membership_queries = db["academy_memberships"].queries
    assert len(membership_queries) == 1
    assert membership_queries[0]["academy_id"] == ACADEMY_A
    assert sorted(membership_queries[0]["user_id"]["$in"]) == ["coach-1", "coach-2"]
    assert len(db["users"].queries) == 1


@pytest.mark.asyncio
async def test_alias_keyed_membership_still_resolves_the_name() -> None:
    """A roster ``user_id`` on the session, a ``firebase_uid`` on the membership."""
    db = _db()
    rows = [{"coach_id": "coach-3", "assistant_coach_ids": []}]

    with tenant_scope(ACADEMY_A):
        await attach_session_staff_names(db, rows)

    assert rows[0]["coach_name"] == "Sam Patel"
