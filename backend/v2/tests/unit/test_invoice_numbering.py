"""Unit tests for the invoice-number formatter (Slice D).

Pure function — no Mongo, no counters. The counter/prefix inputs are
supplied by callers (use cases); this only covers the string shape.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.ledger import format_invoice_number


def test_format_invoice_number_default_prefix() -> None:
    assert format_invoice_number(prefix="BLNO", yyyymm="202606", seq=1) == "BLNO-202606-001"


def test_format_invoice_number_pads_to_three_digits() -> None:
    assert format_invoice_number(prefix="BLNO", yyyymm="202606", seq=42) == "BLNO-202606-042"


def test_format_invoice_number_does_not_truncate_beyond_three_digits() -> None:
    """Gap policy allows sequences beyond 999 — the field grows, it never wraps/collides."""
    assert format_invoice_number(prefix="BLNO", yyyymm="202606", seq=1234) == "BLNO-202606-1234"


def test_format_invoice_number_custom_prefix() -> None:
    assert format_invoice_number(prefix="ACAD", yyyymm="202601", seq=7) == "ACAD-202601-007"


@pytest.mark.parametrize("seq", [0, -1])
def test_format_invoice_number_rejects_non_positive_seq(seq: int) -> None:
    with pytest.raises(ValueError, match="seq must be positive"):
        format_invoice_number(prefix="BLNO", yyyymm="202606", seq=seq)


def test_format_invoice_number_rejects_blank_prefix() -> None:
    with pytest.raises(ValueError, match="prefix must not be blank"):
        format_invoice_number(prefix="", yyyymm="202606", seq=1)


def test_format_invoice_number_rejects_malformed_yyyymm() -> None:
    with pytest.raises(ValueError, match="yyyymm must be 6 digits"):
        format_invoice_number(prefix="BLNO", yyyymm="2026-06", seq=1)
