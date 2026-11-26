"""S33: the monthly run's per-enrollment classification, on a real mongod.

The classifier was extracted out of ``generate_monthly_payments`` as a pure
refactor. The counts below were recorded on this fixture month with the
generator BEFORE the extraction; they must not move. Real Mongo (migrations
applied), not mongomock, because the run leans on the invoice-key unique index.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    MongoMonthlyBillingGenerator,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository

pytestmark = pytest.mark.asyncio

ACAD = "test-academy"
NOW = datetime(2026, 11, 16, 18, tzinfo=UTC)
PERIOD = "2026-11"


async def _seed(db: Any) -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": ACAD,
            "session_id": "sess-1",
            "title": "Juniors",
            "monthly_price_cents": 10_000,
            "days_of_week": ["Tue"],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "status": "active",
        }
    )
    kids = {
        "enr-bill-1": {},
        "enr-bill-2": {"billing_type": "Manual"},
        "enr-paused": {"status": "paused"},
        "enr-free": {"billing_type": "NoCharge"},
        "enr-invoiced": {},
    }
    for i, (enrollment_id, extra) in enumerate(kids.items()):
        student_id = f"kid-{i}"
        await db["students"].insert_one(
            {
                "academy_id": ACAD,
                "student_id": student_id,
                "parent_id": f"parent-{i}",
                "full_name": f"Kid {i}",
            }
        )
        await db["enrollments"].insert_one(
            {
                "academy_id": ACAD,
                "enrollment_id": enrollment_id,
                "student_id": student_id,
                "session_id": "sess-1",
                "parent_id": f"parent-{i}",
                "status": "active",
                "billing_type": "Standard",
                "billing_start_at": datetime(2026, 1, 1, tzinfo=UTC),
                "created_at": datetime(2026, 1, 1, i, tzinfo=UTC),
                **extra,
            }
        )
    # Already invoiced this month under a non-monthly id ("Bill this month").
    await MongoBillingLedgerRepository(db).create_invoice(
        LedgerInvoice(
            invoice_id="inv-manual",
            academy_id=ACAD,
            parent_id="parent-4",
            enrollment_id="enr-invoiced",
            period=PERIOD,
            status="open",
            subtotal_cents=10_000,
            total_cents=10_000,
            balance_due_cents=10_000,
            currency="usd",
            due_date=date(2026, 11, 8),
            created_at=NOW,
            updated_at=NOW,
        ),
        lines=[
            InvoiceLine(
                line_id="inv-manual-0",
                academy_id=ACAD,
                invoice_id="inv-manual",
                line_type="tuition",
                description="tuition",
                quantity=1,
                unit_amount_cents=10_000,
                amount_cents=10_000,
                created_at=NOW,
            )
        ],
        idempotency_key="seed:inv-manual",
    )


def _repo(db: Any) -> MongoPaymentRepository:
    return MongoPaymentRepository(
        db, clock=lambda: NOW, ledger_repo=MongoBillingLedgerRepository(db)
    )


def _counts(result: Any) -> dict[str, int]:
    return {
        "created": result.created,
        "skipped_existing": result.skipped_existing,
        "skipped_no_charge": result.skipped_no_charge,
        "skipped_paused": result.skipped_paused,
        "failed_repair": result.failed_repair,
    }


async def test_generate_counts_unchanged_by_the_classifier_extraction(real_db, acad) -> None:
    await _seed(real_db)

    first = await _repo(real_db).generate_monthly_payments(PERIOD)
    # Recorded with the pre-extraction generator on this fixture.
    assert _counts(first) == {
        "created": 2,
        "skipped_existing": 1,
        "skipped_no_charge": 1,
        "skipped_paused": 1,
        "failed_repair": 0,
    }
    assert [d.enrollment_id for d in first.skipped_details] == ["enr-paused"]

    # The idempotency keys still hold: a rerun creates nothing new.
    again = await _repo(real_db).generate_monthly_payments(PERIOD)
    assert _counts(again) == {
        "created": 0,
        "skipped_existing": 3,
        "skipped_no_charge": 1,
        "skipped_paused": 1,
        "failed_repair": 0,
    }
    assert await real_db["invoices"].count_documents({"period": PERIOD}) == 3


async def test_classifier_is_read_only_and_matches_the_run(real_db, acad) -> None:
    await _seed(real_db)
    generator = MongoMonthlyBillingGenerator(_repo(real_db))

    # A legacy payment row for the month (pre-ledger shape) classifies "existing".
    await real_db["payments"].insert_one(
        {
            "academy_id": ACAD,
            "payment_id": "pay-legacy",
            "enrollment_id": "enr-legacy",
            "period": PERIOD,
            "amount_cents": 10_000,
            "status": "pending",
        }
    )
    await real_db["enrollments"].insert_one(
        {
            "academy_id": ACAD,
            "enrollment_id": "enr-legacy",
            "student_id": "kid-0",
            "session_id": "sess-1",
            "parent_id": "parent-0",
            "status": "active",
            "billing_type": "Standard",
            "billing_start_at": datetime(2026, 1, 1, tzinfo=UTC),
            "created_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
    )

    async def snapshot() -> dict[str, list[str]]:
        # Full content, not counts: an in-place $set must show up too.
        return {
            name: sorted(
                repr(sorted(doc.items())) for doc in await real_db[name].find({}).to_list(None)
            )
            for name in await real_db.list_collection_names()
            if not name.startswith("system.")
        }

    before = await snapshot()
    kinds = {
        c.enrollment_id: c.kind
        async for c in generator.classify_monthly_enrollments(
            PERIOD, now=NOW, academy_timezone="America/Chicago"
        )
    }
    assert await snapshot() == before
    # enr-invoiced is only a "candidate": its ledger invoice is found later, at
    # the (writing) invoice-key step, which is what keeps the run's counts intact.
    assert kinds == {
        "enr-bill-1": "candidate",
        "enr-bill-2": "candidate",
        "enr-paused": "skip",
        "enr-free": "not_billed",
        "enr-invoiced": "candidate",
        "enr-legacy": "existing",
    }
