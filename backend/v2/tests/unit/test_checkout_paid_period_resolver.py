"""Unit tests for the composition-root CheckoutPaidPeriodResolver (#506).

The first-month proration paid at registration checkout leaves a Payment with
``enrollment_id=None`` plus a CONSUMED snapshot with no enrollment_id, so the
monthly generator's dedupe layers cannot see it. This resolver walks
``payment -> snapshot -> billing_period_label`` so approval can stamp the
already-paid period onto the new enrollment as a skip period.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application.checkout_paid_period import (
    CheckoutPaidPeriodResolver,
)
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot

NOW = datetime(2026, 8, 3, tzinfo=UTC)


def _payment(**overrides: object) -> Payment:
    base: dict[str, object] = {
        "payment_id": "pay-1",
        "academy_id": "acad-1",
        "parent_id": "parent-1",
        "session_id": "sess-1",
        "calculation_snapshot_id": "snap-1",
        "amount_cents": 5000,
        "status": "succeeded",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return Payment(**base)  # type: ignore[arg-type]


def _snapshot(**overrides: object) -> BillingCalculationSnapshot:
    base: dict[str, object] = {
        "snapshot_id": "snap-1",
        "status": "CONSUMED",
        "calculation_type": "FIRST_MONTH_PRORATION",
        "monthly_price_cents": 10000,
        "billing_period_start": datetime(2026, 8, 1, tzinfo=UTC),
        "billing_period_end": datetime(2026, 9, 1, tzinfo=UTC),
        "billing_period_label": "2026-08",
        "timezone": "UTC",
        "total_eligible_classes": 8,
        "billable_remaining_classes": 4,
        "proration_ratio": "4/8",
        "final_amount_cents": 5000,
        "included_occurrence_ids": [],
        "excluded_occurrences": {},
        "calculated_at": NOW,
        "calculated_by": "parent-1",
    }
    base.update(overrides)
    return BillingCalculationSnapshot(**base)  # type: ignore[arg-type]


class _FakePayments:
    def __init__(
        self,
        payment: Payment | None,
        snapshot: BillingCalculationSnapshot | None,
    ) -> None:
        self._payment = payment
        self._snapshot = snapshot

    async def get(self, payment_id: str) -> Payment | None:
        return self._payment if self._payment and self._payment.payment_id == payment_id else None

    async def get_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None:
        if self._snapshot and self._snapshot.snapshot_id == snapshot_id:
            return self._snapshot
        return None


@pytest.mark.asyncio
async def test_resolves_period_for_succeeded_first_month_payment() -> None:
    resolver = CheckoutPaidPeriodResolver(_FakePayments(_payment(), _snapshot()))
    assert await resolver.paid_period_for_payment("pay-1") == "2026-08"


@pytest.mark.asyncio
async def test_returns_none_for_missing_payment() -> None:
    resolver = CheckoutPaidPeriodResolver(_FakePayments(None, _snapshot()))
    assert await resolver.paid_period_for_payment("pay-1") is None


@pytest.mark.asyncio
async def test_returns_none_for_unpaid_payment() -> None:
    resolver = CheckoutPaidPeriodResolver(_FakePayments(_payment(status="pending"), _snapshot()))
    assert await resolver.paid_period_for_payment("pay-1") is None


@pytest.mark.asyncio
async def test_returns_none_when_payment_has_no_snapshot_id() -> None:
    resolver = CheckoutPaidPeriodResolver(
        _FakePayments(_payment(calculation_snapshot_id=None), _snapshot())
    )
    assert await resolver.paid_period_for_payment("pay-1") is None


@pytest.mark.asyncio
async def test_returns_none_when_snapshot_is_missing() -> None:
    resolver = CheckoutPaidPeriodResolver(_FakePayments(_payment(), None))
    assert await resolver.paid_period_for_payment("pay-1") is None


@pytest.mark.asyncio
async def test_returns_none_for_non_first_month_snapshot() -> None:
    resolver = CheckoutPaidPeriodResolver(
        _FakePayments(_payment(), _snapshot(calculation_type="WITHDRAWAL_CREDIT"))
    )
    assert await resolver.paid_period_for_payment("pay-1") is None


@pytest.mark.asyncio
async def test_partially_refunded_payment_still_counts_as_paid() -> None:
    resolver = CheckoutPaidPeriodResolver(
        _FakePayments(_payment(status="partially_refunded"), _snapshot())
    )
    assert await resolver.paid_period_for_payment("pay-1") == "2026-08"
