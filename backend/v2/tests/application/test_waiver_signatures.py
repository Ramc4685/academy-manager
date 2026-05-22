"""Waiver signatures — domain + use case tests (Wave 4 prep).

Covers the per-student signature model:

- A signature points to an immutable ``waiver_template_id`` + ``content_hash``.
- A signature carries an ``artifact_id`` (pointer to the stored PDF / image).
- Admin can answer "what exact waiver did this student sign?" by looking up the
  signature and dereferencing the template version + hash.

These tests use in-memory fakes; the Mongo contract is exercised in
``backend/v2/tests/contract/test_admin_waivers_mongo_repo.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.onboarding.application.use_cases.waiver_signatures import (
    GetExactSignedWaiver,
    SignedWaiverNotFound,
)
from backend.v2.contexts.onboarding.domain.models import (
    WaiverSignature,
    WaiverTemplate,
)


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class FakeTemplateRepo:
    def __init__(self, templates: list[WaiverTemplate]) -> None:
        self._by_id = {tpl.waiver_template_id: tpl for tpl in templates}

    async def get(self, waiver_template_id: str) -> WaiverTemplate | None:
        return self._by_id.get(waiver_template_id)


class FakeSignatureRepo:
    def __init__(self, signatures: list[WaiverSignature]) -> None:
        self._signatures = list(signatures)

    async def latest_for_student(self, student_id: str) -> WaiverSignature | None:
        rows = sorted(
            (s for s in self._signatures if s.student_id == student_id),
            key=lambda s: s.signed_at,
            reverse=True,
        )
        return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Domain shape
# ---------------------------------------------------------------------------


def test_waiver_template_requires_academy_id_and_version() -> None:
    tpl = WaiverTemplate(
        waiver_template_id="wt-1",
        academy_id="acad-1",
        name="Standard Liability",
        version="2026.1",
        content_hash="hash-2026-1",
        body="Body text.",
        effective_from=_dt("2026-01-01T00:00:00"),
        expires_at=None,
        status="active",
    )
    assert tpl.academy_id == "acad-1"
    assert tpl.status == "active"


def test_waiver_signature_is_per_student_and_carries_artifact_id() -> None:
    sig = WaiverSignature(
        waiver_signature_id="ws-1",
        academy_id="acad-1",
        waiver_template_id="wt-1",
        student_id="st-1",
        parent_user_id="usr-parent",
        signed_at=_dt("2026-05-01T12:00:00"),
        signer_name="Jane Doe",
        signer_email="jane@example.com",
        content_hash="hash-2026-1",
        ip_address="203.0.113.4",
        user_agent="Mozilla/5.0",
        artifact_id="art-pdf-1",
        expires_at=None,
    )
    assert sig.student_id == "st-1"
    assert sig.artifact_id == "art-pdf-1"
    assert sig.content_hash == "hash-2026-1"


# ---------------------------------------------------------------------------
# Exact signed waiver lookup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_exact_signed_waiver_returns_template_version_and_hash() -> None:
    tpl_v1 = WaiverTemplate(
        waiver_template_id="wt-1",
        academy_id="acad-1",
        name="Standard Liability",
        version="2025.1",
        content_hash="hash-2025-1",
        body="Old body.",
        effective_from=_dt("2025-01-01T00:00:00"),
        expires_at=None,
        status="superseded",
    )
    tpl_v2 = WaiverTemplate(
        waiver_template_id="wt-2",
        academy_id="acad-1",
        name="Standard Liability",
        version="2026.1",
        content_hash="hash-2026-1",
        body="Current body.",
        effective_from=_dt("2026-01-01T00:00:00"),
        expires_at=None,
        status="active",
    )
    sig_old = WaiverSignature(
        waiver_signature_id="ws-old",
        academy_id="acad-1",
        waiver_template_id="wt-1",
        student_id="st-1",
        parent_user_id="usr-parent",
        signed_at=_dt("2025-06-01T12:00:00"),
        signer_name="Jane Doe",
        signer_email="jane@example.com",
        content_hash="hash-2025-1",
        ip_address=None,
        user_agent=None,
        artifact_id="art-old",
        expires_at=None,
    )
    sig_new = WaiverSignature(
        waiver_signature_id="ws-new",
        academy_id="acad-1",
        waiver_template_id="wt-2",
        student_id="st-1",
        parent_user_id="usr-parent",
        signed_at=_dt("2026-05-01T12:00:00"),
        signer_name="Jane Doe",
        signer_email="jane@example.com",
        content_hash="hash-2026-1",
        ip_address="203.0.113.4",
        user_agent="Mozilla/5.0",
        artifact_id="art-new",
        expires_at=None,
    )
    templates = FakeTemplateRepo([tpl_v1, tpl_v2])
    signatures = FakeSignatureRepo([sig_old, sig_new])

    result = await GetExactSignedWaiver(signatures, templates).execute("st-1")

    assert result.signature.waiver_signature_id == "ws-new"
    assert result.template.waiver_template_id == "wt-2"
    assert result.template.version == "2026.1"
    # Exact match: signature hash equals the template hash at signing time.
    assert result.signature.content_hash == result.template.content_hash
    assert result.artifact_id == "art-new"


@pytest.mark.asyncio
async def test_get_exact_signed_waiver_raises_when_student_has_no_signature() -> None:
    templates = FakeTemplateRepo([])
    signatures = FakeSignatureRepo([])

    with pytest.raises(SignedWaiverNotFound):
        await GetExactSignedWaiver(signatures, templates).execute("st-unknown")


@pytest.mark.asyncio
async def test_get_exact_signed_waiver_raises_when_template_was_deleted() -> None:
    """If a signature references a template_id that no longer exists, that is a
    data-integrity violation; the use case must raise rather than silently
    returning a partial result."""
    sig = WaiverSignature(
        waiver_signature_id="ws-orphan",
        academy_id="acad-1",
        waiver_template_id="wt-missing",
        student_id="st-2",
        parent_user_id="usr-parent",
        signed_at=_dt("2026-05-01T12:00:00"),
        signer_name="Jane",
        signer_email="jane@example.com",
        content_hash="hash-x",
        ip_address=None,
        user_agent=None,
        artifact_id="art-x",
        expires_at=None,
    )
    templates = FakeTemplateRepo([])
    signatures = FakeSignatureRepo([sig])

    with pytest.raises(SignedWaiverNotFound):
        await GetExactSignedWaiver(signatures, templates).execute("st-2")


@pytest.mark.asyncio
async def test_get_exact_signed_waiver_flags_hash_mismatch_against_template() -> None:
    """If the signed content_hash doesn't match the referenced template's hash,
    the result must surface ``signature_matches_template = False`` so admins
    can detect tampering or stale data."""
    tpl = WaiverTemplate(
        waiver_template_id="wt-1",
        academy_id="acad-1",
        name="Standard Liability",
        version="2026.1",
        content_hash="hash-current",
        body="Body.",
        effective_from=_dt("2026-01-01T00:00:00"),
        expires_at=None,
        status="active",
    )
    sig = WaiverSignature(
        waiver_signature_id="ws-mismatch",
        academy_id="acad-1",
        waiver_template_id="wt-1",
        student_id="st-3",
        parent_user_id="usr-parent",
        signed_at=_dt("2026-05-01T12:00:00"),
        signer_name="Jane",
        signer_email="jane@example.com",
        content_hash="hash-different",
        ip_address=None,
        user_agent=None,
        artifact_id="art-3",
        expires_at=None,
    )
    templates = FakeTemplateRepo([tpl])
    signatures = FakeSignatureRepo([sig])

    result = await GetExactSignedWaiver(signatures, templates).execute("st-3")

    assert result.signature_matches_template is False
    assert result.template.content_hash == "hash-current"
    assert result.signature.content_hash == "hash-different"
