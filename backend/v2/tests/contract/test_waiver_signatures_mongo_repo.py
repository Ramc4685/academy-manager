"""Mongo contract tests for waiver_templates + waiver_signatures (Wave 4).

These exercise the per-student signature model end-to-end against
mongomock-motor, including:

  * tenant isolation (no leakage across academies)
  * upsert semantics for ``MongoWaiverSignatureRepository.save``
  * ``latest_for_student`` ordering by ``signed_at`` desc
  * ``MongoWaiverTemplateRepository.get`` round-trip
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.v2.contexts.onboarding.domain.models import (
    WaiverSignature,
    WaiverTemplate,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_signature_repo import (
    MongoWaiverSignatureRepository,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_waiver_template_repo import (
    MongoWaiverTemplateRepository,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _template(
    *,
    template_id: str = "wt-1",
    academy_id: str = "test-academy",
    version: str = "2026.1",
    content_hash: str = "hash-2026-1",
    status: str = "active",
) -> WaiverTemplate:
    return WaiverTemplate(
        waiver_template_id=template_id,
        academy_id=academy_id,
        name="Standard Liability",
        version=version,
        content_hash=content_hash,
        body="Body text.",
        effective_from=_dt("2026-01-01T00:00:00"),
        expires_at=None,
        status=status,  # type: ignore[arg-type]
    )


def _signature(
    *,
    signature_id: str,
    academy_id: str = "test-academy",
    template_id: str = "wt-1",
    student_id: str = "st-1",
    signed_at: str = "2026-05-01T12:00:00",
    content_hash: str = "hash-2026-1",
    artifact_id: str | None = "art-1",
) -> WaiverSignature:
    return WaiverSignature(
        waiver_signature_id=signature_id,
        academy_id=academy_id,
        waiver_template_id=template_id,
        student_id=student_id,
        parent_user_id="usr-parent",
        signed_at=_dt(signed_at),
        signer_name="Jane Doe",
        signer_email="jane@example.com",
        content_hash=content_hash,
        ip_address="203.0.113.4",
        user_agent="Mozilla/5.0",
        artifact_id=artifact_id,
        expires_at=None,
    )


@pytest.mark.asyncio
async def test_waiver_template_repo_round_trips_and_scopes_by_tenant(
    db, acad
) -> None:
    # seed: one template in our tenant, one in another tenant.
    await db["waiver_templates"].insert_many(
        [
            {
                "waiver_template_id": "wt-1",
                "academy_id": acad,
                "name": "Standard Liability",
                "version": "2026.1",
                "content_hash": "hash-2026-1",
                "body": "Body text.",
                "effective_from": _dt("2026-01-01T00:00:00"),
                "status": "active",
            },
            {
                "waiver_template_id": "wt-other",
                "academy_id": "other-academy",
                "name": "Other",
                "version": "2026.1",
                "content_hash": "hash-other",
                "body": "Body.",
                "effective_from": _dt("2026-01-01T00:00:00"),
                "status": "active",
            },
        ]
    )

    repo = MongoWaiverTemplateRepository(db)
    tpl = await repo.get("wt-1")
    assert tpl is not None
    assert tpl.version == "2026.1"
    assert tpl.status == "active"
    # tenant isolation: cannot see the other tenant's template
    assert await repo.get("wt-other") is None


@pytest.mark.asyncio
async def test_waiver_signature_repo_upsert_and_latest_for_student(
    db, acad
) -> None:
    repo = MongoWaiverSignatureRepository(db)

    # First save inserts.
    sig_old = _signature(
        signature_id="ws-old",
        signed_at="2025-06-01T12:00:00",
        content_hash="hash-2025-1",
        template_id="wt-old",
        artifact_id="art-old",
    )
    sig_new = _signature(
        signature_id="ws-new",
        signed_at="2026-05-01T12:00:00",
        content_hash="hash-2026-1",
        template_id="wt-1",
        artifact_id="art-new",
    )
    await repo.save(sig_old)
    await repo.save(sig_new)

    # latest_for_student returns the newest.
    latest = await repo.latest_for_student("st-1")
    assert latest is not None
    assert latest.waiver_signature_id == "ws-new"
    assert latest.artifact_id == "art-new"
    assert latest.content_hash == "hash-2026-1"

    # Re-saving the same id is an upsert (no duplicates).
    await repo.save(
        _signature(
            signature_id="ws-new",
            signed_at="2026-05-01T12:00:00",
            content_hash="hash-2026-1",
            template_id="wt-1",
            artifact_id="art-rewritten",
        )
    )
    count = await db["waiver_signatures"].count_documents({})
    assert count == 2
    again = await repo.get("ws-new")
    assert again is not None
    assert again.artifact_id == "art-rewritten"


@pytest.mark.asyncio
async def test_waiver_signature_repo_isolates_tenants(db, acad) -> None:
    # Seed a signature in 'other-academy' directly.
    await db["waiver_signatures"].insert_one(
        {
            "waiver_signature_id": "ws-other",
            "academy_id": "other-academy",
            "waiver_template_id": "wt-1",
            "student_id": "st-1",
            "parent_user_id": "p",
            "signed_at": _dt("2026-05-10T12:00:00"),
            "signer_name": "Other",
            "signer_email": "other@example.com",
            "content_hash": "hash-other",
            "artifact_id": "art-other",
        }
    )

    repo = MongoWaiverSignatureRepository(db)
    # In the default 'acad' fixture context, the row is invisible.
    assert await repo.latest_for_student("st-1") is None
    assert await repo.get("ws-other") is None
