"""The naming resolver behind parent-facing billing emails (#659)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

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


def _resolver(db, ledger, *, now: datetime = NOW):
    return build_invoice_naming_resolver(
        ledger=ledger,
        db=db,
        billing_counters=MongoBillingCounterRepository(db),
        billing_settings=MongoBillingSettingsRepository(db),
        now=lambda: now,
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


async def _pay(db, acad: str, *, invoice_id: str, amount_cents: int, created_at: datetime) -> None:
    """A settled charge: the allocation row is what proves money moved."""
    await db["payment_allocations"].insert_one(
        {
            "allocation_id": f"alloc-{invoice_id}",
            "academy_id": acad,
            "payment_id": f"pay-{invoice_id}",
            "invoice_id": invoice_id,
            "amount_cents": amount_cents,
            "created_at": created_at,
        }
    )


async def _august_invoice(db, acad: str, ledger) -> None:
    await ledger.create_invoice(
        _invoice(acad).model_copy(
            update={
                "invoice_id": "inv-monthly-enroll-1-2026-08",
                "period": "2026-08",
                "status": "paid",
                "balance_due_cents": 0,
                "due_date": date(2026, 8, 8),
            }
        ),
        lines=[],
        idempotency_key="k-aug",
    )


async def test_resolves_the_last_charge_on_the_same_enrollment(db, acad) -> None:
    """Issue #659: September's notice must name August's charge, or the two
    read as one duplicate."""
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(_invoice(acad), lines=[], idempotency_key="k1")
    await _august_invoice(db, acad, ledger)
    await _pay(
        db,
        acad,
        invoice_id="inv-monthly-enroll-1-2026-08",
        amount_cents=7_000,
        created_at=datetime(2026, 8, 30, 15, 0, tzinfo=UTC),
    )

    naming = await _resolver(db, ledger)("inv-monthly-enroll-1-2026-09")

    assert naming.last_charge is not None
    assert naming.last_charge.amount_cents == 7_000
    assert naming.last_charge.period == "2026-08"
    assert naming.last_charge.charged_on == date(2026, 8, 30)


async def test_no_last_charge_when_nothing_was_paid(db, acad) -> None:
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(_invoice(acad), lines=[], idempotency_key="k1")
    await _august_invoice(db, acad, ledger)

    naming = await _resolver(db, ledger)("inv-monthly-enroll-1-2026-09")

    assert naming.last_charge is None


async def test_charges_older_than_the_window_are_not_named(db, acad) -> None:
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(_invoice(acad), lines=[], idempotency_key="k1")
    await _august_invoice(db, acad, ledger)
    await _pay(
        db,
        acad,
        invoice_id="inv-monthly-enroll-1-2026-08",
        amount_cents=7_000,
        created_at=NOW - timedelta(days=46),
    )

    naming = await _resolver(db, ledger)("inv-monthly-enroll-1-2026-09")

    assert naming.last_charge is None


async def test_the_invoice_being_sent_is_never_its_own_last_charge(db, acad) -> None:
    """A partial payment on September must not be quoted back as "your last
    charge" inside September's own notice."""
    ledger = MongoBillingLedgerRepository(db)
    await _seed_roster(db, acad)
    await ledger.create_invoice(_invoice(acad), lines=[], idempotency_key="k1")
    await _pay(
        db,
        acad,
        invoice_id="inv-monthly-enroll-1-2026-09",
        amount_cents=2_000,
        created_at=datetime(2026, 8, 31, 12, 0, tzinfo=UTC),
    )

    naming = await _resolver(db, ledger)("inv-monthly-enroll-1-2026-09")

    assert naming.last_charge is None
