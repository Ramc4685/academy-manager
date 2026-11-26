"""S57: the parent money summary is computed from the ledger, never guessed."""

from __future__ import annotations

from datetime import UTC, date, datetime

from backend.v2.contexts.billing.application.parent_money import (
    PaymentFact,
    build_money_summary,
    method_label,
)
from backend.v2.contexts.billing.domain.ledger import InvoiceLine, LedgerInvoice

_T = datetime(2026, 11, 1, tzinfo=UTC)


def _inv(invoice_id, student_id, *, total, balance, status="open", period="2026-11",
         due=date(2026, 12, 1), enrollment_id=None, subtotal=None) -> LedgerInvoice:
    return LedgerInvoice(
        invoice_id=invoice_id, academy_id="acad", parent_id="p1", student_id=student_id,
        enrollment_id=enrollment_id, period=period, status=status,
        subtotal_cents=subtotal if subtotal is not None else total,
        discount_cents=(subtotal - total) if subtotal is not None else 0,
        total_cents=total, balance_due_cents=balance, due_date=due,
        created_at=_T, updated_at=_T,
    )


def _line(invoice_id, description, cents) -> InvoiceLine:
    return InvoiceLine(
        line_id=f"{invoice_id}-{description}", academy_id="acad", invoice_id=invoice_id,
        line_type="discount" if cents < 0 else "tuition", description=description,
        quantity=1, unit_amount_cents=cents, amount_cents=cents, created_at=_T,
    )


def _summary(invoices, lines, facts=(), today=date(2026, 11, 20)):
    return build_money_summary(
        invoices=invoices,
        lines_by_invoice=lines,
        facts=facts,
        child_names={"sam": "Sam Demo", "alex": "Alex Demo"},
        class_by_enrollment={"e-sam": "Junior Beginners", "e-alex": "Junior Beginners"},
        today=today,
        timezone_name="America/Chicago",
        can_pay_online=True,
    )


def test_two_children_and_a_sibling_discount_add_up_to_the_family_total() -> None:
    sam = _inv("i-sam", "sam", total=8000, balance=8000, enrollment_id="e-sam")
    alex = _inv("i-alex", "alex", total=6000, balance=6000, enrollment_id="e-alex", subtotal=8000)
    out = _summary(
        [sam, alex],
        {
            "i-sam": [_line("i-sam", "Tuition", 8000)],
            "i-alex": [_line("i-alex", "Tuition", 8000), _line("i-alex", "Sibling discount", -2000)],
        },
    )
    assert out["amount_due_cents"] == 14000
    assert out["due_date"] == date(2026, 12, 1)
    assert [(line["kind"], line["label"], line["amount_cents"]) for line in out["lines"]] == [
        ("child", "Alex Demo", 8000),
        ("child", "Sam Demo", 8000),
        ("discount", "Sibling discount", -2000),
    ]
    assert out["lines"][0]["detail"] == "Junior Beginners · November"
    assert sum(line["amount_cents"] for line in out["lines"]) == out["amount_due_cents"]


def test_partial_payment_is_an_already_paid_line_and_draft_void_paid_are_not_due() -> None:
    part = _inv("i1", "sam", total=8000, balance=3000, status="partially_paid")
    out = _summary(
        [
            part,
            _inv("i2", "sam", total=5000, balance=5000, status="draft"),
            _inv("i3", "alex", total=5000, balance=5000, status="void"),
            _inv("i4", "alex", total=5000, balance=0, status="paid", period="2026-10"),
        ],
        {"i1": [_line("i1", "Tuition", 8000)]},
    )
    assert out["amount_due_cents"] == 3000
    assert out["lines"][-1] == {
        "kind": "paid", "student_id": None, "label": "Already paid", "detail": None,
        "amount_cents": -5000,
    }
    assert sum(line["amount_cents"] for line in out["lines"]) == 3000
    assert [p["period"] for p in out["periods"]] == ["2026-11", "2026-10"]
    assert out["periods"][0] == {
        "period": "2026-11", "label": "November 2026",
        "billed_cents": 8000, "paid_cents": 5000, "due_cents": 3000,
    }


def test_lines_that_do_not_explain_the_total_fall_back_to_the_balance() -> None:
    # Credit applied at mint: lines say 8000, total says 6000. Never itemize it.
    inv = _inv("i1", "sam", total=6000, balance=6000)
    out = _summary([inv], {"i1": [_line("i1", "Tuition", 8000)]})
    assert [(line["kind"], line["amount_cents"]) for line in out["lines"]] == [("child", 6000)]


def test_nothing_due_reports_the_last_settled_payment_in_words() -> None:
    paid = _inv("i1", "sam", total=6000, balance=0, status="paid", period="2026-10")
    facts = [
        PaymentFact("i1", "pay-1", 4000, datetime(2026, 10, 3, 15, tzinfo=UTC), "cash"),
        PaymentFact("i1", "pay-0", 2000, datetime(2026, 9, 30, 15, tzinfo=UTC), "check"),
        PaymentFact("other-family", "pay-9", 9900, datetime(2026, 11, 1, tzinfo=UTC), "zelle"),
    ]
    out = _summary([paid], {}, facts)
    assert out["amount_due_cents"] == 0
    assert out["lines"] == []
    assert out["due_date"] is None
    assert out["last_payment"] == {
        "amount_cents": 4000, "paid_on": date(2026, 10, 3), "method_label": "Paid in cash",
    }


def test_overdue_counts_days_on_the_academy_date_and_flags_two_due_dates() -> None:
    out = _summary(
        [
            _inv("i1", "sam", total=100, balance=100, due=date(2026, 11, 1)),
            _inv("i2", "alex", total=100, balance=100, due=date(2026, 12, 1)),
        ],
        {},
        today=date(2026, 11, 26),
    )
    assert out["overdue"] is True
    assert out["days_overdue"] == 25
    assert out["multiple_due_dates"] is True


def test_method_label_never_claims_card_for_a_checkout_that_may_be_bank_debit() -> None:
    assert method_label("cash") == "Paid in cash"
    assert method_label("stripe_checkout") == "Paid online"
    assert method_label("stripe_autopay") == "Paid by autopay"
    assert method_label(None) == "Paid"
