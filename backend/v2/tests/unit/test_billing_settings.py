from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings


def test_default_is_fail_safe_all_discounts_off() -> None:
    settings = BillingSettings.default("acad-1")

    assert settings.academy_id == "acad-1"
    assert settings.ach_discount_enabled is False
    assert settings.ach_discount_percent == 0
    assert settings.ach_discount_label == "ACH autopay discount"
    assert settings.max_ach_discount_percent == 3.0
    assert settings.disclosure_text is None
    assert settings.disclosure_version is None
    assert settings.effective_at is None
    assert settings.invoice_number_prefix == "BLNO"


def test_requires_academy_id() -> None:
    with pytest.raises(ValidationError):
        BillingSettings()  # type: ignore[call-arg]


def test_is_frozen() -> None:
    settings = BillingSettings.default("acad-1")
    with pytest.raises(ValidationError):
        settings.ach_discount_enabled = True  # type: ignore[misc]


def test_can_construct_with_explicit_discount_config() -> None:
    settings = BillingSettings(
        academy_id="acad-1",
        ach_discount_enabled=True,
        ach_discount_percent=2.5,
        ach_discount_label="Autopay savings",
        max_ach_discount_percent=3.0,
        disclosure_text="Discount applies to ACH autopay only.",
        disclosure_version="v1",
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
        invoice_number_prefix="INV",
    )

    assert settings.ach_discount_enabled is True
    assert settings.ach_discount_percent == 2.5
    assert settings.disclosure_version == "v1"
    assert settings.invoice_number_prefix == "INV"
