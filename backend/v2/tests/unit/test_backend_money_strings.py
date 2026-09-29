"""The four backend ``$`` sites go through the shared ``format_money`` (row 12).

Every string here is what BLNO (USD) shows today. The helpers now route through
``shared/comms/email_theme.format_money`` instead of hand-rolled ``f"${...}"``,
so these tables pin the output byte for byte: an ungrouped ``$1234.56`` stays
ungrouped, and the family timeline's ``$60`` keeps dropping zero cents.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.application import family_billing
from backend.v2.contexts.billing.application.first_month_quote_presentation import (
    first_month_quote_formula,
)
from backend.v2.contexts.billing.domain.proration import BillingCalculationSnapshot
from backend.v2.interfaces.admin import billing_routes
from backend.v2.interfaces.parent import payment_routes
from backend.v2.shared.comms.email_theme import format_money


def _snapshot(*, monthly: int, total: int = 4) -> BillingCalculationSnapshot:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return BillingCalculationSnapshot(
        snapshot_id="snap_1",
        monthly_price_cents=monthly,
        billing_period_start=now,
        billing_period_end=now,
        billing_period_label="September 2026",
        timezone="America/Chicago",
        total_eligible_classes=total,
        billable_remaining_classes=3,
        billable_classes_denominator=4,
        proration_ratio="3/4",
        final_amount_cents=monthly * 3 // 4,
        included_occurrence_ids=[],
        excluded_occurrences={},
        calculated_at=now,
        calculated_by="test",
    )


# --------------------------------------------------------------- format_money flags


def test_format_money_default_output_is_unchanged() -> None:
    assert format_money(6000, "usd") == "$60.00"
    assert format_money(123456, "USD") == "$1,234.56"
    assert format_money(-250, "usd") == "-$2.50"
    assert format_money(500, "chf") == "CHF 5.00"


def test_format_money_can_skip_thousands_grouping() -> None:
    assert format_money(123456, "USD", group_thousands=False) == "$1234.56"
    assert format_money(0, "USD", group_thousands=False) == "$0.00"


def test_format_money_can_drop_zero_cents() -> None:
    assert format_money(6000, "USD", drop_zero_cents=True) == "$60"
    assert format_money(6050, "USD", drop_zero_cents=True) == "$60.50"
    assert format_money(120000, "USD", drop_zero_cents=True) == "$1,200"
    assert format_money(-550, "USD", drop_zero_cents=True) == "-$5.50"
    assert format_money(-500, "USD", drop_zero_cents=True) == "-$5"


# --------------------------------------------------------------- BLNO pinning tables


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(0, "$0.00"), (5, "$0.05"), (3750, "$37.50"), (6000, "$60.00"), (123456, "$1234.56")],
)
def test_withdrawal_credit_display_amount_is_byte_identical(cents: int, expected: str) -> None:
    assert billing_routes._format_cents(cents) == expected


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (6000, "$60"),
        (6050, "$60.50"),
        (6005, "$60.05"),
        (0, "$0"),
        (120000, "$1,200"),
        (123456, "$1,234.56"),
        (-550, "-$5.50"),
        (-12000, "-$120"),
    ],
)
def test_family_timeline_money_is_byte_identical(cents: int, expected: str) -> None:
    assert family_billing._money(cents) == expected


def test_first_month_quote_formula_is_byte_identical() -> None:
    assert first_month_quote_formula(_snapshot(monthly=12000)) == "$120.00 x 3 / 4"
    assert first_month_quote_formula(_snapshot(monthly=150000)) == "$1500.00 x 3 / 4"
    assert first_month_quote_formula(_snapshot(monthly=12000, total=0)) == "$0.00"


def test_parent_quote_next_billing_message_is_byte_identical() -> None:
    response = payment_routes._quote_response(_snapshot(monthly=12000))
    assert response.next_billing_message == "Starting next month, tuition is $120.00/month."
    assert response.formula == "$120.00 x 3 / 4"
    big = payment_routes._quote_response(_snapshot(monthly=150000))
    assert big.next_billing_message == "Starting next month, tuition is $1500.00/month."
