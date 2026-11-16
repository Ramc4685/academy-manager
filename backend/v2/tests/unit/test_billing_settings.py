from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from backend.v2.contexts.billing.domain.billing_settings import (
    BillingScheduleChange,
    BillingSettings,
)


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
    # No hardcoded prefix: an academy with no prefix set must never mint a
    # BLNO- number (Settings overhaul Phase 1 PR 2).
    assert settings.invoice_number_prefix is None


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


# --- L8 billing calendar: charge offset and dated schedule change -------------

_JAN_CHANGE = {
    "effective_from": date(2027, 1, 1),
    "invoice_due_days": 4,
    "autopay_charge_offset_days": 0,
    "reminder_days": (7, 0, 3),
}


def test_charge_offset_defaults_to_none_so_no_academy_moves_at_deploy() -> None:
    settings = BillingSettings.default("acad-1")
    assert settings.autopay_charge_offset_days is None
    assert settings.schedule_change is None


def test_charge_offset_may_not_exceed_the_due_window() -> None:
    BillingSettings(academy_id="a", invoice_due_days=4, autopay_charge_offset_days=4)
    with pytest.raises(ValidationError):
        BillingSettings(academy_id="a", invoice_due_days=4, autopay_charge_offset_days=5)
    with pytest.raises(ValidationError):
        BillingScheduleChange(**{**_JAN_CHANGE, "autopay_charge_offset_days": 5})


def test_schedule_change_applies_from_its_day_and_clears_itself() -> None:
    settings = BillingSettings(
        academy_id="a", invoice_due_days=7, reminder_days=(15, 20), schedule_change=_JAN_CHANGE
    )

    dec31 = settings.effective(date(2026, 12, 31))
    assert dec31 is settings
    assert (dec31.invoice_due_days, dec31.autopay_charge_offset_days) == (7, None)

    jan1 = settings.effective(date(2027, 1, 1))
    assert jan1.invoice_due_days == 4
    assert jan1.autopay_charge_offset_days == 0
    assert jan1.reminder_days == (0, 3, 7)
    assert jan1.schedule_change is None
    assert jan1.billing_day == settings.billing_day
