"""The naming resolver behind parent-facing billing emails (#659)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.composition.invoice_naming import build_invoice_naming_resolver
from backend.v2.contexts.billing.domain.ledger import LedgerInvoice, record_delivery
from backend.v2.contexts.billing.infrastructure.mongo_billing_counter_repo import (
    MongoBillingCounterRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _invoice(acad: str, *, invoice_number: str | None = None) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id="inv-monthly-enroll-1-2026-09",
        invoice_number=invoice_number,
        academy_id=acad,
        parent_id="parent-1",
        student_id="student-1",
        enrollment_id="enroll-1",
        period="2026-09",
        status="open",
        subtotal_cents=7_000,
        total_cents=7_000,
        balance_due_cents=7_000,
        due_date=date(2026, 9, 8),
        created_at=NOW,
        updated_at=NOW,
    )


async def _seed_roster(db, acad: str) -> None:
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "student-1",
            "parent_id": "parent-1",
            "full_name": "Arjun Kumar",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-1",
            "session_id": "sess-1",
            "student_id": "student-1",
        }
    )
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-1",
            "name": "Beginners",
            "days_of_week": ["Sat"],
            "start_time": "09:00",
        }
    )


def _resolver(db, ledger):
    return build_invoice_naming_resolver(
        ledger=ledger,
        db=db,
        billing_counters=MongoBillingCounterRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
    )


async def test_resolves_student_class_and_existing_number(db, acad) -> None:
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(
        _invoice(acad, invoice_number="BLNO-2026-09-0042"), lines=[], idempotency_key="k1"
    )

    naming = await _resolver(db, ledger)("inv-monthly-enroll-1-2026-09")

    assert naming.student_name == "Arjun Kumar"
    assert naming.session_label == "Sat 09:00 Beginners"
    assert naming.invoice_number == "BLNO-2026-09-0042"


async def test_legacy_invoice_gets_a_number_lazily_and_keeps_it(db, acad) -> None:
    """Owner decision: historical invoices keep their id and gain a number on
    first display/send — and the same invoice must not renumber on each send."""
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(_invoice(acad), lines=[], idempotency_key="k1")
    resolve = _resolver(db, ledger)

    first = await resolve("inv-monthly-enroll-1-2026-09")
    second = await resolve("inv-monthly-enroll-1-2026-09")

    assert first.invoice_number
    assert "-2026-09-" in first.invoice_number
    assert second.invoice_number == first.invoice_number
    stored = await ledger.get_invoice("inv-monthly-enroll-1-2026-09")
    assert stored is not None
    assert stored.invoice_number == first.invoice_number


async def test_lazy_mint_does_not_break_the_delivery_write_that_follows_it(db, acad) -> None:
    """The send path holds an invoice across the email call. Numbering must not
    bump its optimistic-concurrency version underneath it, or the very invoices
    this back-fills would fail to record delivery."""
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(_invoice(acad), lines=[], idempotency_key="k1")
    held = await ledger.get_invoice("inv-monthly-enroll-1-2026-09")
    assert held is not None

    naming = await _resolver(db, ledger)("inv-monthly-enroll-1-2026-09")
    assert naming.invoice_number

    delivered = await ledger.save_invoice(
        record_delivery(held, outcome="sent", now=NOW, provider_message_id="msg_1")
    )

    assert delivered.delivery_status == "sent"
    stored = await ledger.get_invoice("inv-monthly-enroll-1-2026-09")
    assert stored is not None
    assert stored.delivery_status == "sent"
    # The stale in-memory copy carried invoice_number=None; persisting it must
    # not take the number back off the invoice the parent was just shown.
    assert stored.invoice_number == naming.invoice_number


async def test_unknown_invoice_resolves_to_empty_naming(db, acad) -> None:
    ledger = MongoBillingLedgerRepository(db)

    naming = await _resolver(db, ledger)("inv-does-not-exist")

    assert naming.student_name is None
    assert naming.session_label is None
    assert naming.invoice_number is None
