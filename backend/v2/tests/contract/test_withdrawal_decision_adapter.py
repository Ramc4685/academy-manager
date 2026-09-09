"""Issue #670: the withdrawal decision adapter over the real credit ledger.

mongomock-backed ``MongoCreditLedgerRepository`` so the idempotency the
enrollment use case relies on is the repository's own lookup, not a fake's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.composition.lifecycle_billing import compose_withdrawal_decision
from backend.v2.contexts.billing.domain.models import Payment, Subscription
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.contexts.billing.infrastructure.mongo_credit_ledger_repo import (
    MongoCreditLedgerRepository,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment

WITHDRAWAL = datetime(2026, 5, 21, tzinfo=UTC)


@dataclass
class FakePayments:
    payment: Payment
    snapshot: BillingCalculationSnapshot

    async def latest_paid_payment_for_enrollment(self, _enrollment_id: str):
        return self.payment

    async def get_snapshot(self, _snapshot_id: str):
        return self.snapshot


@dataclass
class FakeSubscriptions:
    subscription: Subscription | None
    saved: list[Subscription] = field(default_factory=list)

    async def latest_for_enrollment(self, _enrollment_id: str):
        return self.saved[-1] if self.saved else self.subscription

    async def save(self, subscription: Subscription) -> None:
        self.saved.append(subscription)


@dataclass
class FakeStripe:
    cancelled: list[tuple[str, bool]] = field(default_factory=list)

    async def cancel_subscription(self, stripe_subscription_id: str, *, at_period_end: bool):
        self.cancelled.append((stripe_subscription_id, at_period_end))


def _payment(acad: str) -> Payment:
    return Payment(
        payment_id="pay-1",
        academy_id=acad,
        parent_id="parent-1",
        session_id="sess-1",
        calculation_snapshot_id="snap-1",
        amount_cents=4000,
        status="succeeded",
        created_at=datetime(2026, 5, 16, tzinfo=UTC),
        updated_at=datetime(2026, 5, 16, tzinfo=UTC),
    )


def _snapshot() -> BillingCalculationSnapshot:
    return BillingCalculationSnapshot(
        snapshot_id="snap-1",
        monthly_price_cents=10_000,
        billing_period_start=datetime(2026, 5, 1, tzinfo=UTC),
        billing_period_end=datetime(2026, 6, 1, tzinfo=UTC),
        billing_period_label="2026-05",
        timezone="America/Chicago",
        total_eligible_classes=8,
        billable_remaining_classes=3,
        proration_ratio="3/8",
        final_amount_cents=4000,
        included_occurrence_ids=[
            "sess-1:2026-05-20:18:00",
            "sess-1:2026-05-22:18:00",
            "sess-1:2026-05-26:18:00",
        ],
        excluded_occurrences={},
        calculated_at=datetime(2026, 5, 16, tzinfo=UTC),
        calculated_by="parent-1",
    )


def _enrollment(acad: str) -> Enrollment:
    return Enrollment(
        enrollment_id="enroll-1",
        academy_id=acad,
        session_id="sess-1",
        student_id="student-1",
        status="active",
    )


@pytest.mark.asyncio
async def test_credit_outcome_issues_one_ledger_entry_across_retries(db, acad) -> None:
    credits = MongoCreditLedgerRepository(db)
    stripe = FakeStripe()
    subscriptions = FakeSubscriptions(
        Subscription(
            subscription_id="sub-1",
            academy_id=acad,
            parent_id="parent-1",
            enrollment_id="enroll-1",
            session_id="sess-1",
            stripe_subscription_id="sub_stripe_1",
            status="active",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
            updated_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
    )
    adapter = compose_withdrawal_decision(
        payments=FakePayments(payment=_payment(acad), snapshot=_snapshot()),
        credits=credits,
        subscriptions=subscriptions,
        stripe=stripe,
    )

    first = await adapter.record_withdrawal_decision(
        enrollment=_enrollment(acad),
        outcome="credit",
        effective_at=WITHDRAWAL,
        actor_id="owner-1",
        reason="moving",
    )
    second = await adapter.record_withdrawal_decision(
        enrollment=_enrollment(acad),
        outcome="credit",
        effective_at=WITHDRAWAL,
        actor_id="owner-1",
        reason="moving",
    )

    assert first["billing_policy"] == "early_withdrawal_credit"
    assert first["billing_result"] == "credit_approved"
    assert first["metadata"]["credit_amount_cents"] == "2667"
    assert second["billing_result"] == "credit_already_approved"
    assert second["credit_id"] == first["credit_id"]
    docs = [d async for d in db["account_credit_ledger"].find({"enrollment_id": "enroll-1"})]
    assert len(docs) == 1
    assert docs[0]["academy_id"] == acad
    assert docs[0]["type"] == "EARLY_WITHDRAWAL_CREDIT"
    assert docs[0]["status"] == "APPROVED"
    assert docs[0]["amount_cents"] == 2667
    assert docs[0]["remaining_amount_cents"] == 2667
    assert docs[0]["approved_by"] == "owner-1"
    assert await credits.balance_for_parent("parent-1") == 2667
    # legacy subscription cancelled at period end exactly once
    assert stripe.cancelled == [("sub_stripe_1", True)]
    assert [s.status for s in subscriptions.saved] == ["cancelled"]


@pytest.mark.asyncio
async def test_manual_outcomes_write_no_ledger_entry(db, acad) -> None:
    credits = MongoCreditLedgerRepository(db)
    stripe = FakeStripe()
    adapter = compose_withdrawal_decision(
        payments=FakePayments(payment=_payment(acad), snapshot=_snapshot()),
        credits=credits,
        subscriptions=FakeSubscriptions(None),
        stripe=stripe,
    )

    result = await adapter.record_withdrawal_decision(
        enrollment=_enrollment(acad),
        outcome="refund",
        effective_at=WITHDRAWAL,
        actor_id="admin-1",
        reason="moving",
    )

    assert result == {
        "billing_policy": "withdrawal_refund",
        "billing_result": "refund_manual",
        "credit_id": None,
        "metadata": {"outcome": "refund", "automation": "none"},
    }
    assert await db["account_credit_ledger"].count_documents({}) == 0
    assert stripe.cancelled == []
