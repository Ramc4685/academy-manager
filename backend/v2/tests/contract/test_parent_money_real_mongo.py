"""S57: the parent money summary over the real ledger store.

Settled payments only, live allocations only, the caller's family and academy
only. Run against real Mongo in CI (CONTRACT_TESTS_MONGO_URL).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.composition.parent_money_summary import (
    can_pay_online_from,
    compose_parent_money,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_payment_facts import (
    MongoParentPaymentFacts,
)

_T = datetime(2026, 11, 1, tzinfo=UTC)


def _invoice(
    invoice_id,
    parent_id,
    student_id,
    *,
    total,
    balance,
    status,
    period,
    academy_id="test-academy",
    subtotal=None,
):
    return {
        "invoice_id": invoice_id,
        "academy_id": academy_id,
        "parent_id": parent_id,
        "student_id": student_id,
        "enrollment_id": f"e-{student_id}",
        "period": period,
        "status": status,
        "subtotal_cents": subtotal or total,
        "discount_cents": (subtotal or total) - total,
        "total_cents": total,
        "balance_due_cents": balance,
        "currency": "usd",
        "due_date": "2026-12-01",
        "created_at": _T,
        "updated_at": _T,
    }


def _line(invoice_id, description, cents, academy_id="test-academy"):
    return {
        "line_id": f"{invoice_id}-{description}",
        "academy_id": academy_id,
        "invoice_id": invoice_id,
        "line_type": "discount" if cents < 0 else "tuition",
        "description": description,
        "quantity": 1,
        "unit_amount_cents": cents,
        "amount_cents": cents,
        "created_at": _T,
    }


def _payment(payment_id, status, method, paid_at, academy_id="test-academy"):
    return {
        "payment_id": payment_id,
        "academy_id": academy_id,
        "parent_id": "p1",
        "amount_cents": 6000,
        "unapplied_amount_cents": 0,
        "currency": "usd",
        "status": status,
        "payment_method": method,
        "paid_at": paid_at,
        "created_at": paid_at,
        "updated_at": paid_at,
    }


def _alloc(allocation_id, payment_id, invoice_id, cents, academy_id="test-academy"):
    return {
        "allocation_id": allocation_id,
        "academy_id": academy_id,
        "payment_id": payment_id,
        "invoice_id": invoice_id,
        "amount_cents": cents,
        "created_at": _T,
    }


async def _seed(db) -> None:
    await db["invoices"].insert_many(
        [
            _invoice(
                "nov-sam", "p1", "sam", total=8000, balance=8000, status="open", period="2026-11"
            ),
            _invoice(
                "nov-alex",
                "p1",
                "alex",
                total=6000,
                balance=6000,
                status="open",
                period="2026-11",
                subtotal=8000,
            ),
            _invoice(
                "oct-sam", "p1", "sam", total=6000, balance=0, status="paid", period="2026-10"
            ),
            # Another family here, and the same family id in another academy.
            _invoice(
                "nov-other", "p2", "kim", total=9900, balance=9900, status="open", period="2026-11"
            ),
            _invoice(
                "nov-elsewhere",
                "p1",
                "sam",
                total=7700,
                balance=7700,
                status="open",
                period="2026-11",
                academy_id="other-academy",
            ),
        ]
    )
    await db["invoice_lines"].insert_many(
        [
            _line("nov-sam", "Tuition", 8000),
            _line("nov-alex", "Tuition", 8000),
            _line("nov-alex", "Sibling discount", -2000),
            _line("oct-sam", "Tuition", 6000),
        ]
    )
    await db["ledger_payments"].insert_many(
        [
            _payment("cash-oct", "succeeded", "cash", datetime(2026, 10, 3, 16, tzinfo=UTC)),
            _payment("failed-nov", "failed", "stripe_checkout", datetime(2026, 11, 5, tzinfo=UTC)),
            _payment(
                "cash-elsewhere",
                "succeeded",
                "cash",
                datetime(2026, 11, 9, tzinfo=UTC),
                academy_id="other-academy",
            ),
        ]
    )
    await db["payment_allocations"].insert_many(
        [
            _alloc("a1", "cash-oct", "oct-sam", 6000),
            _alloc("a2", "failed-nov", "nov-sam", 6000),
            _alloc("a3", "cash-elsewhere", "oct-sam", 6000, academy_id="other-academy"),
        ]
    )


def _money(db, ledger, enrollment_reads=None):
    async def children(_parent_id):
        return [
            {"student_id": "sam", "full_name": "Sam Demo"},
            {"student_id": "alex", "full_name": "Alex Demo"},
        ]

    async def enrollments(_parent_id):
        if enrollment_reads is not None:
            enrollment_reads.append(_parent_id)
        return [
            {
                "enrollment_id": "e-sam",
                "session_title": "Junior Beginners",
                "autopay_offer": "available",
            }
        ]

    async def get_invoice(*, parent_id, invoice_id):
        # The real GetParentInvoice rule: tenant-scoped read, then ownership.
        invoice = await ledger.get_invoice(invoice_id)
        if invoice is None or invoice.parent_id != parent_id:
            return None
        return {"invoice": invoice, "lines": await ledger.get_lines_for_invoice(invoice_id)}

    async def academy_info(*, academy_id):
        return {
            "display_name": "Demo Academy",
            "address": "12 Court Lane",
            "contact_phone": "(309) 555-0142",
            "contact_email": "hello@example.com",
            "logo_url": None,
        }

    async def payer(_parent_id):
        return "Demo Parent"

    return compose_parent_money(
        db,
        list_invoices=ledger.list_invoices_for_parent,
        get_invoice=get_invoice,
        get_lines=ledger.get_lines_for_invoice,
        list_children=children,
        list_enrollments=enrollments,
        get_academy_info=academy_info,
        payer_name=payer,
        clock=lambda: datetime(2026, 11, 20, 18, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_payment_facts_keep_settled_payments_in_this_academy_only(db, acad) -> None:
    await _seed(db)
    facts = await MongoParentPaymentFacts(db).for_invoices(["oct-sam", "nov-sam"])
    assert [(f.invoice_id, f.payment_id, f.amount_cents, f.method) for f in facts] == [
        ("oct-sam", "cash-oct", 6000, "cash")
    ]
    assert facts[0].paid_at == datetime(2026, 10, 3, 16, tzinfo=UTC)


@pytest.mark.asyncio
async def test_summary_is_the_callers_own_ledger_with_the_discount_as_its_own_line(
    db, acad
) -> None:
    await _seed(db)
    ledger = MongoBillingLedgerRepository(db)

    reads: list[str] = []
    money = _money(db, ledger, reads)
    out = await money.summary("p1")
    assert reads == ["p1"]  # the heavy enrollment read happens once per summary

    assert out["amount_due_cents"] == 14000  # never p2's 9900, never the other academy's 7700
    assert sum(line["amount_cents"] for line in out["lines"]) == out["amount_due_cents"]
    assert [(line["kind"], line["label"], line["amount_cents"]) for line in out["lines"]] == [
        ("child", "Alex Demo", 8000),
        ("child", "Sam Demo", 8000),
        ("discount", "Sibling discount", -2000),
    ]
    assert out["due_date"] == date(2026, 12, 1)
    assert out["last_payment"]["method_label"] == "Paid in cash"
    assert out["last_payment"]["paid_on"] == date(2026, 10, 3)

    invoices = await ledger.list_invoices_for_parent("p1")
    extras = await money.invoice_extras("p1", invoices)
    assert extras["oct-sam"]["has_receipt"] is True
    assert extras["oct-sam"]["method_label"] == "Paid in cash"
    assert extras["oct-sam"]["student_name"] == "Sam Demo"
    assert extras["nov-sam"]["class_name"] == "Junior Beginners"
    assert extras["nov-sam"]["paid_on"] is None  # the failed charge never counts


def test_can_pay_online_is_false_only_when_every_live_class_is_desk_paid_or_free() -> None:
    desk = {"autopay_offer": "manual_payments"}
    free = {"autopay_offer": "free_class"}
    online = {"autopay_offer": "available"}
    assert can_pay_online_from([desk, free]) is False
    assert can_pay_online_from([desk, online]) is True
    assert can_pay_online_from([]) is True
    assert can_pay_online_from([desk | {"departed": True}, online]) is True


@pytest.mark.asyncio
async def test_receipt_only_for_the_callers_paid_invoice(db, acad) -> None:
    await _seed(db)
    money = _money(db, MongoBillingLedgerRepository(db))

    receipt = await money.receipt("p1", "oct-sam")
    assert receipt is not None
    assert receipt["academy"]["name"] == "Demo Academy"
    assert receipt["payer_name"] == "Demo Parent"
    assert receipt["student_name"] == "Sam Demo"
    assert receipt["period_label"] == "October 2026"
    assert receipt["lines"] == [{"label": "Tuition", "amount_cents": 6000}]
    assert receipt["payments"] == [
        {"paid_on": date(2026, 10, 3), "method": "Cash", "amount_cents": 6000}
    ]
    assert receipt["balance_cents"] == 0
    assert receipt["refunded_cents"] == 0
    assert receipt["paid_in_full_on"] == date(2026, 10, 3)

    assert await money.receipt("p1", "nov-sam") is None  # unpaid
    assert await money.receipt("p2", "oct-sam") is None  # another family
    assert await money.receipt("p1", "nov-elsewhere") is None  # another academy
