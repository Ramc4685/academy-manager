"""A failed monthly invoice run retries without duplicating anything (G:jobs_data_infra:2).

The job now fails the academy's local-day marker when generation failed, was
partial, or the email pass itself raised, so the scheduler re-runs it on the next
hourly tick. A single failed email does not: SendInvoice records delivery_failed
and returns, and the next run's send pass picks that invoice up again. Both are
only safe if a re-run neither mints a second invoice nor re-emails a parent who
already got one: proven here on a real mongod with the production
indexes, the real generation path and the real undelivered-invoice query.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.v2.contexts.billing.application.use_cases.send_generated_invoices import (
    SendGeneratedInvoices,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.main import (
    _monthly_generation_retry_reason,
    _record_monthly_generation,
    _run_monthly_invoice_generation,
)
from backend.v2.tests.contract.test_monthly_invoice_numbering import _seed

pytestmark = pytest.mark.asyncio


async def test_retried_runs_create_one_invoice_and_send_one_email(real_db, acad) -> None:
    await _seed(real_db, acad, enrollment_id="enroll-1", student_id="student-1")
    # August already invoiced, so only September is in play.
    await _record_monthly_generation(
        real_db, acad, "2026-08", datetime(2026, 8, 1, 3, 0), logging.getLogger(__name__)
    )
    ledger = MongoBillingLedgerRepository(real_db)
    repo = MongoPaymentRepository(
        real_db, clock=lambda: datetime(2026, 9, 1, 8, 0, tzinfo=UTC), ledger_repo=ledger
    )
    generate_calls = 0
    send_calls: list[str] = []
    delivered: list[str] = []

    async def _generate(period: str):
        nonlocal generate_calls
        generate_calls += 1
        if generate_calls == 1:
            raise RuntimeError("mongo blip")
        return await repo.generate_monthly_payments(period)

    async def _send_one(invoice_id: str) -> None:
        # Mirrors SendInvoice: an email error is recorded, never raised.
        send_calls.append(invoice_id)
        outcome = "delivery_failed" if len(send_calls) == 1 else "sent"
        await real_db["invoices"].update_one(
            {"academy_id": acad, "invoice_id": invoice_id},
            {"$set": {"delivery_status": outcome}},
        )
        if outcome == "sent":
            delivered.append(invoice_id)

    async def _send_invoices(period: str):
        return await SendGeneratedInvoices(ledger=ledger, send=_send_one).execute(period)

    async def _settings():
        return SimpleNamespace(billing_day=1)

    async def _tick(hour: int) -> str | None:
        totals = await _run_monthly_invoice_generation(
            db=real_db,
            academy_ids=[acad],
            get_billing_settings=_settings,
            generate=_generate,
            now=datetime(2026, 9, 1, hour, 5),
            send_invoices=_send_invoices,
        )
        return _monthly_generation_retry_reason(totals)

    assert await _tick(3) == "generation_failed=1"
    assert await _tick(4) is None  # the email failed, recorded as delivery_failed
    assert await _tick(5) is None
    assert await _tick(6) is None

    invoice_ids = [
        doc["invoice_id"] async for doc in real_db["invoices"].find({"academy_id": acad})
    ]
    assert invoice_ids == ["inv-monthly-enroll-1-2026-09"]
    # Generated once the gate allowed it, then never again once recorded.
    assert generate_calls == 2
    assert delivered == invoice_ids
    assert send_calls == invoice_ids * 2  # the failed send, then the one that landed

    # Even an unrecorded (partial) period re-runs generation safely.
    again = await repo.generate_monthly_payments("2026-09")
    assert again.created == 0
    assert await real_db["invoices"].count_documents({"academy_id": acad}) == 1
