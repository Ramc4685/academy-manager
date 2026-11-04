"""``trial_nudge_sends`` on a real ``mongod`` (migration 0216 applied by the
``real_db`` fixture): one claim per ``(academy, subject, nudge key)``, the
unique index refuses a duplicate row, and a mark from another academy leaves
the row untouched. Skipped when no ``mongod`` is reachable."""

from __future__ import annotations

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.composition.trial_nudges import MongoTrialNudgeSendRepository
from backend.v2.shared.tenancy import tenant_scope

ACADEMY_ID = "acad-nudge-a"


@pytest.mark.asyncio
async def test_a_second_claim_for_the_same_nudge_is_refused(real_db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoTrialNudgeSendRepository(real_db)
        first = await repo.try_claim(
            academy_id=ACADEMY_ID, subject_id="t1", nudge_key="trial_reminder"
        )
        assert first is not None
        await repo.mark_sent(ACADEMY_ID, first["send_id"])

        assert (
            await repo.try_claim(academy_id=ACADEMY_ID, subject_id="t1", nudge_key="trial_reminder")
            is None
        )
        # Another nudge for the same trial, and the same nudge for another
        # trial, are their own claims.
        assert (
            await repo.try_claim(academy_id=ACADEMY_ID, subject_id="t1", nudge_key="trial_no_show")
            is not None
        )
        assert (
            await repo.try_claim(academy_id=ACADEMY_ID, subject_id="t2", nudge_key="trial_reminder")
            is not None
        )

    assert (
        await real_db["trial_nudge_sends"].count_documents(
            {"academy_id": ACADEMY_ID, "subject_id": "t1", "digest_date": "trial_reminder"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_the_unique_index_refuses_a_duplicate_row(real_db) -> None:
    indexes = await real_db["trial_nudge_sends"].index_information()
    assert "trial_nudge_sends_key_unique" in indexes
    row = {"academy_id": ACADEMY_ID, "subject_id": "t9", "digest_date": "trial_reminder"}
    await real_db["trial_nudge_sends"].insert_one(dict(row))
    with pytest.raises(DuplicateKeyError):
        await real_db["trial_nudge_sends"].insert_one(dict(row))
    # The same key under another academy is a different claim.
    await real_db["trial_nudge_sends"].insert_one({**row, "academy_id": "acad-nudge-b"})


@pytest.mark.asyncio
async def test_a_mark_from_another_academy_leaves_the_row_untouched(real_db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoTrialNudgeSendRepository(real_db)
        claim = await repo.try_claim(
            academy_id=ACADEMY_ID, subject_id="t1", nudge_key="trial_reminder"
        )
        assert claim is not None
    with tenant_scope("acad-nudge-b"):
        other = MongoTrialNudgeSendRepository(real_db)
        await other.mark_sent("acad-nudge-b", claim["send_id"])
        await other.mark_failed("acad-nudge-b", claim["send_id"], "x")

    row = await real_db["trial_nudge_sends"].find_one({"send_id": claim["send_id"]})
    assert row is not None
    assert row["status"] == "queued"
    assert row["academy_id"] == ACADEMY_ID


@pytest.mark.asyncio
async def test_a_failed_send_is_reclaimed_but_a_skipped_one_is_final(real_db) -> None:
    # The fakes in the application tests mirror this: "failed" retries on a
    # later tick, "skipped" (no address, opted out) never does.
    with tenant_scope(ACADEMY_ID):
        repo = MongoTrialNudgeSendRepository(real_db)
        failed = await repo.try_claim(academy_id=ACADEMY_ID, subject_id="f1", nudge_key="k")
        skipped = await repo.try_claim(academy_id=ACADEMY_ID, subject_id="s1", nudge_key="k")
        assert failed is not None and skipped is not None
        await repo.mark_failed(ACADEMY_ID, failed["send_id"], "send_failed")
        await repo.mark_failed(ACADEMY_ID, skipped["send_id"], "skipped", retryable=False)

        assert await repo.try_claim(academy_id=ACADEMY_ID, subject_id="f1", nudge_key="k")
        assert await repo.try_claim(academy_id=ACADEMY_ID, subject_id="s1", nudge_key="k") is None
