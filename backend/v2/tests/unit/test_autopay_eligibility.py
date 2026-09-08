from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.autopay_eligibility import (
    AUTOPAY_ACTIVE_STATUS,
    CHARGEABLE_INVOICE_STATUSES,
    autopay_eligibility,
    invoice_is_chargeable,
    ladder_eligibility,
)


def _eligible(**overrides):
    kwargs = dict(
        invoice_status="open",
        balance_due_cents=7000,
        enrollment_id="enr-1",
        autopay_enrollment_status=AUTOPAY_ACTIVE_STATUS,
        has_payment_method=True,
        connected_account_ready=True,
    )
    kwargs.update(overrides)
    return autopay_eligibility(**kwargs)


def test_constants_match_worker_vocabulary() -> None:
    assert CHARGEABLE_INVOICE_STATUSES == frozenset({"open", "partially_paid"})
    assert AUTOPAY_ACTIVE_STATUS == "active"


@pytest.mark.parametrize(
    ("status", "balance", "expected"),
    [
        ("open", 1, True),
        ("partially_paid", 1, True),
        ("paid", 1, False),
        ("void", 1, False),
        ("draft", 1, False),
        ("open", 0, False),
        (None, 1, False),
    ],
)
def test_invoice_is_chargeable(status, balance, expected) -> None:
    assert invoice_is_chargeable(status, balance) is expected


def test_fully_eligible() -> None:
    result = _eligible()
    assert result.status == "eligible" and result.eligible and result.reason is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"invoice_status": "void"}, "invoice_not_chargeable"),
        ({"invoice_status": "draft"}, "invoice_not_chargeable"),
        ({"balance_due_cents": 0}, "no_balance"),
        ({"enrollment_id": None}, "no_enrollment"),
        ({"enrollment_id": ""}, "no_enrollment"),
        ({"autopay_enrollment_status": "paused"}, "autopay_not_active"),
        ({"autopay_enrollment_status": None}, "autopay_not_active"),
        ({"has_payment_method": False}, "no_card_on_file"),
        ({"connected_account_ready": False}, "connected_account_not_ready"),
    ],
)
def test_ineligible_reasons_in_order(overrides, reason) -> None:
    result = _eligible(**overrides)
    assert result.status == "ineligible"
    assert result.reason == reason
    assert not result.eligible


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"has_payment_method": None}, "card_state_unknown"),
        ({"connected_account_ready": None}, "connected_account_unknown"),
    ],
)
def test_unknown_card_or_account_is_unknown_not_eligible(overrides, reason) -> None:
    result = _eligible(**overrides)
    assert result.status == "unknown"
    assert result.reason == reason
    assert not result.eligible


def test_invoice_problems_win_over_unknown_card_state() -> None:
    result = _eligible(invoice_status="paid", has_payment_method=None)
    assert result.status == "ineligible" and result.reason == "invoice_not_chargeable"


def test_ladder_eligibility_is_the_prepare_predicate() -> None:
    ok = ladder_eligibility(
        invoice_status="open",
        balance_due_cents=1,
        enrollment_id="e",
        autopay_enrollment_status="active",
    )
    assert ok.eligible
    assert not ladder_eligibility(
        invoice_status="open",
        balance_due_cents=1,
        enrollment_id="e",
        autopay_enrollment_status="offered",
    ).eligible
    assert (
        ladder_eligibility(
            invoice_status="open",
            balance_due_cents=1,
            enrollment_id=None,
            autopay_enrollment_status="active",
        ).reason
        == "no_enrollment"
    )
