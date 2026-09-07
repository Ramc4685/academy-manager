from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    PreviewWithdrawalCredit,
    PreviewWithdrawalCreditCommand,
    RecordWithdrawalDecision,
    RecordWithdrawalDecisionCommand,
)
from backend.v2.contexts.billing.domain.errors import PaymentNotFound
from backend.v2.contexts.billing.domain.models import CreditLedgerEntry, Payment, Subscription
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.contexts.enrollment.domain.models import Enrollment


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
        # Real repo: `credit_id` is the unique key; a second insert raises.
        assert all(e.credit_id != entry.credit_id for e in self.entries)
        self.entries.append(entry)

    async def balance_for_parent(self, parent_id):
        return sum(e.remaining_amount_cents for e in self.entries if e.parent_id == parent_id)

    async def find_active_for_enrollment(self, *, enrollment_id, type):
        for entry in reversed(self.entries):
            if (
                entry.enrollment_id == enrollment_id
                and entry.type == type
                and entry.status == "APPROVED"
            ):
                return entry
        return None


@dataclass
class FakeEnrollments:
    enrollment: Enrollment

    async def get(self, enrollment_id):
        return self.enrollment if enrollment_id == self.enrollment.enrollment_id else None


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
        created_at=datetime(2026, 5, 16, tzinfo=UTC),
        updated_at=datetime(2026, 5, 16, tzinfo=UTC),
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
        clock=lambda: datetime(2026, 5, 20, tzinfo=UTC),
    )

    result = await uc.execute(
        PreviewWithdrawalCreditCommand(
            enrollment_id="enroll-1",
            withdrawal_date=datetime(2026, 5, 21, tzinfo=UTC),
            actor_id="admin-1",
        )
    )

    assert result.credit_amount_cents == 1333
    assert result.unused_eligible_classes == 2
    assert result.paid_period_eligible_classes == 3


def _paid_payment() -> Payment:
    return Payment(
        payment_id="pay-1",
        academy_id="acad",
        parent_id="parent-1",
        session_id="sess-1",
        calculation_snapshot_id="snap-1",
        amount_cents=4000,
        refunded_cents=0,
        status="succeeded",
        created_at=datetime(2026, 5, 16, tzinfo=UTC),
        updated_at=datetime(2026, 5, 16, tzinfo=UTC),
    )


def _live_subscription() -> Subscription:
    return Subscription(
        subscription_id="sub-1",
        academy_id="acad",
        parent_id="parent-1",
        enrollment_id="enroll-1",
        session_id="sess-1",
        stripe_subscription_id="sub_stripe_1",
        status="active",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


def _decision(outcome: str = "credit") -> RecordWithdrawalDecisionCommand:
    return RecordWithdrawalDecisionCommand(
        enrollment_id="enroll-1",
        academy_id="acad",
        student_id="student-1",
        outcome=outcome,  # type: ignore[arg-type]
        withdrawal_date=datetime(2026, 5, 21, tzinfo=UTC),
        actor_id="admin-1",
        reason="moving",
    )


@pytest.mark.asyncio
async def test_credit_decision_creates_credit_and_cancels_subscription_once() -> None:
    credits = FakeCredits()
    subscriptions = FakeSubscriptions(_live_subscription())
    stripe = FakeStripe()
    uc = RecordWithdrawalDecision(
        payments=FakePayments(payment=_paid_payment(), snapshot=_snapshot()),
        credits=credits,
        subscriptions=subscriptions,
        stripe=stripe,
        clock=lambda: datetime(2026, 5, 20, tzinfo=UTC),
    )

    result = await uc.execute(_decision("credit"))

    assert result.billing_policy == "early_withdrawal_credit"
    assert result.billing_result == "credit_approved"
    assert result.credit_amount_cents == 2667
    assert result.credit_balance_cents == 2667
    assert result.credit_id == credits.entries[0].credit_id
    assert credits.entries[0].type == "EARLY_WITHDRAWAL_CREDIT"
    assert credits.entries[0].status == "APPROVED"
    assert credits.entries[0].reason == "moving"
    assert credits.entries[0].approved_by == "admin-1"
    assert stripe.cancelled == [("sub_stripe_1", True)]
    assert subscriptions.saved is not None
    assert subscriptions.saved.status == "cancelled"
    assert result.metadata == {
        "outcome": "credit",
        "credit_amount_cents": "2667",
        "subscription": "cancelled_at_period_end",
    }

    # Idempotency (issue #670): a retried withdraw must not insert a second
    # credit, must not cancel the subscription again, and must hand back the
    # credit it already made so the lifecycle event can carry its id.
    subscriptions.subscription = subscriptions.saved
    result2 = await uc.execute(_decision("credit"))
    assert result2.billing_result == "credit_already_approved"
    assert result2.credit_id == result.credit_id
    assert result2.credit_amount_cents == result.credit_amount_cents
    assert len(credits.entries) == 1
    assert stripe.cancelled == [("sub_stripe_1", True)]


@pytest.mark.asyncio
async def test_credit_decision_reports_zero_credit_honestly() -> None:
    fully_refunded = _paid_payment().model_copy(
        update={"refunded_cents": 4000, "status": "refunded"}
    )
    credits = FakeCredits()
    uc = RecordWithdrawalDecision(
        payments=FakePayments(payment=fully_refunded, snapshot=_snapshot()),
        credits=credits,
        subscriptions=FakeSubscriptions(None),
        stripe=FakeStripe(),
        clock=lambda: datetime(2026, 5, 20, tzinfo=UTC),
    )

    result = await uc.execute(_decision("credit"))

    assert result.billing_result == "credit_none"
    assert result.credit_id is None
    assert credits.entries == []
    assert result.metadata["subscription"] == "none"
    assert result.metadata.get("no_credit_reason")


@pytest.mark.asyncio
async def test_credit_decision_refuses_without_a_paid_snapshot() -> None:
    @dataclass
    class NoPayments:
        async def latest_paid_payment_for_enrollment(self, _enrollment_id: str):
            return None

        async def get_snapshot(self, _snapshot_id: str):
            return None

    uc = RecordWithdrawalDecision(
        payments=NoPayments(),
        credits=FakeCredits(),
        subscriptions=FakeSubscriptions(None),
        stripe=FakeStripe(),
    )
    with pytest.raises(PaymentNotFound):
        await uc.execute(_decision("credit"))


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["refund", "adjustment"])
async def test_manual_outcomes_record_nothing_and_say_so(outcome: str) -> None:
    credits = FakeCredits()
    stripe = FakeStripe()
    uc = RecordWithdrawalDecision(
        payments=FakePayments(payment=_paid_payment(), snapshot=_snapshot()),
        credits=credits,
        subscriptions=FakeSubscriptions(_live_subscription()),
        stripe=stripe,
    )

    result = await uc.execute(_decision(outcome))

    assert result.billing_policy == f"withdrawal_{outcome}"
    assert result.billing_result == f"{outcome}_manual"
    assert result.credit_id is None
    assert result.metadata == {"outcome": outcome, "automation": "none"}
    assert credits.entries == []
    assert stripe.cancelled == []
