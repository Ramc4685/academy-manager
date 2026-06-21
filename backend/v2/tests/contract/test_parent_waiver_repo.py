"""Mongo contract tests for parent waiver signature persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.onboarding.domain.models import WaiverSignature
from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
    MongoParentWaiverRepository,
)

NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)


def _signature() -> WaiverSignature:
    return WaiverSignature(
        waiver_signature_id="ws-1",
        academy_id="test-academy",
        waiver_template_id="wt-1",
        student_id="st-1",
        parent_user_id="parent-1",
        signed_at=NOW,
        signer_name="Parent One",
        signer_email="parent@example.com",
        content_hash="hash-1",
        ip_address="203.0.113.10",
        user_agent="Playwright",
    )


@pytest.mark.asyncio
async def test_save_signature_creates_idempotent_artifact_and_share_link(db, acad) -> None:
    await db["waiver_templates"].insert_one(
        {
            "academy_id": acad,
            "waiver_template_id": "wt-1",
            "title": "Annual waiver",
            "version": "2026.1",
            "content_hash": "hash-1",
            "body": "Signed waiver text.",
            "status": "active",
            "effective_from": NOW,
        }
    )
    repo = MongoParentWaiverRepository(db)

    await repo.save_signature(_signature())
    await repo.save_signature(_signature())

    signature = await db["waiver_signatures"].find_one(
        {"academy_id": acad, "waiver_signature_id": "ws-1"}
    )
    assert signature is not None
    assert signature["artifact_id"] == "wa_ws-1"

    artifacts = [doc async for doc in db["waiver_artifacts"].find({"academy_id": acad})]
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["artifact_id"] == "wa_ws-1"
    assert artifact["status"] == "stored"
    assert artifact["signature_id"] == "ws-1"
    assert artifact["waiver_template_id"] == "wt-1"
    assert artifact["template_title"] == "Annual waiver"
    assert artifact["template_version"] == "2026.1"
    assert artifact["content_hash"] == "hash-1"
    assert artifact["body"] == "Signed waiver text."

    links = [doc async for doc in db["waiver_share_links"].find({"academy_id": acad})]
    assert len(links) == 1
    link = links[0]
    assert link["artifact_id"] == "wa_ws-1"
    assert link["signature_id"] == "ws-1"
    assert link["status"] == "active"
    assert link["share_link_id"].startswith("wsl_")
    assert len(link["share_link_id"]) >= 30
    assert link["share_link_id"] != "ws-1"
