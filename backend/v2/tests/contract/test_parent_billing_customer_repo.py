"""Contract tests — MongoParentBillingCustomerRepository autopay_status split (Slice B).

Covers:
- `set_default_payment_method` no longer hardcodes `autopay_status="active"`;
  it sets the split `autopay_enrollment_status="active"` field.
- `set_enrollment_status` persists enrollment-lifecycle state independently
  of attempt outcomes.
- `record_attempt_outcome` persists a projection of the latest charge attempt
  (`last_attempt_outcome`, `last_attempt_at`, `last_failure_code`) without
  touching `autopay_enrollment_status`.
- Tenant isolation on both split fields.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)


async def test_set_default_payment_method_sets_split_enrollment_status_active(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)

    await repo.set_default_payment_method(
        parent_id="parent-1",
        stripe_customer_id="cus_1",
        stripe_payment_method_id="pm_1",
        payment_method_type="card",
        stripe_mandate_id=None,
        setup_intent_id="seti_1",
        checkout_session_id="cs_1",
        completed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-1"})
    assert doc is not None
    assert doc["autopay_enrollment_status"] == "active"
    # Legacy hardcoded field must be gone — no conflated status left behind.
    assert "autopay_status" not in doc


async def test_set_enrollment_status_persists_independently_of_attempt_outcome(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    await repo.set_stripe_customer_id(parent_id="parent-1", stripe_customer_id="cus_1")

    await repo.set_enrollment_status(parent_id="parent-1", status="offered")
    doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-1"})
    assert doc["autopay_enrollment_status"] == "offered"

    await repo.set_enrollment_status(parent_id="parent-1", status="setup_started")
    await repo.set_enrollment_status(parent_id="parent-1", status="active")
    doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-1"})
    assert doc["autopay_enrollment_status"] == "active"

    await repo.set_enrollment_status(parent_id="parent-1", status="paused")
    doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-1"})
    assert doc["autopay_enrollment_status"] == "paused"


async def test_record_attempt_outcome_does_not_change_enrollment_status(db, acad) -> None:
    """Regression: a bounced charge sets last_attempt_outcome=declined but
    leaves autopay_enrollment_status=active untouched."""
    repo = MongoParentBillingCustomerRepository(db)
    await repo.set_default_payment_method(
        parent_id="parent-1",
        stripe_customer_id="cus_1",
        stripe_payment_method_id="pm_1",
        payment_method_type="card",
        stripe_mandate_id=None,
        setup_intent_id="seti_1",
        checkout_session_id="cs_1",
        completed_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    occurred_at = datetime(2026, 6, 15, 9, 30, tzinfo=UTC)
    await repo.record_attempt_outcome(
        parent_id="parent-1",
        outcome="declined",
        occurred_at=occurred_at,
        failure_code="card_declined",
    )

    doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-1"})
    assert doc["autopay_enrollment_status"] == "active"
    assert doc["last_attempt_outcome"] == "declined"
    assert doc["last_attempt_at"].replace(tzinfo=UTC) == occurred_at
    assert doc["last_failure_code"] == "card_declined"


async def test_record_attempt_outcome_clears_failure_code_on_success(db, acad) -> None:
    repo = MongoParentBillingCustomerRepository(db)
    await repo.set_stripe_customer_id(parent_id="parent-1", stripe_customer_id="cus_1")
    await repo.record_attempt_outcome(
        parent_id="parent-1",
        outcome="declined",
        occurred_at=datetime(2026, 6, 15, tzinfo=UTC),
        failure_code="card_declined",
    )

    await repo.record_attempt_outcome(
        parent_id="parent-1",
        outcome="succeeded",
        occurred_at=datetime(2026, 6, 16, tzinfo=UTC),
        failure_code=None,
    )

    doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-1"})
    assert doc["last_attempt_outcome"] == "succeeded"
    assert doc["last_failure_code"] is None


async def test_tenant_isolation_enrollment_status(db, acad, other_acad) -> None:
    from backend.v2.shared.tenancy.context import _current as _tv

    repo = MongoParentBillingCustomerRepository(db)

    token = _tv.set(acad)
    try:
        await repo.set_enrollment_status(parent_id="parent-shared", status="offered")
    finally:
        _tv.reset(token)

    token = _tv.set(other_acad)
    try:
        await repo.set_enrollment_status(parent_id="parent-shared", status="offered")
        await repo.set_enrollment_status(parent_id="parent-shared", status="setup_started")
        await repo.set_enrollment_status(parent_id="parent-shared", status="active")
        other_doc = await repo.collection.find_one(
            {"academy_id": other_acad, "parent_id": "parent-shared"}
        )
    finally:
        _tv.reset(token)

    acad_doc = await repo.collection.find_one({"academy_id": acad, "parent_id": "parent-shared"})

    assert acad_doc["autopay_enrollment_status"] == "offered"
    assert other_doc["autopay_enrollment_status"] == "active"
