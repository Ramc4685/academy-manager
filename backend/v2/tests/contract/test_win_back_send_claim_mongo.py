"""Issue #778 — win-back notice sends must be idempotent per
``(academy_id, student_id, milestone_key, dropped_event_id)`` against the
REAL claim (``digest_claim.claim_digest_send``), mirroring
``test_hold_notice_send_claim_mongo.py``'s C9 coverage for hold notices.

``dropped_event_id`` scopes the claim to one departure cycle (review fix on
#778): a student who drops, gets win-back outreach, re-enrolls, and drops
again months later must be eligible for a fresh 30/60/90 series rather than
being permanently blocked by the first cycle's claims.

Run both WITH the migration 0180 unique index and WITHOUT it — the claim's
lookup-then-insert-then-verify protocol must be safe either way, per the
2026-09-02 production incident that motivated ``digest_claim.py`` in the
first place.
"""

from __future__ import annotations

import pytest

from backend.v2.composition.win_back_send_repo import MongoWinBackSendRepository
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-win-back"


async def _create_index(db) -> None:
    await db["win_back_notice_sends"].create_index(
        [
            ("academy_id", 1),
            ("student_id", 1),
            ("milestone_key", 1),
            ("dropped_event_id", 1),
        ],
        unique=True,
        name="win_back_notice_sends_key_unique",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_a_fresh_claim_succeeds_and_can_be_marked_sent(db, with_index: bool) -> None:
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoWinBackSendRepository(db)

        claim = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-0",
            milestone_key="30",
            dropped_event_id="evt-0",
        )
        assert claim is not None, "try_claim returned None — the digest_date claim key is missing"
        await repo.mark_sent(ACADEMY_ID, claim["send_id"])

    sent = await db["win_back_notice_sends"].find_one({"send_id": claim["send_id"]})
    assert sent is not None
    assert sent["status"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_two_ticks_same_milestone_send_exactly_once(db, with_index: bool) -> None:
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoWinBackSendRepository(db)

        first_claim = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-1",
            milestone_key="30",
            dropped_event_id="evt-1",
        )
        assert first_claim is not None
        await repo.mark_sent(ACADEMY_ID, first_claim["send_id"])

        # A second tick for the SAME milestone AND SAME departure event
        # (e.g. a late-running job on the next day, before the 60-day
        # milestone is due) must never re-claim a sent row.
        second_claim = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-1",
            milestone_key="30",
            dropped_event_id="evt-1",
        )
        assert second_claim is None

    sent_count = await db["win_back_notice_sends"].count_documents(
        {"academy_id": ACADEMY_ID, "student_id": "stu-1", "milestone_key": "30"}
    )
    assert sent_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_a_later_milestone_gets_its_own_claim(db, with_index: bool) -> None:
    """The 60-day milestone is not blocked by the already-sent 30-day one —
    each milestone is its own claim key."""
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoWinBackSendRepository(db)

        first = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-1",
            milestone_key="30",
            dropped_event_id="evt-1",
        )
        assert first is not None
        await repo.mark_sent(ACADEMY_ID, first["send_id"])

        second = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-1",
            milestone_key="60",
            dropped_event_id="evt-1",
        )
        assert second is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("with_index", [True, False], ids=["with_index", "without_index"])
async def test_a_second_departure_cycle_gets_its_own_claim(db, with_index: bool) -> None:
    """Review fix (#778): a second ``dropped`` event for the SAME student and
    the SAME milestone_key (student drops, gets outreach, re-enrolls, drops
    again) must not be blocked by the first cycle's claim — the claim key
    must include ``dropped_event_id``."""
    if with_index:
        await _create_index(db)
    with tenant_scope(ACADEMY_ID):
        repo = MongoWinBackSendRepository(db)

        first = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-2",
            milestone_key="30",
            dropped_event_id="evt-cycle-1",
        )
        assert first is not None
        await repo.mark_sent(ACADEMY_ID, first["send_id"])

        second = await repo.try_claim(
            academy_id=ACADEMY_ID,
            student_id="stu-2",
            milestone_key="30",
            dropped_event_id="evt-cycle-2",
        )
        assert second is not None, (
            "second departure cycle's claim was blocked by the first cycle's "
            "row — dropped_event_id is not part of the claim key"
        )
        await repo.mark_sent(ACADEMY_ID, second["send_id"])

    sent_count = await db["win_back_notice_sends"].count_documents(
        {"academy_id": ACADEMY_ID, "student_id": "stu-2", "milestone_key": "30", "status": "sent"}
    )
    assert sent_count == 2
