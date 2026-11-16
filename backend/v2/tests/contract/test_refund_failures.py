"""Refunds Stripe could not deliver surface on Billing Health (L1 A4-8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


@pytest.mark.asyncio
async def test_failed_refund_is_recorded_once_and_listed(real_db, acad) -> None:
    await real_db["ledger_payments"].insert_one(
        {
            "academy_id": acad,
            "payment_id": "pay-1",
            "parent_id": "parent-1",
            "stripe_payment_intent_id": "pi_1",
            "amount_cents": 5_000,
            "unapplied_amount_cents": 0,
            "currency": "usd",
            "status": "succeeded",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    ledger = MongoBillingLedgerRepository(real_db)

    for _ in range(2):
        assert await ledger.record_refund_failure(
            stripe_payment_intent_id="pi_1",
            refund_id="re_1",
            reason="expired_or_canceled_card",
            amount_cents=5_000,
            failed_at=NOW,
        )
    assert not await ledger.record_refund_failure(
        stripe_payment_intent_id="pi_unknown",
        refund_id="re_2",
        reason="x",
        amount_cents=1,
        failed_at=NOW,
    )

    listed = await ledger.list_refund_failures()
    assert listed["count"] == 1
    (row,) = listed["rows"]
    failed_at = row.pop("failed_at")
    assert failed_at.replace(tzinfo=UTC) == NOW
    assert row == {
        "payment_id": "pay-1",
        "parent_id": "parent-1",
        "currency": "usd",
        "refund_id": "re_1",
        "reason": "expired_or_canceled_card",
        "amount_cents": 5_000,
    }


class _Ledger:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_refund_failure(self, **kwargs) -> bool:
        self.calls.append(kwargs)
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "status", "recorded"),
    [
        ("refund.failed", "failed", True),
        ("refund.updated", "failed", True),
        ("refund.updated", "succeeded", False),
    ],
)
async def test_webhook_flags_only_failed_refunds(
    event_type: str, status: str, recorded: bool
) -> None:
    from backend.v2.tests.application.test_webhook_handler import (
        FakePaymentRepo,
        _build,
    )

    ledger = _Ledger()
    uc = _build(FakePaymentRepo(), billing_ledger=ledger)
    body = json.dumps(
        {
            "id": f"evt_{event_type}_{status}",
            "type": event_type,
            "livemode": True,
            "data": {
                "object": {
                    "id": "re_1",
                    "object": "refund",
                    "status": status,
                    "payment_intent": "pi_1",
                    "amount": 5_000,
                    "failure_reason": "lost_or_stolen_card",
                }
            },
        }
    ).encode()

    await uc.execute(body, "test_signature")

    assert bool(ledger.calls) is recorded
