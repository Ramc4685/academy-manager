"""Resolve the billing period already paid by a registration checkout (#506)."""

from __future__ import annotations

from typing import Protocol

from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot


class PaymentSnapshotReader(Protocol):
    """Narrow read-only slice of the payment repository needed by
    ``CheckoutPaidPeriodResolver`` (keeps the resolver unit-testable with a
    fake instead of the full Mongo repository)."""

    async def get(self, payment_id: str) -> Payment | None: ...

    async def get_snapshot(self, snapshot_id: str) -> BillingCalculationSnapshot | None: ...


class CheckoutPaidPeriodResolver:
    """Implements ``PaidPeriodResolver`` for registration approval (#506).

    The first-month proration paid at registration checkout leaves a Payment
    with ``enrollment_id=None`` and a CONSUMED calculation snapshot that also
    has no enrollment_id, so the monthly generator's enrollment-keyed dedupe
    layers cannot see either artifact. This resolver walks
    ``payment -> calculation_snapshot -> billing_period_label`` so approval
    can stamp the already-paid period onto the new enrollment as a skip
    period, mirroring the zero-quote path.
    """

    _PAID_STATUSES = frozenset({"succeeded", "paid", "partially_refunded"})

    def __init__(self, payments: PaymentSnapshotReader) -> None:
        self._payments = payments

    async def paid_period_for_payment(self, payment_id: str) -> str | None:
        payment = await self._payments.get(payment_id)
        if payment is None or payment.status not in self._PAID_STATUSES:
            return None
        if not payment.calculation_snapshot_id:
            return None
        snapshot = await self._payments.get_snapshot(payment.calculation_snapshot_id)
        if snapshot is None or snapshot.calculation_type != "FIRST_MONTH_PRORATION":
            return None
        return snapshot.billing_period_label
