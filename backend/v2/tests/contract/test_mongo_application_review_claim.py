"""Atomic admin review claim contract."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.domain.models import Application
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)


@pytest.mark.asyncio
async def test_only_one_admin_worker_can_claim_pending_application(db, acad) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    repo = MongoApplicationRepository(db)
    await repo.save(
        Application(
            application_id="app-1",
            academy_id=acad,
            parent_user_id="parent-1",
            parent_email="parent@example.com",
            status="PENDING_APPROVAL",
            expires_at=now + timedelta(days=7),
            created_at=now,
            updated_at=now,
        )
    )

    approve_claim, waitlist_claim = await asyncio.gather(
        repo.claim_for_review(
            "app-1",
            "APPROVING",
            claim_token="token-a",
            updated_at=now,
            stale_before=now - timedelta(minutes=15),
        ),
        repo.claim_for_review(
            "app-1",
            "WAITLISTING",
            claim_token="token-b",
            updated_at=now,
            stale_before=now - timedelta(minutes=15),
        ),
    )

    assert sum(claim is not None for claim in (approve_claim, waitlist_claim)) == 1
    stored = await repo.get("app-1")
    assert stored is not None
    assert stored.status in {"APPROVING", "WAITLISTING"}


@pytest.mark.asyncio
async def test_stale_admin_review_claim_can_be_recovered_after_worker_exit(db, acad) -> None:
    now = datetime(2026, 7, 14, tzinfo=UTC)
    old = now - timedelta(hours=1)
    await db["onboarding_applications"].insert_one(
        {
            "academy_id": acad,
            "application_id": "app-stale",
            "parent_user_id": "parent-1",
            "parent_email": "parent@example.com",
            "status": "APPROVING",
            "review_claimed_at": old,
            "review_claim_token": "expired-token",
            "expires_at": now + timedelta(days=7),
            "created_at": old,
            "updated_at": old,
        }
    )
    repo = MongoApplicationRepository(db)

    recovered = await repo.claim_for_review(
        "app-stale",
        "APPROVING",
        claim_token="replacement-token",
        updated_at=now,
        stale_before=now - timedelta(minutes=15),
    )

    assert recovered is not None
    assert recovered.review_claimed_at == now.replace(tzinfo=None)
    await repo.release_review(
        "app-stale",
        "APPROVING",
        claim_token="expired-token",
        updated_at=now,
    )
    stale_completed = await repo.complete_review(
        recovered.model_copy(update={"status": "DECLINED"}),
        claim_token="expired-token",
    )
    stored = await repo.get("app-stale")
    assert stale_completed is False
    assert stored is not None
    assert stored.review_claim_token == "replacement-token"
