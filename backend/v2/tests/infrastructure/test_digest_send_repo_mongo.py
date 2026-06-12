"""End-to-end test of the coach digest-send Mongo repo against mongomock.

Exercises the real TenantScopedRepository-backed repo, the 0125 unique index,
and the claim-based idempotency guard through an actual (mock) Mongo driver.
"""

from __future__ import annotations

import importlib

import pytest
from backend.v2.contexts.communications.domain.models import DigestSendStatus
from backend.v2.contexts.communications.infrastructure.mongo_digest_send_repo import (
    MongoDigestSendRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope
from mongomock_motor import AsyncMongoMockClient

ACADEMY_ID = "acad-digest-test"
DIGEST_DATE = "2026-06-12"

_migration = importlib.import_module("backend.v2.migrations.0125_coach_digest_send_indexes")


async def _status(db, digest_id: str) -> str:
    doc = await db["coach_digest_sends"].find_one({"digest_id": digest_id})
    return str(doc["status"])


@pytest.mark.asyncio
async def test_try_claim_inserts_once_then_returns_none() -> None:
    db = AsyncMongoMockClient()["digest_test"]
    await _migration.up(db)

    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)

        first = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert first is not None
        assert first.status == DigestSendStatus.QUEUED
        assert first.coach_id == "coach-1"

        # Second claim for the same (academy, coach, date) is refused.
        second = await repo.try_claim(ACADEMY_ID, "coach-1", DIGEST_DATE)
        assert second is None

        # A different coach (or a different date) still claims.
        other_coach = await repo.try_claim(ACADEMY_ID, "coach-2", DIGEST_DATE)
        assert other_coach is not None
        other_date = await repo.try_claim(ACADEMY_ID, "coach-1", "2026-06-13")
        assert other_date is not None

        count = await db["coach_digest_sends"].count_documents({})
        assert count == 3


@pytest.mark.asyncio
async def test_mark_transitions() -> None:
    db = AsyncMongoMockClient()["digest_test"]
    await _migration.up(db)

    with tenant_scope(ACADEMY_ID):
        repo = MongoDigestSendRepository(db)

        sent = await repo.try_claim(ACADEMY_ID, "coach-sent", DIGEST_DATE)
        assert sent is not None
        await repo.mark_sent(sent.digest_id, "prov-123")
        assert await _status(db, sent.digest_id) == DigestSendStatus.SENT
        doc = await db["coach_digest_sends"].find_one({"digest_id": sent.digest_id})
        assert doc["provider_message_id"] == "prov-123"
        assert doc["sent_at"] is not None

        failed = await repo.try_claim(ACADEMY_ID, "coach-failed", DIGEST_DATE)
        assert failed is not None
        await repo.mark_failed(failed.digest_id, "bounced")
        assert await _status(db, failed.digest_id) == DigestSendStatus.FAILED
        doc = await db["coach_digest_sends"].find_one({"digest_id": failed.digest_id})
        assert doc["failed_reason"] == "bounced"

        skipped = await repo.try_claim(ACADEMY_ID, "coach-skip", DIGEST_DATE)
        assert skipped is not None
        await repo.mark_skipped_empty(skipped.digest_id)
        assert await _status(db, skipped.digest_id) == DigestSendStatus.SKIPPED_EMPTY
