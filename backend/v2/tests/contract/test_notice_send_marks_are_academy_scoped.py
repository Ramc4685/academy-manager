"""The notice-send claim repos mark rows by ``(academy_id, send_id)`` (#880 pattern).

Found by the own-collection check added to ``test_no_raw_tenant_mongo_access``
in the same change: the hold, absence and win-back send repos are structural
copies of the digest-send repo and updated by a bare ``send_id`` too.
"""

from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from backend.v2.composition.absence_notifications import MongoAbsenceNoticeSendRepository
from backend.v2.composition.hold_notice_send_repo import MongoHoldNoticeSendRepository
from backend.v2.composition.win_back_send_repo import MongoWinBackSendRepository
from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY_ID = "acad-notice-a"
OTHER = "acad-notice-b"


async def _claim(repo_cls, repo):  # type: ignore[no-untyped-def]
    if repo_cls is MongoHoldNoticeSendRepository:
        return await repo.try_claim(academy_id=ACADEMY_ID, enrollment_id="enr-1", notice_key="k")
    if repo_cls is MongoAbsenceNoticeSendRepository:
        return await repo.try_claim(academy_id=ACADEMY_ID, notice_id="n-1", audience="parent")
    return await repo.try_claim(
        academy_id=ACADEMY_ID, student_id="stu-1", milestone_key="30", dropped_event_id="ev-1"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mark", ["mark_sent", "mark_failed"])
@pytest.mark.parametrize(
    "repo_cls",
    [MongoHoldNoticeSendRepository, MongoAbsenceNoticeSendRepository, MongoWinBackSendRepository],
)
async def test_mark_from_another_academy_leaves_the_row_untouched(repo_cls, mark: str) -> None:  # type: ignore[no-untyped-def]
    db = AsyncMongoMockClient()["notice_test"]
    coll = db[repo_cls.collection_name]

    with tenant_scope(ACADEMY_ID):
        repo = repo_cls(db)
        claim = await _claim(repo_cls, repo)
        assert claim is not None
    send_id = claim["send_id"]

    with tenant_scope(OTHER):
        other = repo_cls(db)
        if mark == "mark_sent":
            await other.mark_sent(OTHER, send_id)
        else:
            await other.mark_failed(OTHER, send_id, "boom", retryable=False)
    row = await coll.find_one({"send_id": send_id})
    assert row["status"] == str(DigestSendStatus.QUEUED)

    with tenant_scope(ACADEMY_ID):
        if mark == "mark_sent":
            await repo.mark_sent(ACADEMY_ID, send_id)
            expected = DigestSendStatus.SENT
        else:
            await repo.mark_failed(ACADEMY_ID, send_id, "boom", retryable=False)
            expected = DigestSendStatus.FAILED
    row = await coll.find_one({"send_id": send_id})
    assert row["status"] == str(expected)
