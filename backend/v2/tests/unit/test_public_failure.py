"""Stored email failure strings become safe public codes (L11)."""

from __future__ import annotations

from backend.v2.shared.comms.public_failure import SUPPRESSION_REFUSAL, public_failure


def test_unsubscribe_is_named_and_suppression_detail_is_hidden() -> None:
    assert public_failure("unsubscribed:campaigns", "x") == "recipient_unsubscribed"
    assert public_failure("suppressed:complaint", "email_delivery_failed") == (
        "email_delivery_failed"
    )
    assert public_failure("Resend 422: bad address", "fallback") == "fallback"
    assert public_failure("send_gave_up", "fallback") == "send_gave_up"
    assert SUPPRESSION_REFUSAL.match("suppressed:hard_bounce")
    assert not SUPPRESSION_REFUSAL.match("unsubscribed:campaigns")
