"""``MongoAccountDeletionStore`` on a real ``mongod`` with migrations applied (mobile M5, D1).

Pins what mongomock can get wrong: the unique ``user_id`` on requests, the
array match on ``roles``, and alias-wide membership removal.
"""

from __future__ import annotations

from dataclasses import replace
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


async def test_remove_memberships_reaches_every_alias_and_keeps_the_prior_status(
    real_db,
) -> None:
    await real_db["academy_memberships"].insert_many(
        [
            _m("acad-a", "u1"),
            _m("acad-b", "fb-1", "suspended"),
            _m("acad-c", "u1", "removed"),
            _m("acad-a", "other"),
        ]
    )
    await MongoAccountDeletionStore(real_db).remove_memberships(aliases=("u1", "fb-1"), now=T0)
    rows = await real_db["academy_memberships"].find({}, {"_id": 0}).to_list(None)
    assert {
        (r["academy_id"], r["user_id"], r["status"], r.get("status_before_deletion")) for r in rows
    } == {
        ("acad-a", "u1", "removed", "active"),
        ("acad-b", "fb-1", "removed", "suspended"),
        # Removed before the request: not the request's to give back.
        ("acad-c", "u1", "removed", None),
        ("acad-a", "other", "active", None),
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


async def test_support_cancel_removes_the_request_and_restores_every_academy(real_db) -> None:
    store = MongoAccountDeletionStore(real_db)
    await real_db["academy_memberships"].insert_many(
        [_m("acad-a", "u1"), _m("acad-b", "fb-1", "suspended"), _m("acad-c", "u1", "removed")]
    )
    await store.create_request(
        replace(_request("r1", ("u1", "fb-1")), academy_ids=("acad-a", "acad-b"))
    )
    await store.remove_memberships(aliases=("u1", "fb-1"), now=T0)
    assert await store.pending_request_exists(["fb-1"])

    cancelled = await store.cancel_request("r1")
    assert cancelled is not None and cancelled.academy_ids == ("acad-a", "acad-b")
    await store.restore_memberships(aliases=cancelled.aliases, now=T0)

    assert await real_db["account_deletion_requests"].count_documents({}) == 0
    assert not await store.pending_request_exists(["fb-1"])
    rows = await real_db["academy_memberships"].find({}, {"_id": 0}).to_list(None)
    assert {(r["academy_id"], r["status"], "status_before_deletion" in r) for r in rows} == {
        ("acad-a", "active", False),
        ("acad-b", "suspended", False),
        ("acad-c", "removed", False),
    }
    # The unique user_id no longer blocks a later request by the same person.
    assert (await store.create_request(_request("r2", ("u1",)))).request_id == "r2"


async def test_support_cancel_is_refused_once_the_erasure_claimed_or_attempted_it(
    real_db,
) -> None:
    store = MongoAccountDeletionStore(real_db)
    await store.create_request(
        replace(_request("r1", ("u1", "fb-1")), academy_ids=("acad-a", "acad-b"))
    )
    claimed = await store.claim("r1", now=T0)
    assert claimed is not None and claimed.status == "running"
    # A second run (or a second tick) does not get it while the claim is fresh.
    assert await store.claim("r1", now=T0 + timedelta(minutes=5)) is None
    assert await store.cancel_request("r1") is None
    assert await store.pending_request_exists(["u1"])

    # A failed run hands the request back to the job, never to support: some
    # records may already be gone, so it is retried to the end.
    await store.record_failure("r1", step="family", error="boom", now=T0)
    row = await real_db["account_deletion_requests"].find_one({"request_id": "r1"})
    assert row["status"] == "scheduled" and row["attempts"] == 1
    assert await store.cancel_request("r1") is None
    assert await store.request_exists("r1")

    # Even an attempt that left no claim marker behind (the claim itself failed).
    await store.create_request(_request("r2", ("u2",)))
    await real_db["account_deletion_requests"].update_one(
        {"request_id": "r2"}, {"$set": {"attempts": 1}}
    )
    assert await store.cancel_request("r2") is None


async def test_mark_completed_needs_the_runs_claim(real_db) -> None:
    store = MongoAccountDeletionStore(real_db)
    await store.create_request(_request("r1", ("u1",)))
    await store.mark_completed("r1", now=T0)
    row = await real_db["account_deletion_requests"].find_one({"request_id": "r1"})
    assert row["status"] == "scheduled"

    await store.claim("r1", now=T0)
    await store.mark_completed("r1", now=T0)
    row = await real_db["account_deletion_requests"].find_one({"request_id": "r1"})
    assert row["status"] == "completed"


async def test_a_claim_left_by_a_dead_run_is_picked_up_again(real_db) -> None:
    store = MongoAccountDeletionStore(real_db)
    await store.create_request(replace(_request("r1", ("u1",)), execute_after=T0))
    await store.claim("r1", now=T0)

    assert await store.due_requests(now=T0 + timedelta(minutes=30), limit=10) == []
    later = T0 + timedelta(hours=2)
    assert [r.request_id for r in await store.due_requests(now=later, limit=10)] == ["r1"]
    assert await store.claim("r1", now=later) is not None


async def test_anonymise_identity_erases_the_persons_users_doc_in_every_academy(
    real_db,
) -> None:
    await real_db["users"].insert_many(
        [
            {
                "user_id": "u1",
                "firebase_uid": "fb-1",
                "academy_id": "acad-a",
                "display_name": "Pat",
            },
            # The same person's doc in academy B, keyed by the Firebase uid.
            {"user_id": "fb-1", "academy_id": "acad-b", "display_name": "Pat"},
            {"user_id": "u9", "academy_id": "acad-b", "display_name": "Sam"},
        ]
    )
    request = replace(_request("r1", ("u1", "fb-1")), academy_ids=("acad-a", "acad-b"))

    await MongoAccountDeletionStore(real_db).anonymise_identity(request, now=T0)

    names = {
        d["user_id"]: d["display_name"]
        async for d in real_db["users"].find({}, {"user_id": 1, "display_name": 1})
    }
    assert names == {"u1": "Deleted user", "fb-1": "Deleted user", "u9": "Sam"}
