from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.models import AutopayConsent
from backend.v2.contexts.billing.infrastructure.mongo_autopay_consent_repo import (
    MongoAutopayConsentRepository,
)


def _consent(consent_id: str, parent_id: str = "parent-1") -> AutopayConsent:
    now = datetime(2026, 6, 11, tzinfo=UTC)
    return AutopayConsent(
        consent_id=consent_id,
        academy_id="test-academy",
        parent_id=parent_id,
        enrollment_id="enr-1",
        setup_intent_id=f"seti-{consent_id}",
        checkout_session_id=None,
        stripe_payment_method_id=f"pm-{consent_id}",
        method_type="card",
        consent_text_version="autopay-v1",
        ach_mandate_version=None,
        card_disclosure_version="card-v1",
        source="parent_checkout_status",
        actor_id=parent_id,
        ip="203.0.113.10",
        user_agent="pytest",
        captured_at=now,
        created_at=now,
    )


async def test_autopay_consent_repo_is_append_only(db, acad) -> None:
    repo = MongoAutopayConsentRepository(db)

    await repo.append(_consent("consent-1"))
    await repo.append(_consent("consent-2"))

    docs = await repo.list_for_parent(parent_id="parent-1")
    assert [doc.consent_id for doc in docs] == ["consent-1", "consent-2"]
    assert await repo.collection.count_documents({"academy_id": acad}) == 2


async def test_autopay_consent_repo_is_tenant_isolated(db, acad, other_acad) -> None:
    from backend.v2.shared.tenancy.context import _current as _tv

    repo = MongoAutopayConsentRepository(db)
    token = _tv.set(acad)
    try:
        await repo.append(_consent("consent-acad"))
    finally:
        _tv.reset(token)

    token = _tv.set(other_acad)
    try:
        await repo.append(_consent("consent-other"))
        other_docs = await repo.list_for_parent(parent_id="parent-1")
    finally:
        _tv.reset(token)

    assert [doc.consent_id for doc in other_docs] == ["consent-other"]

    token = _tv.set(acad)
    try:
        acad_docs = await repo.list_for_parent(parent_id="parent-1")
    finally:
        _tv.reset(token)

    assert [doc.consent_id for doc in acad_docs] == ["consent-acad"]
