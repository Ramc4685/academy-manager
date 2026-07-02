from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.events import (
    AutopayConsentCaptured,
    AutopayConsentCapturedPayload,
)


def test_autopay_consent_captured_event_schema() -> None:
    captured_at = datetime(2026, 6, 11, 12, 30, tzinfo=UTC)

    event = AutopayConsentCaptured(
        aggregate_id="consent-1",
        academy_id="acad",
        payload=AutopayConsentCapturedPayload(
            consent_id="consent-1",
            parent_id="parent-1",
            method_type="card",
            consent_text_version="autopay-v1",
            ach_mandate_version=None,
            card_disclosure_version="card-v1",
            source="parent_checkout_status",
            actor_id="parent-1",
            captured_at=captured_at,
        ),
    )

    assert event.name == "Billing.AutopayConsentCaptured"
    assert event.schema_version == 1
    assert event.payload.consent_id == "consent-1"
    assert event.payload.card_disclosure_version == "card-v1"
    assert event.payload.ach_mandate_version is None
    assert event.payload.source == "parent_checkout_status"
