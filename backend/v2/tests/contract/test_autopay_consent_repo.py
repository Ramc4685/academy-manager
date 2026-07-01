from __future__ import annotations

import importlib
from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.models import AutopayConsent
from backend.v2.contexts.billing.infrastructure.mongo_autopay_consent_repo import (
    MongoAutopayConsentRepository,
)

migration_0141 = importlib.import_module("backend.v2.migrations.0141_autopay_consents")


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


def _consent_with_setup(
    consent_id: str,
    *,
    setup_intent_id: str,
    parent_id: str = "parent-1",
) -> AutopayConsent:
    return _consent(consent_id, parent_id=parent_id).model_copy(
        update={"setup_intent_id": setup_intent_id}
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


async def test_autopay_consent_repo_returns_existing_for_same_setup_intent(db, acad) -> None:
    repo = MongoAutopayConsentRepository(db)

    first = await repo.append(_consent_with_setup("consent-1", setup_intent_id="seti-replay"))
    replay = await repo.append(_consent_with_setup("consent-2", setup_intent_id="seti-replay"))

    docs = await repo.list_for_parent(parent_id="parent-1")
    assert replay.consent_id == first.consent_id
    assert [doc.consent_id for doc in docs] == ["consent-1"]
    assert await repo.collection.count_documents({"academy_id": acad}) == 1


async def test_autopay_consents_migration_creates_unique_setup_intent_natural_key(
    db,
) -> None:
    await migration_0141.up(db)

    indexes = await db["autopay_consents"].index_information()
    assert indexes["tenant_setup_intent_unique"]["key"] == [
        ("academy_id", 1),
        ("setup_intent_id", 1),
    ]
    assert indexes["tenant_setup_intent_unique"]["unique"] is True
    assert indexes["tenant_setup_intent_unique"]["sparse"] is True
