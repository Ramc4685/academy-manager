"""Unit tests for the invoice-number formatter (Slice D, reshaped for #659).

Pure function — no Mongo, no counters. The counter/prefix inputs are
supplied by callers (use cases); this only covers the string shape.

Owner decision 2026-09-12 (#659): the parent-facing number is
``ACADEMYCODE-YYYY-MM-NNNN`` so the tuition month reads at a glance.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.ledger import (
    format_invoice_number,
    format_tuition_month,
)


def test_format_invoice_number_default_prefix() -> None:
    assert format_invoice_number(prefix="BLNO", yyyymm="202606", seq=1) == "BLNO-2026-06-0001"


def test_format_invoice_number_pads_to_four_digits() -> None:
    assert format_invoice_number(prefix="BLNO", yyyymm="202609", seq=42) == "BLNO-2026-09-0042"


def test_format_invoice_number_does_not_truncate_beyond_four_digits() -> None:
    """Gap policy allows sequences beyond 9999 — the field grows, it never wraps/collides."""
    assert format_invoice_number(prefix="BLNO", yyyymm="202606", seq=12345) == "BLNO-2026-06-12345"


def test_format_invoice_number_custom_prefix() -> None:
    assert format_invoice_number(prefix="ACAD", yyyymm="202601", seq=7) == "ACAD-2026-01-0007"


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


def test_format_tuition_month_renders_words() -> None:
    assert format_tuition_month("2026-09") == "September 2026"


def test_format_tuition_month_degrades_to_raw_period_when_unparseable() -> None:
    """A malformed period must never crash a parent email mid-send."""
    assert format_tuition_month("not-a-period") == "not-a-period"
