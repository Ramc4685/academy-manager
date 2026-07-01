from __future__ import annotations

import pytest

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.fees import compute_ach_discount


def _settings(
    *,
    enabled: bool = True,
    percent: float = 2.5,
    max_percent: float = 3.0,
) -> BillingSettings:
    return BillingSettings(
        academy_id="acad-1",
        ach_discount_enabled=enabled,
        ach_discount_percent=percent,
        max_ach_discount_percent=max_percent,
    )


@pytest.mark.parametrize("funding_type", ["us_bank_account", "ach"])
def test_compute_ach_discount_applies_only_to_ach_funding(funding_type: str) -> None:
    assert compute_ach_discount(10_000, _settings(percent=2.5), funding_type) == 250


@pytest.mark.parametrize("funding_type", ["card", "debit", "unknown", "", None])
def test_compute_ach_discount_returns_zero_for_non_ach_or_missing_funding(
    funding_type: str | None,
) -> None:
    assert compute_ach_discount(10_000, _settings(percent=2.5), funding_type) == 0


def test_compute_ach_discount_returns_zero_when_disabled() -> None:
    assert compute_ach_discount(10_000, _settings(enabled=False, percent=2.5), "ach") == 0


@pytest.mark.parametrize("subtotal_cents", [0, -1])
def test_compute_ach_discount_returns_zero_for_non_positive_subtotal(
    subtotal_cents: int,
) -> None:
    assert compute_ach_discount(subtotal_cents, _settings(percent=2.5), "ach") == 0


def test_compute_ach_discount_caps_percent_at_configured_max() -> None:
    assert (
        compute_ach_discount(
            10_000,
            _settings(percent=5.0, max_percent=3.0),
            "us_bank_account",
        )
        == 300
    )


def test_compute_ach_discount_rounds_half_up_to_whole_cents() -> None:
    # 999 * 2.5% = 24.975 cents; cash discount rounds to the nearest cent.
    assert compute_ach_discount(999, _settings(percent=2.5), "ach") == 25
