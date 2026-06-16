"""Unit tests for Phase 4 backfill mapping logic.

Tests are pure (no MongoDB I/O) — they exercise map_legacy_payment and
is_legacy_payment directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.scripts.backfill_p4_legacy_payments import (
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


def test_discount_reduces_total_not_balance_for_pending() -> None:
    doc = _base_doc(status="pending", amount_cents=7000, discount_cents=500)
    result = map_legacy_payment(doc)

    assert result is not None
    inv = result["invoice"]
    assert inv["subtotal_cents"] == 7000
    assert inv["discount_cents"] == 500
    assert inv["total_cents"] == 6500
    assert inv["balance_due_cents"] == 7000  # balance_due comes from amount_cents for pending


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
