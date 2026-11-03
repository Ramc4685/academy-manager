"""``MongoAccountDeletionStore`` on a real ``mongod`` with migrations applied (mobile M5, D1).

Pins what mongomock can get wrong: the unique ``user_id`` on requests, the
array match on ``roles``, and alias-wide membership removal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.identity.domain.account_deletion import AccountDeletionRequest
from backend.v2.contexts.identity.infrastructure.mongo_account_deletion_store import (
    MongoAccountDeletionStore,
)

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _m(academy_id: str, user_id: str, status: str = "active", roles=("parent",)) -> dict:
    return {
        "membership_id": f"m-{academy_id}-{user_id}",
        "academy_id": academy_id,
        "user_id": user_id,
        "roles": list(roles),
        "status": status,
    }


def _occ(n: int, academy_id: str, start_at: datetime, status: str) -> dict:
    return {
        "occurrence_id": f"o{n}",
        "session_id": f"s{n}",
        "academy_id": academy_id,
        "start_at": start_at,
        "end_at": start_at + timedelta(hours=1),
        "status": status,
        "scheduled_coach_id": "u1",
    }


def _request(request_id: str, aliases: tuple[str, ...]) -> AccountDeletionRequest:
    return AccountDeletionRequest(
        request_id=request_id,
        user_id="u1",
        auth_uid="fb-1",
        email="p@example.com",
        aliases=aliases,
        academy_ids=("acad-a",),
        requested_at=T0,
        execute_after=T0 + timedelta(days=14),
    )


async def test_load_account_gathers_aliases_and_memberships_across_academies(real_db) -> None:
    await real_db["users"].insert_many(
        [
            {"user_id": "u1", "firebase_uid": "fb-1", "email": "p@example.com"},
            # Same person's doc in another academy, found by email.
            {"user_id": "roster-7", "email": "p@example.com"},
        ]
    )
    await real_db["academy_memberships"].insert_many(
        [
            _m("acad-a", "u1", "active", ("parent",)),
            _m("acad-b", "roster-7", roles=("coach",)),
            _m("acad-a", "someone", "active", ("owner",)),
        ]
    )
    account = await MongoAccountDeletionStore(real_db).load_account(
        user_id="u1", email="p@example.com"
    )
    assert account.auth_uid == "fb-1"
    assert {"u1", "fb-1", "roster-7"} <= set(account.aliases)
    assert sorted((m.academy_id, m.roles) for m in account.memberships) == [
        ("acad-a", ("parent",)),
        ("acad-b", ("coach",)),
    ]


async def test_one_request_per_account_and_a_repeat_returns_it(real_db) -> None:
    store = MongoAccountDeletionStore(real_db)
    first = await store.create_request(_request("r1", ("u1", "fb-1")))
    again = await store.create_request(_request("r2", ("u1", "fb-1")))
    assert first.request_id == again.request_id == "r1"
    assert await real_db["account_deletion_requests"].count_documents({}) == 1
    found = await store.find_request(("fb-1", "u1"))
    assert found is not None and found.execute_after == T0 + timedelta(days=14)


async def test_other_owner_check_ignores_the_leaver_and_inactive_rows(real_db) -> None:
    store = MongoAccountDeletionStore(real_db)
    await real_db["academy_memberships"].insert_many(
        [
            _m("acad-a", "u1", "active", ("owner",)),
            _m("acad-a", "x", "suspended", ("owner",)),
            _m("acad-b", "y", "active", ("owner",)),
        ]
    )
    assert not await store.other_active_owner_exists(academy_id="acad-a", aliases=("u1",))
    await real_db["academy_memberships"].insert_one(
        _m(
            "acad-a",
            "z",
            "active",
            (
                "admin",
                "owner",
            ),
        )
    )
    assert await store.other_active_owner_exists(academy_id="acad-a", aliases=("u1",))


async def test_remove_memberships_reaches_every_alias_and_academy_only(real_db) -> None:
    await real_db["academy_memberships"].insert_many(
        [
            _m("acad-a", "u1"),
            _m("acad-b", "fb-1", "suspended"),
            _m("acad-a", "other"),
        ]
    )
    await MongoAccountDeletionStore(real_db).remove_memberships(aliases=("u1", "fb-1"), now=T0)
    rows = await real_db["academy_memberships"].find({}, {"_id": 0}).to_list(None)
    assert {(r["user_id"], r["status"]) for r in rows} == {
        ("u1", "removed"),
        ("fb-1", "removed"),
        ("other", "active"),
    }


async def test_upcoming_coaching_counts_future_live_occurrences_in_that_academy(real_db) -> None:
    now = datetime.now(UTC)
    await real_db["session_occurrences"].insert_many(
        [
            _occ(1, "acad-a", now + timedelta(days=1), "scheduled"),
            _occ(2, "acad-a", now - timedelta(days=1), "scheduled"),
            _occ(3, "acad-a", now + timedelta(days=1), "cancelled"),
            _occ(4, "acad-b", now + timedelta(days=1), "scheduled"),
        ]
    )
    store = MongoAccountDeletionStore(real_db)
    assert await store.upcoming_coaching_count(academy_id="acad-a", aliases=("u1",)) == 1
    assert await store.upcoming_coaching_count(academy_id="acad-c", aliases=("u1",)) == 0
