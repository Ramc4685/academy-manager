"""Unit tests for Phase 4 backfill mapping logic.

Tests are pure (no MongoDB I/O) — they exercise map_legacy_payment and
is_legacy_payment directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from backend.scripts.backfill_p4_legacy_payments import (
    _legacy_balance_for_parent,
    _status_keys_from_counts,
    is_legacy_payment,
    map_legacy_payment,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NOW = datetime(2026, 4, 15, 10, 0, 0, tzinfo=UTC)


def _base_doc(**overrides: object) -> dict:
    doc: dict = {
        "payment_id": "pay-001",
        "academy_id": "blno",
        "parent_id": "parent-abc",
        "student_id": "stu-xyz",
        "enrollment_id": "enr-111",
        "period": "2026-04",
        "amount_cents": 7000,
        "paid_amount_cents": None,
        "balance_due_cents": None,
        "discount_cents": None,
        "status": "succeeded",
        "currency": "usd",
        "stripe_payment_intent_id": "pi_test_123",
        "payment_method": "Zelle",
        "paid_at": NOW,
        "created_at": NOW,
        "updated_at": NOW,
        "is_deleted": False,
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# is_legacy_payment
# ---------------------------------------------------------------------------


def test_legacy_payment_identified_when_no_ledger_fields() -> None:
    doc = _base_doc()
    assert is_legacy_payment(doc) is True


def test_ledger_payment_excluded_by_unapplied_amount_cents() -> None:
    doc = _base_doc(unapplied_amount_cents=0)
    assert is_legacy_payment(doc) is False


def test_ledger_payment_excluded_by_ledger_idempotency_key() -> None:
    doc = _base_doc(ledger_idempotency_key="some-key")
    assert is_legacy_payment(doc) is False


# ---------------------------------------------------------------------------
# Status: succeeded
# ---------------------------------------------------------------------------


def test_succeeded_produces_invoice_paid_with_zero_balance() -> None:
    doc = _base_doc(status="succeeded", amount_cents=7000, paid_amount_cents=7000)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["invoice_id"] == "inv-from-pay-001"
    assert inv["status"] == "paid"
    assert inv["balance_due_cents"] == 0
    assert inv["subtotal_cents"] == 7000
    assert inv["total_cents"] == 7000
    assert inv["discount_cents"] == 0
    assert inv["due_date"] == datetime(2026, 4, 15, 0, 0, tzinfo=UTC)


def test_succeeded_creates_ledger_payment() -> None:
    doc = _base_doc(status="succeeded", amount_cents=7000, paid_amount_cents=7000)
    result = map_legacy_payment(doc)

    assert result is not None
    lp = result["ledger_payment"]
    assert lp is not None
    assert lp["payment_id"] == "lp-from-pay-001"
    assert lp["amount_cents"] == 7000
    assert lp["unapplied_amount_cents"] == 0
    assert lp["status"] == "succeeded"


def test_succeeded_creates_allocation() -> None:
    doc = _base_doc(status="succeeded", amount_cents=7000, paid_amount_cents=7000)
    result = map_legacy_payment(doc)

    assert result is not None
    alloc = result["allocation"]
    assert alloc is not None
    assert alloc["allocation_id"] == "alloc-from-pay-001"
    assert alloc["invoice_id"] == "inv-from-pay-001"
    assert alloc["payment_id"] == "lp-from-pay-001"
    assert alloc["amount_cents"] == 7000


def test_succeeded_falls_back_to_amount_cents_when_paid_amount_missing() -> None:
    doc = _base_doc(status="succeeded", amount_cents=6000, paid_amount_cents=None)
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["ledger_payment"] is not None
    assert result["ledger_payment"]["amount_cents"] == 6000


def test_succeeded_with_zero_paid_amount_treats_status_as_paid() -> None:
    doc = _base_doc(status="succeeded", amount_cents=6000, paid_amount_cents=0)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    lp = result["ledger_payment"]
    assert inv["status"] == "paid"
    assert inv["balance_due_cents"] == 0
    assert lp is not None
    assert lp["amount_cents"] == 6000
    assert lp["unapplied_amount_cents"] == 0


@pytest.mark.parametrize("status", ["succeeded", "paid"])
def test_paid_status_with_string_zero_amount_falls_back_to_total(status: str) -> None:
    doc = _base_doc(status=status, amount_cents=6000, paid_amount_cents="0")
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["status"] == "paid"
    assert result["invoice"]["balance_due_cents"] == 0
    assert result["ledger_payment"] is not None
    assert result["ledger_payment"]["amount_cents"] == 6000


@pytest.mark.parametrize("status", ["succeeded", "paid"])
def test_paid_status_with_empty_string_paid_amount_falls_back_to_total(status: str) -> None:
    doc = _base_doc(status=status, amount_cents=6000, paid_amount_cents="")
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["status"] == "paid"
    assert result["invoice"]["balance_due_cents"] == 0
    assert result["ledger_payment"] is not None
    assert result["ledger_payment"]["amount_cents"] == 6000


def test_overpayment_creates_unapplied_amount_and_capped_allocation() -> None:
    doc = _base_doc(
        status="succeeded",
        amount_cents=10000,
        amount_received_cents=12500,
        paid_amount_cents=None,
    )
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    lp = result["ledger_payment"]
    alloc = result["allocation"]

    assert inv["status"] == "paid"
    assert inv["balance_due_cents"] == 0
    assert lp is not None
    assert alloc is not None
    assert lp["amount_cents"] == 12500
    assert lp["unapplied_amount_cents"] == 2500
    assert alloc["amount_cents"] == 10000


def test_succeeded_payment_method_falls_back_to_unknown() -> None:
    doc = _base_doc(status="succeeded", payment_method=None)
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["ledger_payment"] is not None
    assert result["ledger_payment"]["payment_method"] == "unknown"


# ---------------------------------------------------------------------------
# Status: pending
# ---------------------------------------------------------------------------


def test_pending_produces_open_invoice_with_full_balance() -> None:
    doc = _base_doc(status="pending", amount_cents=6000)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["status"] == "open"
    assert inv["balance_due_cents"] == 6000


def test_pending_does_not_create_ledger_payment_or_allocation() -> None:
    doc = _base_doc(status="pending")
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["ledger_payment"] is None
    assert result["allocation"] is None


# ---------------------------------------------------------------------------
# Mapping-specific regression tests
# ---------------------------------------------------------------------------


def test_mapping_preserves_legacy_invoice_number() -> None:
    doc = _base_doc(
        status="pending",
        payment_id="pay_28505f6db2b4a5b11917",
        invoice_number="BLNO-202605-b11917",
    )
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["invoice_id"] == "inv-from-pay_28505f6db2b4a5b11917"
    assert result["invoice"]["invoice_number"] == "BLNO-202605-b11917"


# ---------------------------------------------------------------------------
# Status: failed
# ---------------------------------------------------------------------------


def test_failed_produces_open_invoice_without_payment() -> None:
    doc = _base_doc(status="failed", amount_cents=6000)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["status"] == "open"
    assert inv["balance_due_cents"] == 6000
    assert result["ledger_payment"] is None
    assert result["allocation"] is None


def test_failed_counts_as_open_legacy_balance() -> None:
    assert (
        _legacy_balance_for_parent(
            [
                _base_doc(status="failed", amount_cents=6000),
                _base_doc(status="succeeded", amount_cents=7000),
            ]
        )
        == 6000
    )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_invalid_amount_cents_raises_value_error() -> None:
    doc = _base_doc(status="succeeded", amount_cents="not-a-number")

    with pytest.raises(ValueError, match="Invalid cents value"):
        map_legacy_payment(doc)


@pytest.mark.parametrize(
    "bad_value",
    [
        True,
        False,
        12.5,
        "12.34",
        Decimal("12.5"),
    ],
)
def test_bool_or_fractional_numeric_amount_cents_raises_value_error(bad_value: object) -> None:
    doc = _base_doc(status="succeeded", amount_cents=bad_value)

    with pytest.raises(ValueError, match="Invalid cents value"):
        map_legacy_payment(doc)


# ---------------------------------------------------------------------------
# Status: waived
# ---------------------------------------------------------------------------


def test_waived_produces_void_invoice_with_zero_balance() -> None:
    doc = _base_doc(status="waived", amount_cents=6000)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["status"] == "void"
    assert inv["balance_due_cents"] == 0


def test_waived_does_not_create_ledger_payment_or_allocation() -> None:
    doc = _base_doc(status="waived")
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["ledger_payment"] is None
    assert result["allocation"] is None


# ---------------------------------------------------------------------------
# Unknown status: skip
# ---------------------------------------------------------------------------


def test_unknown_status_returns_none() -> None:
    doc = _base_doc(status="refunded")
    result = map_legacy_payment(doc)
    assert result is None


def test_empty_status_returns_none() -> None:
    doc = _base_doc(status="")
    result = map_legacy_payment(doc)
    assert result is None


# ---------------------------------------------------------------------------
# Deleted docs
# ---------------------------------------------------------------------------


def test_deleted_doc_should_be_skipped_by_caller_not_mapper() -> None:
    """map_legacy_payment itself does not check is_deleted; the caller does.

    This test verifies the contract: mapping an is_deleted doc still
    returns a mapped result; the caller is responsible for skipping it.
    The backfill loop checks is_deleted before calling map_legacy_payment.
    """
    doc = _base_doc(status="succeeded", is_deleted=True)
    result = map_legacy_payment(doc)
    assert result is not None  # mapper is unaware of deletion


# ---------------------------------------------------------------------------
# Missing student_id
# ---------------------------------------------------------------------------


def test_missing_student_id_does_not_crash() -> None:
    doc = _base_doc(status="succeeded", student_id=None)
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["student_id"] is None


# ---------------------------------------------------------------------------
# parent_id fallback to parent_user_id
# ---------------------------------------------------------------------------


def test_parent_user_id_used_when_parent_id_absent() -> None:
    doc = _base_doc(status="pending")
    del doc["parent_id"]
    doc["parent_user_id"] = "parent-from-user-id"
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["parent_id"] == "parent-from-user-id"


# ---------------------------------------------------------------------------
# Period fallback
# ---------------------------------------------------------------------------


def test_period_falls_back_to_created_at_month() -> None:
    doc = _base_doc(status="pending")
    doc.pop("period", None)
    doc["period"] = None
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["period"] == "2026-04"


# ---------------------------------------------------------------------------
# Discount
# ---------------------------------------------------------------------------


def test_pending_discount_uses_final_amount_as_balance() -> None:
    doc = _base_doc(status="pending", amount_cents=7000, discount_cents=1000)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["subtotal_cents"] == 7000
    assert inv["discount_cents"] == 1000
    assert inv["total_cents"] == 6000
    assert inv["balance_due_cents"] == 6000


def test_partially_paid_creates_partial_invoice_payment_and_allocation() -> None:
    doc = _base_doc(
        status="partially_paid",
        amount_cents=10000,
        paid_amount_cents=None,
        amount_received_cents=4000,
        payment_method="cash",
    )
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["status"] == "partially_paid"
    assert inv["total_cents"] == 10000
    assert inv["balance_due_cents"] == 6000
    assert result["ledger_payment"] is not None
    assert result["ledger_payment"]["payment_id"] == "lp-from-pay-001"
    assert result["ledger_payment"]["amount_cents"] == 4000
    assert result["ledger_payment"]["payment_method"] == "cash"
    assert result["allocation"] is not None
    assert result["allocation"]["amount_cents"] == 4000


def test_partial_status_alias_maps_to_partially_paid() -> None:
    doc = _base_doc(status="partial", amount_cents=10000, amount_received_cents=2500)
    result = map_legacy_payment(doc)

    assert result is not None
    assert result["invoice"]["status"] == "partially_paid"
    assert result["invoice"]["balance_due_cents"] == 7500


def test_legacy_balance_uses_final_amount_minus_received_money() -> None:
    docs = [
        _base_doc(status="pending", amount_cents=7000, discount_cents=1000),
        _base_doc(status="partially_paid", amount_cents=10000, amount_received_cents=4000),
        _base_doc(status="succeeded", amount_cents=8000),
        _base_doc(status="waived", amount_cents=5000),
    ]

    assert _legacy_balance_for_parent(docs) == 12000


def test_legacy_balance_ignores_invalid_paid_and_void_amounts() -> None:
    docs = [
        _base_doc(status="succeeded", amount_cents="not-a-number"),
        _base_doc(status="paid", amount_cents=True),
        _base_doc(status="waived", amount_cents="12.5"),
        _base_doc(status="pending", amount_cents=7000, discount_cents=1000),
    ]

    assert _legacy_balance_for_parent(docs) == 6000


def test_final_amount_cents_controls_subtotal_total_and_line_amounts() -> None:
    doc = _base_doc(
        status="succeeded",
        amount_cents=20000,
        discount_cents=2500,
        final_amount_cents=8000,
    )
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    line = result["line"]

    assert inv["subtotal_cents"] == 8000
    assert inv["discount_cents"] == 0
    assert inv["total_cents"] == 8000
    assert line["unit_amount_cents"] == 8000
    assert line["amount_cents"] == 8000


def test_status_counts_are_sorted() -> None:
    counts: dict[str, int] = {
        "status_pending": 2,
        "status_succeeded": 1,
        "status_waived": 3,
        "status_failed": 4,
        "total": 10,
    }
    assert _status_keys_from_counts(counts) == ["failed", "pending", "succeeded", "waived"]


# ---------------------------------------------------------------------------
# Invoice line
# ---------------------------------------------------------------------------


def test_invoice_line_has_correct_ids_and_type() -> None:
    doc = _base_doc(status="succeeded")
    result = map_legacy_payment(doc)

    assert result is not None
    line = result["line"]
    assert line["line_id"] == "line-from-pay-001"
    assert line["invoice_id"] == "inv-from-pay-001"
    assert line["line_type"] == "tuition"
    assert line["source_type"] == "legacy_payment"
    assert line["source_id"] == "pay-001"


# ---------------------------------------------------------------------------
# Idempotency: calling map_legacy_payment twice on the same doc
# ---------------------------------------------------------------------------


def test_mapping_is_deterministic_across_calls() -> None:
    doc = _base_doc(status="succeeded")
    result_a = map_legacy_payment(doc)
    result_b = map_legacy_payment(doc)

    assert result_a is not None
    assert result_b is not None
    assert result_a["invoice"]["invoice_id"] == result_b["invoice"]["invoice_id"]
    assert result_a["line"]["line_id"] == result_b["line"]["line_id"]
    assert result_a["ledger_payment"]["payment_id"] == result_b["ledger_payment"]["payment_id"]  # type: ignore[index]
    assert result_a["allocation"]["allocation_id"] == result_b["allocation"]["allocation_id"]  # type: ignore[index]
