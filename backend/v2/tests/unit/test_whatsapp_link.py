from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from backend.v2.shared.comms.whatsapp import (
    dues_reminder_text,
    normalize_wa_number,
    whatsapp_deep_link,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Bare national numbers pick up the default country code.
        ("5550100100", "15550100100"),
        ("(555) 010-0100", "15550100100"),
        ("555-010-0100", "15550100100"),
        ("555.010.0100 ", "15550100100"),
        # Already carries the default country code.
        ("15550100100", "15550100100"),
        ("1 (555) 010-0100", "15550100100"),
        # Explicit international beats the default country code.
        ("+91 98765 43210", "919876543210"),
        ("+44 20 7946 0100", "442079460100"),
        ("0091 98765 43210", "919876543210"),
        # National trunk prefix is dropped before applying the default.
        ("05550100100", "15550100100"),
    ],
)
def test_normalize_wa_number_resolves_international_digits(raw: str, expected: str) -> None:
    assert normalize_wa_number(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "n/a",
        "555-0100",  # too short to dial
        "+12345",  # explicit international but implausibly short
        "5550100100123456",  # length we cannot attribute without guessing
    ],
)
def test_normalize_wa_number_refuses_to_guess(raw: str | None) -> None:
    # Guessing a country code here would open a chat with a stranger, so the
    # caller must render no link at all.
    assert normalize_wa_number(raw) is None


def test_normalize_wa_number_honours_non_us_default() -> None:
    assert normalize_wa_number("9876543210", default_country_code="91") == "919876543210"


def test_dues_reminder_text_carries_amount_count_and_pay_url() -> None:
    text = dues_reminder_text(
        display_name="Sample Parent",
        total_due_cents=16000,
        pending_count=2,
        currency="usd",
        pay_url="https://blno-academy.courtmastr.com/parent/payments",
        academy_name="BLNO Academy",
    )

    assert "Hi Sample Parent," in text
    assert "USD 160.00" in text
    assert "2 open invoices" in text
    assert "BLNO Academy" in text
    assert "https://blno-academy.courtmastr.com/parent/payments" in text


def test_dues_reminder_text_singular_invoice_and_missing_name() -> None:
    text = dues_reminder_text(
        display_name=None,
        total_due_cents=5000,
        pending_count=1,
        currency="usd",
        pay_url=None,
    )

    assert "Hi there," in text
    assert "1 open invoice " in text
    assert "USD 50.00" in text


def test_dues_reminder_text_falls_back_to_portal_wording_without_pay_url() -> None:
    # Mirrors the email adapter, which drops the "Pay now" button and tells the
    # parent to log in when no frontend URL is configured.
    text = dues_reminder_text(
        display_name="Sample Parent",
        total_due_cents=16000,
        pending_count=2,
        currency="usd",
        pay_url=None,
    )

    assert "Please log in to the parent portal to pay." in text
    assert "http" not in text


def test_whatsapp_deep_link_encodes_message_into_wa_me_url() -> None:
    message = dues_reminder_text(
        display_name="Sample Parent",
        total_due_cents=16000,
        pending_count=2,
        currency="usd",
        pay_url="https://blno-academy.courtmastr.com/parent/payments",
    )

    link = whatsapp_deep_link(phone="(555) 010-0100", message=message)

    assert link is not None
    parts = urlsplit(link)
    assert parts.scheme == "https"
    assert parts.netloc == "wa.me"
    assert parts.path == "/15550100100"
    # The whole message must survive the round trip, newlines and URL included.
    assert parse_qs(parts.query)["text"] == [message]
    # Raw spaces/newlines would break the link.
    assert " " not in link
    assert "\n" not in link


def test_whatsapp_deep_link_is_none_when_phone_unusable() -> None:
    assert whatsapp_deep_link(phone=None, message="hi") is None
    assert whatsapp_deep_link(phone="", message="hi") is None
    assert whatsapp_deep_link(phone="555-0100", message="hi") is None
