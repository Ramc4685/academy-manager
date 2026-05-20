from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    ApproveWithdrawalCredit,
    ApproveWithdrawalCreditCommand,
    PreviewWithdrawalCredit,
    PreviewWithdrawalCreditCommand,
)
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment, Subscription
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.contexts.enrollment.domain.models import Enrollment


def _snapshot() -> BillingCalculationSnapshot:
    return BillingCalculationSnapshot(
        snapshot_id="snap-1",
        monthly_price_cents=10_000,
        billing_period_start=datetime(2026, 5, 1, tzinfo=timezone.utc),
        billing_period_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
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
        calculated_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        calculated_by="parent-1",
    )


@dataclass
class FakePayments:
    payment: Payment
    snapshot: BillingCalculationSnapshot

    async def latest_paid_payment_for_enrollment(self, _enrollment_id: str):
        return self.payment

    async def get_snapshot(self, _snapshot_id: str):
        return self.snapshot


@dataclass
class FakeCredits:
    entries: list[CreditLedgerEntry] = field(default_factory=list)

    async def create(self, entry):
        self.entries.append(entry)

    async def balance_for_parent(self, parent_id):
        return sum(e.remaining_amount_cents for e in self.entries if e.parent_id == parent_id)


@dataclass
class FakeEnrollments:
    enrollment: Enrollment
    withdrawn: tuple[str, datetime] | None = None

    async def get(self, enrollment_id):
        return self.enrollment if enrollment_id == self.enrollment.enrollment_id else None

    async def mark_withdrawn(self, enrollment_id, *, withdrawal_date):
        self.withdrawn = (enrollment_id, withdrawal_date)


@dataclass
class FakeSubscriptions:
    subscription: Subscription | None
    saved: Subscription | None = None

    async def latest_for_enrollment(self, _enrollment_id):
        return self.subscription

    async def save(self, subscription):
        self.saved = subscription


@dataclass
class FakeStripe:
    cancelled: list[tuple[str, bool]] = field(default_factory=list)

    async def cancel_subscription(self, stripe_subscription_id, *, at_period_end):
        self.cancelled.append((stripe_subscription_id, at_period_end))


@pytest.mark.asyncio
async def test_preview_withdrawal_credit_uses_net_paid_and_original_snapshot() -> None:
    payment = Payment(
        payment_id="pay-1",
        academy_id="acad",
        parent_id="parent-1",
        session_id="sess-1",
        calculation_snapshot_id="snap-1",
        amount_cents=4000,
        refunded_cents=2000,
        status="partially_refunded",
        created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    uc = PreviewWithdrawalCredit(
        payments=FakePayments(payment=payment, snapshot=_snapshot()),
        enrollments=FakeEnrollments(
            Enrollment(
                enrollment_id="enroll-1",
                academy_id="acad",
                session_id="sess-1",
                student_id="student-1",
                status="active",
            )
        ),
        clock=lambda: datetime(2026, 5, 20, tzinfo=timezone.utc),
    )

    result = await uc.execute(
        PreviewWithdrawalCreditCommand(
            enrollment_id="enroll-1",
            withdrawal_date=datetime(2026, 5, 21, tzinfo=timezone.utc),
            actor_id="admin-1",
        )
    )

    assert result.credit_amount_cents == 1333
    assert result.unused_eligible_classes == 2
    assert result.paid_period_eligible_classes == 3


@pytest.mark.asyncio
async def test_approve_withdrawal_creates_credit_and_cancels_subscription() -> None:
    payment = Payment(
        payment_id="pay-1",
        academy_id="acad",
        parent_id="parent-1",
        session_id="sess-1",
        calculation_snapshot_id="snap-1",
        amount_cents=4000,
        refunded_cents=0,
        status="succeeded",
        created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
    )
    credits = FakeCredits()
    enrollments = FakeEnrollments(
        Enrollment(
            enrollment_id="enroll-1",
            academy_id="acad",
            session_id="sess-1",
            student_id="student-1",
            status="active",
        )
    )
    subscriptions = FakeSubscriptions(
        Subscription(
            subscription_id="sub-1",
            academy_id="acad",
            parent_id="parent-1",
            enrollment_id="enroll-1",
            session_id="sess-1",
            stripe_subscription_id="sub_stripe_1",
            status="active",
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
    )
    stripe = FakeStripe()
    uc = ApproveWithdrawalCredit(
        payments=FakePayments(payment=payment, snapshot=_snapshot()),
        credits=credits,
        enrollments=enrollments,
        subscriptions=subscriptions,
        stripe=stripe,
        academy_id="acad",
        clock=lambda: datetime(2026, 5, 20, tzinfo=timezone.utc),
    )

    result = await uc.execute(
        ApproveWithdrawalCreditCommand(
            enrollment_id="enroll-1",
            withdrawal_date=datetime(2026, 5, 21, tzinfo=timezone.utc),
            actor_id="admin-1",
            admin_note="moving",
        )
    )

    assert result.credit_amount_cents == 2667
    assert result.credit_balance_cents == 2667
    assert credits.entries[0].type == "EARLY_WITHDRAWAL_CREDIT"
    assert credits.entries[0].status == "APPROVED"
    assert enrollments.withdrawn is not None
    assert stripe.cancelled == [("sub_stripe_1", True)]
    assert subscriptions.saved is not None
    assert subscriptions.saved.status == "cancelled"
