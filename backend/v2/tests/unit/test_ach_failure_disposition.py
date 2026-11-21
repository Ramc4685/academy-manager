"""Which bank-debit failures retry (L1 A4-2, owner decision 2026-11-15)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.ach_returns import ach_failure_disposition


@pytest.mark.parametrize("code", ["insufficient_funds", "R01", "r09"])
def test_insufficient_funds_retries(code: str) -> None:
    assert ach_failure_disposition(code) == "retry"


@pytest.mark.parametrize(
    "code",
    [
        "bank_account_closed",
        "account_closed",
        "debit_not_authorized",
        "R02",
        "R10",
        "R29",
        "bank_account_unusable",
        "bank_account_frozen",
        "bank_account_invalid_details",
    ],
)
def test_closed_or_unauthorized_never_retries(code: str) -> None:
    assert ach_failure_disposition(code) == "stop"


@pytest.mark.parametrize("code", ["card_declined", "expired_card", "do_not_honor", "", None])
def test_card_codes_are_not_bank_failures(code: object) -> None:
    assert ach_failure_disposition(code) is None
