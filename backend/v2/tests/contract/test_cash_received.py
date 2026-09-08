"""``cash_received_in_period`` — the one definition of cash received (spec §3.2).

The reader was extracted verbatim from the reports dashboard, so the tests
that matter most are the ones proving it did not drift: the last two assert
that ``payment_collected_cents`` still describes every legacy row, and that
the dashboard's ``cash_collected_cents`` over a seeded month equals the
reader's ``net_cents``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.billing.application.admin_money import (
    month_bounds,
    payment_collected_cents,
)
from backend.v2.contexts.billing.infrastructure.admin_reports_read_model import (
    make_reports_dashboard,
)
from backend.v2.contexts.billing.infrastructure.cash_received import (
    cash_received_in_period,
)

PERIOD = "2026-09"
ACADEMY = "test-academy"
START, END = month_bounds(PERIOD)


async def _ledger(db: Any, **doc: Any) -> None:
    await db["ledger_payments"].insert_one(
        {
            "academy_id": ACADEMY,
            "status": "succeeded",
            "paid_at": datetime(2026, 9, 12, tzinfo=UTC),
            **doc,
        }
    )


async def _legacy(db: Any, **doc: Any) -> None:
    await db["payments"].insert_one(
        {
            "academy_id": ACADEMY,
            "status": "succeeded",
            "paid_at": datetime(2026, 9, 12, tzinfo=UTC),
            **doc,
        }
    )


async def _read(db: Any, academy_id: str = ACADEMY):
    return await cash_received_in_period(db, academy_id=academy_id, start=START, end=END)


@pytest.mark.asyncio
async def test_gross_net_and_refund_split(db: Any) -> None:
    await _ledger(db, payment_id="pay-1", paid_amount_cents=10_000)
    await _ledger(db, payment_id="pay-2", paid_amount_cents=5_000, refunded_cents=2_000)

    result = await _read(db)

    assert result.gross_cents == 15_000
    assert result.refunded_cents == 2_000
    assert result.net_cents == 13_000
    assert {row.payment_id for row in result.rows} == {"pay-1", "pay-2"}
    assert {row.source for row in result.rows} == {"ledger"}


@pytest.mark.asyncio
async def test_a_fully_refunded_payment_nets_to_zero_not_negative(db: Any) -> None:
    """Flooring is per payment, so an over-refund cannot eat other revenue."""
    await _ledger(db, payment_id="pay-1", paid_amount_cents=10_000)
    await _ledger(db, payment_id="pay-2", paid_amount_cents=4_000, refunded_cents=9_000)

    result = await _read(db)

    assert result.net_cents == 10_000
    by_id = {row.payment_id: row for row in result.rows}
    assert by_id["pay-2"].net_cents == 0


@pytest.mark.asyncio
async def test_paid_at_missing_falls_back_to_created_at(db: Any) -> None:
    await _ledger(
        db,
        payment_id="pay-1",
        paid_at=None,
        created_at=datetime(2026, 9, 3, tzinfo=UTC),
        paid_amount_cents=7_000,
    )
    # created_at in the next month, no paid_at → not this period.
    await _ledger(
        db,
        payment_id="pay-2",
        paid_at=None,
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        paid_amount_cents=9_000,
    )

    result = await _read(db)

    assert result.net_cents == 7_000
    assert [row.payment_id for row in result.rows] == ["pay-1"]
    assert result.rows[0].at == datetime(2026, 9, 3, tzinfo=UTC)


@pytest.mark.asyncio
async def test_method_comes_from_the_payment_row(db: Any) -> None:
    await _ledger(db, payment_id="pay-1", paid_amount_cents=1_000, payment_method="card")

    result = await _read(db)

    assert result.rows[0].method == "card"


@pytest.mark.asyncio
async def test_a_legacy_row_is_counted_when_nothing_supersedes_it(db: Any) -> None:
    await _legacy(db, payment_id="leg-1", paid_amount_cents=3_000)

    result = await _read(db)

    assert result.net_cents == 3_000
    assert result.rows[0].source == "legacy"


@pytest.mark.asyncio
async def test_a_legacy_row_sharing_a_provider_key_with_a_ledger_row_is_deduped(
    db: Any,
) -> None:
    await _ledger(db, payment_id="pay-1", stripe_payment_intent_id="pi_1", paid_amount_cents=8_000)
    await _legacy(db, payment_id="leg-1", stripe_payment_intent_id="pi_1", paid_amount_cents=8_000)

    result = await _read(db)

    assert result.net_cents == 8_000
    assert [row.source for row in result.rows] == ["ledger"]


@pytest.mark.asyncio
async def test_dedup_spans_ledger_payments_from_other_months(db: Any) -> None:
    """The all-time key pass: a legacy row can mirror last month's ledger row."""
    await _ledger(
        db,
        payment_id="pay-old",
        stripe_payment_intent_id="pi_old",
        paid_at=datetime(2026, 8, 12, tzinfo=UTC),
        paid_amount_cents=6_000,
    )
    await _legacy(
        db, payment_id="leg-1", stripe_payment_intent_id="pi_old", paid_amount_cents=6_000
    )

    result = await _read(db)

    assert result.net_cents == 0
    assert result.rows == ()


@pytest.mark.asyncio
async def test_a_legacy_row_keyed_by_this_period_invoice_is_deduped(db: Any) -> None:
    await db["invoices"].insert_one(
        {"academy_id": ACADEMY, "invoice_id": "inv-1", "period": PERIOD, "status": "paid"}
    )
    await _legacy(db, payment_id="leg-1", invoice_id="inv-1", paid_amount_cents=4_000)

    result = await _read(db)

    assert result.net_cents == 0


@pytest.mark.asyncio
async def test_a_legacy_row_keyed_by_an_allocated_invoice_is_deduped(db: Any) -> None:
    await _ledger(db, payment_id="pay-1", paid_amount_cents=5_000)
    await db["payment_allocations"].insert_one(
        {"academy_id": ACADEMY, "payment_id": "pay-1", "invoice_id": "inv-9"}
    )
    await _legacy(db, payment_id="leg-1", invoice_id="inv-9", paid_amount_cents=5_000)

    result = await _read(db)

    assert result.net_cents == 5_000


@pytest.mark.asyncio
async def test_another_academys_money_is_never_counted(db: Any) -> None:
    await _ledger(db, payment_id="pay-1", paid_amount_cents=1_000)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "other-academy",
            "payment_id": "pay-other",
            "status": "succeeded",
            "paid_at": datetime(2026, 9, 12, tzinfo=UTC),
            "paid_amount_cents": 99_000,
        }
    )

    result = await _read(db)

    assert result.net_cents == 1_000


@pytest.mark.asyncio
async def test_an_empty_month_is_all_zeros(db: Any) -> None:
    result = await _read(db)

    assert (result.gross_cents, result.refunded_cents, result.net_cents, result.rows) == (
        0,
        0,
        0,
        (),
    )


@pytest.mark.parametrize(
    "payment",
    [
        {"status": "succeeded", "paid_amount_cents": 10_000},
        {"status": "paid", "amount_cents": 10_000, "discount_cents": 1_000},
        {"status": "refunded", "paid_amount_cents": 10_000, "refunded_cents": 10_000},
        {"status": "partially_refunded", "paid_amount_cents": 10_000, "refunded_cents": 3_000},
        {"status": "partially_paid", "paid_amount_cents": 2_500, "amount_cents": 10_000},
        {"status": "pending", "amount_cents": 10_000},
        {"status": "failed", "paid_amount_cents": 0, "amount_cents": 10_000},
        {"status": "waived", "amount_cents": 10_000},
        {"status": "", "amount_cents": 10_000},
    ],
)
def test_legacy_row_netting_still_equals_payment_collected_cents(
    payment: dict[str, Any],
) -> None:
    """The extraction's contract: rows carry gross/refunded, but their netting
    must stay bit-identical to the figure the dashboard used to add."""
    from backend.v2.contexts.billing.infrastructure.cash_received import _legacy_amounts

    gross, refunded = _legacy_amounts(payment)

    assert max(gross - refunded, 0) == payment_collected_cents(payment)


@pytest.mark.asyncio
async def test_the_dashboard_reports_exactly_what_the_reader_returns(db: Any, acad: str) -> None:
    """Spec §3.2: the dashboard's ``cash_collected_cents`` is unchanged by the
    extraction. Seeds one month of mixed ledger, legacy and deduped rows."""
    await db["invoices"].insert_one(
        {
            "academy_id": ACADEMY,
            "invoice_id": "inv-1",
            "period": PERIOD,
            "status": "paid",
            "amount_cents": 10_000,
            "paid_amount_cents": 10_000,
            "balance_due_cents": 0,
            "parent_id": "par-1",
            "due_date": "2026-09-05",
        }
    )
    await _ledger(db, payment_id="pay-1", invoice_id="inv-1", paid_amount_cents=10_000)
    await _ledger(db, payment_id="pay-2", paid_amount_cents=5_000, refunded_cents=1_500)
    # Deduped against inv-1 above.
    await _legacy(db, payment_id="leg-dup", invoice_id="inv-1", paid_amount_cents=10_000)
    # Genuine legacy cash.
    await _legacy(db, payment_id="leg-1", paid_amount_cents=2_000, period=PERIOD)

    reader = await _read(db)
    dashboard = await make_reports_dashboard(db)(PERIOD)  # type: ignore[operator]

    assert reader.net_cents == 15_500
    assert dashboard["cash_collected_cents"] == reader.net_cents
    assert dashboard["profit_and_loss"]["revenue_cents"] == reader.net_cents
