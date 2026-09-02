"""The digest claim must hold WITHOUT the unique index (2026-09-02 incident).

Production never ran migrations 0125/0148 (``V2_RUN_MIGRATIONS_ON_BOOT=false``,
registry stopped at 0122), so ``coach_digest_sends`` / ``parent_digest_sends``
carried only the ``_id`` index. ``try_claim`` was an insert-first lock whose
only guard was ``DuplicateKeyError`` from that unique index: with no index the
insert never conflicted, every hourly tick after the digest hour (``>=`` since
PR #558) inserted a fresh QUEUED row, and every coach and parent was e-mailed
once an hour for the rest of the day.

These tests run the real repositories on a bare mongomock database and
deliberately do NOT install the migrations. Each one pins an arm of
``reclaim_retryable_send`` so the pre-insert lookup in ``try_claim`` cannot
regress into "index or nothing" again.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import pytest
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    SendCoachDailyDigestCommand,
)
from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.mongo_digest_send_repo import (
    MongoDigestSendRepository,
)
from backend.v2.contexts.communications.infrastructure.mongo_parent_digest_send_repo import (
    MongoParentDigestSendRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from backend.v2.tests.infrastructure.test_digest_send_retry import _digest, _ScriptedSender
from mongomock_motor import AsyncMongoMockClient

ACADEMY_ID = "acad-digest-no-index"
DIGEST_DATE = "2026-09-02"

_REPOS = [
    pytest.param(MongoDigestSendRepository, "coach_digest_sends", id="coach"),
    pytest.param(MongoParentDigestSendRepository, "parent_digest_sends", id="parent"),
]


def _bare_db() -> Any:
    """A database with only the implicit ``_id`` index — no migration applied."""
    return AsyncMongoMockClient()["digest_no_index_test"]


async def _assert_only_indexes_are_id(db: Any, collection: str) -> None:
    # mongomock reports no indexes at all (not even ``_id_``) for a collection
    # that holds no documents, so the guard is "nothing beyond ``_id_``".
    names = {idx["name"] async for idx in db[collection].list_indexes()}
    assert names <= {"_id_"}, names


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_sent_row_is_not_reclaimed_without_the_index(repo_cls: Any, collection: str) -> None:
    """The incident case: a delivered digest must never be claimed again."""
    db = _bare_db()
    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        first = await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        assert first is not None
        await repo.mark_sent(first.digest_id, "prov-1")

        assert await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE) is None
        assert await db[collection].count_documents({}) == 1
    await _assert_only_indexes_are_id(db, collection)


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_skipped_row_is_not_reclaimed_without_the_index(
    repo_cls: Any, collection: str
) -> None:
    db = _bare_db()
    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        first = await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        assert first is not None
        await repo.mark_skipped_empty(first.digest_id)

        assert await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE) is None
        assert await db[collection].count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_fresh_queued_row_is_not_reclaimed_without_the_index(
    repo_cls: Any, collection: str
) -> None:
    """An in-flight send must not be stolen by a concurrent tick."""
    db = _bare_db()
    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        first = await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        assert first is not None

        assert await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE) is None
        assert await db[collection].count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_failed_row_is_still_retried_without_the_index(
    repo_cls: Any, collection: str
) -> None:
    """The guard must not over-correct: the #435 retry ladder still works."""
    db = _bare_db()
    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        first = await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        assert first is not None
        await repo.mark_failed(first.digest_id, "resend timeout")

        retry = await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        assert retry is not None
        assert retry.digest_id == first.digest_id
        assert retry.status == DigestSendStatus.QUEUED
        assert retry.attempt_count == 2
        assert await db[collection].count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_test_send_rows_do_not_block_the_daily_claim_without_the_index(
    repo_cls: Any, collection: str
) -> None:
    """Admin test sends live under ``<date>#test:<ulid>``; the exact-match
    lookup must not mistake one for the day's real claim."""
    db = _bare_db()
    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        test_send = await repo.record_test_send(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        await repo.mark_sent(test_send.digest_id, "prov-test")

        daily = await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE)
        assert daily is not None
        assert daily.digest_id != test_send.digest_id
        assert await db[collection].count_documents({}) == 2


@pytest.mark.asyncio
async def test_hourly_ticks_send_exactly_once_without_the_index() -> None:
    """Three ticks after the digest hour: one failure, one delivery, then quiet.

    Mirrors ``test_next_tick_recovers_a_failed_send_without_duplicating_it`` but
    with no unique index installed — the shape of the production incident.
    """
    db = _bare_db()
    command = SendCoachDailyDigestCommand(academy_id=ACADEMY_ID, digest_date=date(2026, 9, 2))
    sender = _ScriptedSender(fail_first=1)

    with tenant_scope(ACADEMY_ID):
        first = await _digest(db, sender).execute(command)
        assert (first.sent, first.failed) == (0, 1)

        second = await _digest(db, sender).execute(command)
        assert (second.sent, second.failed) == (1, 0)

        third = await _digest(db, sender).execute(command)
        assert (third.sent, third.already_claimed) == (0, 1)

        assert sender.sent == ["coach@example.test"]
        assert await db["coach_digest_sends"].count_documents({}) == 1
    await _assert_only_indexes_are_id(db, "coach_digest_sends")


# ---------------------------------------------------------------------------
# Concurrency: the claim must settle a race WITHOUT the unique index
# ---------------------------------------------------------------------------
#
# mongomock_motor's awaits never actually suspend, so two coroutines under
# ``asyncio.gather`` would run back to back and never interleave. The wrapper
# below yields to the event loop after each named collection call, which makes
# the interleaving deterministic: with ``yield_after={"find_one"}`` both claims
# miss on the lookup before either inserts (the review reproduction); adding
# ``insert_one`` makes both insert before either verifies; adding
# ``count_documents`` makes both observe the collision.


class _YieldingCollection:
    def __init__(self, inner: Any, yield_after: set[str]) -> None:
        self._inner = inner
        self._yield_after = yield_after

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if name not in self._yield_after:
            return attr

        async def call(*args: Any, **kwargs: Any) -> Any:
            result = await attr(*args, **kwargs)
            await asyncio.sleep(0)
            return result

        return call


async def _race(repo_cls: Any, collection: str, yield_after: set[str]) -> tuple[list[Any], Any]:
    db = _bare_db()
    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        repo.collection = _YieldingCollection(repo.collection, yield_after)
        claims = await asyncio.gather(
            repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE),
            repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE),
        )
    await _assert_only_indexes_are_id(db, collection)
    return [c for c in claims if c is not None], db


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_two_claims_that_both_miss_the_lookup_yield_one_claim(
    repo_cls: Any, collection: str
) -> None:
    """The review reproduction: both callers pass the lookup before either
    inserts. Only one may hold the claim and only one row may survive."""
    won, db = await _race(repo_cls, collection, {"find_one"})
    assert len(won) == 1
    rows = await db[collection].find({}).to_list(None)
    assert [r["digest_id"] for r in rows] == [won[0].digest_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_two_claims_that_both_insert_yield_one_claim(repo_cls: Any, collection: str) -> None:
    """Both rows exist before either caller verifies: the first to verify sees
    two, withdraws its own row and is refused by the re-claim; the second then
    sees itself alone and wins."""
    won, db = await _race(repo_cls, collection, {"find_one", "insert_one"})
    assert len(won) == 1
    rows = await db[collection].find({}).to_list(None)
    assert [r["digest_id"] for r in rows] == [won[0].digest_id]


@pytest.mark.asyncio
@pytest.mark.parametrize(("repo_cls", "collection"), _REPOS)
async def test_two_claims_that_both_see_the_collision_send_nothing_then_recover(
    repo_cls: Any, collection: str
) -> None:
    """The one interleaving with no winner: both observe two rows, both
    withdraw. That costs the tick, never a duplicate — and the next tick
    claims normally because no row is left behind."""
    won, db = await _race(repo_cls, collection, {"find_one", "insert_one", "count_documents"})
    assert won == []
    assert await db[collection].count_documents({}) == 0

    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        assert await repo.try_claim(ACADEMY_ID, "recipient-1", DIGEST_DATE) is not None
    assert await db[collection].count_documents({}) == 1
