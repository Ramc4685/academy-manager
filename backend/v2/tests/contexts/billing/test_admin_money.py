"""Money-path semantics for the admin billing helpers (MT1 Phase A).

These pin the behaviour the production-readiness audit called out before the
reports/payout pipelines move out of the composition root.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from backend.v2.contexts.billing.application.admin_money import (
    aging_label,
    cents_to_dollars,
    coerce_report_datetime,
    invoice_final_amount_cents,
    invoice_outstanding_cents,
    invoice_paid_cents,
    invoice_to_admin_payment_row,
    legacy_payment_cash_candidate_query,
    month_bounds,
    payment_collected_cents,
    payment_effective_month,
    payment_final_amount_cents,
    payment_outstanding_cents,
    round_money_minor,
)


def test_month_bounds_wraps_year_at_december() -> None:
    assert month_bounds("2026-12") == (
        datetime(2026, 12, 1, tzinfo=UTC),
        datetime(2027, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("payment", "expected"),
    [
        ({"final_amount_cents": 4500}, 4500),
        ({"final_amount": 45.0}, 4500),
        # discount applies only to the gross-amount fallbacks
        ({"amount_cents": 5000, "discount_cents": 500}, 4500),
        ({"amount": 50.0, "discount": 5.0}, 4500),
        # discount larger than gross clamps at zero rather than going negative
        ({"amount_cents": 1000, "discount_cents": 2500}, 0),
        ({}, 0),
    ],
)
def test_payment_final_amount_cents(payment: dict[str, object], expected: int) -> None:
    assert payment_final_amount_cents(payment) == expected


def test_payment_collected_cents_nets_refunds_on_settled_payments() -> None:
    assert (
        payment_collected_cents(
            {"status": "partially_refunded", "paid_amount_cents": 5000, "refunded_cents": 1500}
        )
        == 3500
    )


def test_payment_collected_cents_ignores_amounts_on_unknown_status() -> None:
    assert payment_collected_cents({"status": "cancelled", "paid_amount_cents": 5000}) == 0


def test_payment_outstanding_cents_zero_unless_unsettled() -> None:
    assert payment_outstanding_cents({"status": "succeeded", "balance_due_cents": 2500}) == 0
    assert payment_outstanding_cents({"status": "pending", "balance_due_cents": 2500}) == 2500
    assert (
        payment_outstanding_cents(
            {"status": "partially_paid", "amount_cents": 5000, "paid_amount_cents": 2000}
        )
        == 3000
    )


def test_invoice_outstanding_cents_is_zero_for_terminal_statuses() -> None:
    for status in ("paid", "void", "waived", "cancelled"):
        assert invoice_outstanding_cents({"status": status, "balance_due_cents": 9900}) == 0
    assert invoice_outstanding_cents({"status": "open", "balance_due_cents": 9900}) == 9900


def test_invoice_paid_cents_derives_from_total_minus_balance() -> None:
    assert invoice_paid_cents({"total_cents": 10000, "balance_due_cents": 2500}) == 7500
    # a credit balance must not inflate the paid figure past the total
    assert invoice_paid_cents({"total_cents": 10000, "balance_due_cents": -500}) == 10000


def test_invoice_final_amount_falls_back_to_subtotal_plus_discount() -> None:
    assert invoice_final_amount_cents({"total_cents": 0, "subtotal_cents": 8000}) == 8000


def test_invoice_to_admin_payment_row_marks_stripe_linked_and_maps_status() -> None:
    row = invoice_to_admin_payment_row(
        {
            "invoice_id": "inv_1",
            "parent_id": "parent_1",
            "status": "open",
            "total_cents": 10000,
            "balance_due_cents": 4000,
            "discount_cents": 500,
            "stripe_payment_intent_id": "pi_123",
        }
    )
    assert row["status"] == "pending"
    assert row["payment_method"] == "stripe"
    assert row["stripe_linked"] is True
    assert row["final_amount_cents"] == 10000
    assert row["paid_amount_cents"] == 6000
    assert row["balance_due_cents"] == 4000


def test_invoice_to_admin_payment_row_without_stripe_ids_is_invoice_method() -> None:
    row = invoice_to_admin_payment_row(
        {"invoice_id": "inv_2", "status": "void", "total_cents": 100}
    )
    assert row["payment_method"] == "invoice"
    assert row["stripe_linked"] is False
    assert row["status"] == "waived"


def test_payment_effective_month_prefers_paid_at_then_falls_back_to_period() -> None:
    assert payment_effective_month({"paid_at": "2026-03-15T10:00:00Z", "period": "2026-01"}) == (
        "2026-03"
    )
    assert payment_effective_month({"period": "2026-01"}) == "2026-01"
    assert payment_effective_month({}) == ""


def test_coerce_report_datetime_normalises_to_utc() -> None:
    assert coerce_report_datetime("2026-03-15") == datetime(2026, 3, 15, tzinfo=UTC)
    assert coerce_report_datetime(date(2026, 3, 15)) == datetime(2026, 3, 15, tzinfo=UTC)
    assert coerce_report_datetime("not-a-date") is None
    assert coerce_report_datetime("") is None


def test_legacy_payment_cash_candidate_query_is_tenant_scoped() -> None:
    query = legacy_payment_cash_candidate_query(
        "acad_1", "2026-03", datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 4, 1, tzinfo=UTC)
    )
    assert query["academy_id"] == "acad_1"


def test_aging_label_buckets() -> None:
    assert [aging_label(n) for n in (0, 1, 30, 31, 60, 61)] == [
        "Current",
        "1-30",
        "1-30",
        "31-60",
        "31-60",
        "60+",
    ]


def test_cents_to_dollars_and_round_money_minor() -> None:
    assert cents_to_dollars(12345) == "123.45"
    # banker's rounding: .5 goes to the nearest even minor unit
    assert round_money_minor(Decimal("2.5")) == 2
    assert round_money_minor(Decimal("3.5")) == 4
