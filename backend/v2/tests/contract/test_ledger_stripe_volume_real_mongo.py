"""``sum_stripe_settled_cents`` on a real ``mongod``: counts only succeeded
Stripe payments inside the window, for the academy in scope and no other."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.shared.tenancy import tenant_scope

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def _payment(
    academy_id: str, payment_id: str, cents: int, **overrides: object
) -> dict[str, object]:
    return {
        "payment_id": payment_id,
        "academy_id": academy_id,
        "parent_id": "p1",
        "amount_cents": cents,
        "unapplied_amount_cents": 0,
        "currency": "usd",
        "status": "succeeded",
        "refunded_cents": 0,
        "payment_method": "card",
        "stripe_payment_intent_id": f"pi_{payment_id}",
        "paid_at": NOW - timedelta(days=10),
        "created_at": NOW - timedelta(days=10),
        "updated_at": NOW - timedelta(days=10),
        **overrides,
    }


@pytest.mark.asyncio
async def test_sums_only_this_academys_succeeded_stripe_payments_in_window(real_db) -> None:
    await real_db["ledger_payments"].insert_many(
        [
            _payment("acad-a", "a1", 1000),
            _payment("acad-a", "a2", 2000),
            _payment("acad-a", "a3", 4000, status="refunded"),
            _payment("acad-a", "a4", 8000, stripe_payment_intent_id=None, payment_method="cash"),
            _payment("acad-a", "a5", 16000, paid_at=NOW - timedelta(days=120)),
            _payment("acad-b", "b1", 32000),
        ]
    )
    repo = MongoBillingLedgerRepository(real_db)
    with tenant_scope("acad-a"):
        assert await repo.sum_stripe_settled_cents(since=NOW - timedelta(days=90)) == 3000
    with tenant_scope("acad-b"):
        assert await repo.sum_stripe_settled_cents(since=NOW - timedelta(days=90)) == 32000
    with tenant_scope("acad-c"):
        assert await repo.sum_stripe_settled_cents(since=NOW - timedelta(days=90)) == 0
