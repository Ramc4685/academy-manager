"""``nurture_sends`` on a real ``mongod`` (migration 0225 applied by the
``real_db`` fixture): one claim per ``(academy, contact, step)``, the unique
index refuses a duplicate row, concurrent claims produce one winner, and a
mark from another academy leaves the row untouched. Skipped when no
``mongod`` is reachable."""

from __future__ import annotations

import asyncio

import pytest
from pymongo.errors import DuplicateKeyError

from backend.v2.composition.nurture import MongoNurtureSendRepository
from backend.v2.shared.tenancy import tenant_scope

ACADEMY_ID = "acad-nurture-a"


@pytest.mark.asyncio
async def test_a_second_claim_for_the_same_step_is_refused(real_db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoNurtureSendRepository(real_db)
        first = await repo.try_claim(
            academy_id=ACADEMY_ID, subject_id="c1", nudge_key="nurture:day_2"
        )
        assert first is not None and first["channel"] == "email"
        await repo.mark_sent(ACADEMY_ID, first["send_id"])
        assert (
            await repo.try_claim(academy_id=ACADEMY_ID, subject_id="c1", nudge_key="nurture:day_2")
            is None
        )
        assert (
            await repo.try_claim(academy_id=ACADEMY_ID, subject_id="c1", nudge_key="nurture:day_7")
            is not None
        )


@pytest.mark.asyncio
async def test_concurrent_claims_have_one_winner(real_db) -> None:
    with tenant_scope(ACADEMY_ID):
        repo = MongoNurtureSendRepository(real_db)
        results = await asyncio.gather(
            *(
                repo.try_claim(academy_id=ACADEMY_ID, subject_id="c5", nudge_key="nurture:day_2")
                for _ in range(5)
            )
        )
    assert sum(r is not None for r in results) <= 1
    assert (
        await real_db["nurture_sends"].count_documents(
            {"academy_id": ACADEMY_ID, "subject_id": "c5", "digest_date": "nurture:day_2"}
        )
        <= 1
    )


@pytest.mark.asyncio
async def test_the_unique_index_refuses_a_duplicate_row(real_db) -> None:
    indexes = await real_db["nurture_sends"].index_information()
    assert "nurture_sends_key_unique" in indexes
    row = {"academy_id": ACADEMY_ID, "subject_id": "c9", "digest_date": "nurture:day_2"}
    await real_db["nurture_sends"].insert_one(dict(row))
    with pytest.raises(DuplicateKeyError):
        await real_db["nurture_sends"].insert_one(dict(row))
    await real_db["nurture_sends"].insert_one({**row, "academy_id": "acad-nurture-b"})


@pytest.mark.asyncio
async def test_a_mark_from_another_academy_leaves_the_row_untouched(real_db) -> None:
    with tenant_scope(ACADEMY_ID):
        claim = await MongoNurtureSendRepository(real_db).try_claim(
            academy_id=ACADEMY_ID, subject_id="c1", nudge_key="nurture:day_2"
        )
        assert claim is not None
    with tenant_scope("acad-nurture-b"):
        other = MongoNurtureSendRepository(real_db)
        await other.mark_sent("acad-nurture-b", claim["send_id"])
        await other.mark_failed("acad-nurture-b", claim["send_id"], "x")
    row = await real_db["nurture_sends"].find_one({"send_id": claim["send_id"]})
    assert row is not None and row["status"] == "queued" and row["academy_id"] == ACADEMY_ID
