"""Departures design contract §4.4, C9 — two hold-reminder (or reclaim
notice) ticks on the same day must produce exactly one send per
``(enrollment_id, notice_key)``, against the REAL claim
(``digest_claim.claim_digest_send``) reused via
``MongoHoldNoticeSendRepository`` — not a hand-rolled append.

This is the reproduction for defect #2: ``try_claim`` built its QUEUED
document with a ``notice_key`` field but ``claim_digest_send`` (and its
fallback ``reclaim_retryable_send``) key their lookup, their post-insert
"am I alone" verify, and the conditional re-claim on a ``digest_date``
field the document never set. Every claim's own insert therefore failed
its own alone-check, withdrew itself, and ``try_claim`` returned ``None``
unconditionally — no hold reclaim notice or monthly reminder could ever
send. These tests fail on that bug (every claim below would return
``None`` and no row would ever reach ``sent``) and pass once
``hold_notice_send_repo.py`` sets ``digest_date``.

Run both WITH the migration 0170 unique index and WITHOUT it, because the
2026-09-02 production incident (digest_claim.py's own docstring) happened
precisely because production had never built the index the claim assumed —
the claim's lookup-then-insert-then-verify protocol must be safe either way.
"""

from __future__ import annotations

import pytest

from backend.v2.composition.hold_notice_send_repo import MongoHoldNoticeSendRepository
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-hold-notice"


async def _create_index(db) -> None:
    await db["enrollment_hold_notice_sends"].create_index(
        [("academy_id", 1), ("enrollment_id", 1), ("notice_key", 1)],
        unique=True,
        name="enrollment_hold_notice_sends_key_unique",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_c9_a_fresh_claim_succeeds_and_can_be_marked_sent(db, with_index: bool) -> None:
    """The direct reproduction: before the fix, EVERY try_claim call
    returned None (it withdrew its own insert), so this assertion alone
    fails without the digest_date fix."""
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoHoldNoticeSendRepository(db)

        claim = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-0", notice_key="hold-reclaim:1"
        )
        assert claim is not None, "try_claim returned None — the digest_date claim key is missing"
        await repo.mark_sent(claim["send_id"])

    sent = await db["enrollment_hold_notice_sends"].find_one({"send_id": claim["send_id"]})
    assert sent is not None
    assert sent["status"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_c9_two_ticks_same_notice_key_send_exactly_once(db, with_index: bool) -> None:
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoHoldNoticeSendRepository(db)

        first_claim = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="hold-reminder:1:1"
        )
        assert first_claim is not None
        await repo.mark_sent(first_claim["send_id"])

        # A second tick for the SAME notice_key (e.g. an overlapping/late
        # job run on the same day) must never re-claim a sent row.
        second_claim = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="hold-reminder:1:1"
        )
        assert second_claim is None

    sent_count = await db["enrollment_hold_notice_sends"].count_documents(
        {"academy_id": ACADEMY_ID, "enrollment_id": "enr-1", "notice_key": "hold-reminder:1:1"}
    )
    assert sent_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_c9_a_new_hold_seq_gets_its_own_claim_not_blocked_by_the_old_one(
    db, with_index: bool
) -> None:
    """A family held again later (hold_seq bumped) must be notified again —
    the notice_key embeds hold_seq precisely so this is not treated as a
    duplicate of the first hold's reminder."""
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoHoldNoticeSendRepository(db)

        first = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="hold-reminder:1:1"
        )
        assert first is not None
        await repo.mark_sent(first["send_id"])

        second = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="hold-reminder:2:1"
        )
        assert second is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_c9_skipped_row_is_never_reclaimed(db, with_index: bool) -> None:
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoHoldNoticeSendRepository(db)
        first = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="hold-reclaim:1"
        )
        assert first is not None
        await db["enrollment_hold_notice_sends"].update_one(
            {"send_id": first["send_id"]}, {"$set": {"status": "skipped"}}
        )

        second = await repo.try_claim(
            academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="hold-reclaim:1"
        )
        assert second is None
