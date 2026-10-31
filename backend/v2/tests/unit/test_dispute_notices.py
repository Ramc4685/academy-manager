"""The dispute notice: delivered to the academy owner inside the event's
tenant scope, exactly the facts recorded, every value escaped; skipped (not
failed) when e-mail delivery is not configured."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import mongomock_motor
import pytest

from backend.v2.composition.dispute_notices import (
    DisputeNoticeEmailAdapter,
    build_dispute_notifier,
    render_dispute_notice,
)
from backend.v2.composition.event_handlers import (
    install_dispute_notifier,
    on_payment_dispute_notice_requested,
)
from backend.v2.contexts.billing.domain.events import (
    PaymentDisputeNoticePayload,
    PaymentDisputeNoticeRequested,
)
from backend.v2.contexts.communications.application.ports import SendOutcome
from backend.v2.shared.tenancy import current_academy_id, tenant_scope


def _payload(**overrides: Any) -> PaymentDisputeNoticePayload:
    data: dict[str, Any] = {
        "dispute_id": "dp_1",
        "kind": "opened",
        "payment_id": "pay-1",
        "amount_cents": 12_500,
        "currency": "usd",
        "reason": "fraudulent",
        "status": "needs_response",
        "evidence_due_by": datetime(2026, 10, 9, tzinfo=UTC),
    }
    data.update(overrides)
    return PaymentDisputeNoticePayload(**data)


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, PaymentDisputeNoticePayload]] = []

    async def send_dispute_notice(self, *, payload: PaymentDisputeNoticePayload) -> None:
        self.calls.append((current_academy_id(), payload))


@pytest.fixture(autouse=True)
def _reset_notifier():
    yield
    install_dispute_notifier(None)


async def test_handler_sends_inside_the_event_tenant_scope() -> None:
    notifier = _RecordingNotifier()
    install_dispute_notifier(notifier)
    event = PaymentDisputeNoticeRequested(
        event_id="dispute-notice:acad_a:dp_1:opened",
        aggregate_id="dp_1",
        academy_id="acad_a",
        payload=_payload(),
    )
    await on_payment_dispute_notice_requested(event)
    assert notifier.calls == [("acad_a", event.payload)]


async def test_handler_skips_when_email_is_not_configured() -> None:
    install_dispute_notifier(None)
    event = PaymentDisputeNoticeRequested(
        aggregate_id="dp_1", academy_id="acad_a", payload=_payload()
    )
    await on_payment_dispute_notice_requested(event)  # no raise


def test_notifier_is_not_built_without_email_delivery() -> None:
    assert (
        build_dispute_notifier(object(), sender=None, users=None, academies=None, enabled=False)
        is None
    )


def test_render_escapes_and_names_the_dashboard() -> None:
    subject, body = render_dispute_notice(
        _payload(reason="<script>x</script>", dispute_id="dp_<b>")
    )
    assert subject == "A payment of $125.00 was disputed"
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "dp_&lt;b&gt;" in body
    assert "Stripe dashboard" in body
    assert "October 9, 2026" in body

    subject, body = render_dispute_notice(_payload(kind="closed", status="lost", outcome="lost"))
    assert subject == "Dispute closed: lost"
    assert "cardholder" in body


class _Users:
    async def get_by_id(self, user_id: str) -> Any:
        return SimpleNamespace(email=f"{user_id}@example.com", display_name="Owner")


class _Academies:
    async def get_academy_name(self, academy_id: str) -> str:
        return "Academy A"


class _Sender:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> SendOutcome:
        self.sent.append(kwargs)
        return SendOutcome(ok=True, provider_message_id="m1", failed_reason=None)


async def test_adapter_mails_the_academy_owner_only() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    await db["academy_memberships"].insert_many(
        [
            {"academy_id": "acad_a", "user_id": "owner-a", "roles": ["owner"], "status": "active"},
            {"academy_id": "acad_b", "user_id": "owner-b", "roles": ["owner"], "status": "active"},
            {"academy_id": "acad_a", "user_id": "coach-a", "roles": ["coach"], "status": "active"},
        ]
    )
    sender = _Sender()
    adapter = DisputeNoticeEmailAdapter(
        db=db, users=_Users(), academies=_Academies(), sender=sender
    )
    with tenant_scope("acad_a"):
        await adapter.send_dispute_notice(payload=_payload())
    assert [s["recipient"].email for s in sender.sent] == ["owner-a@example.com"]


async def test_adapter_fails_loudly_without_an_owner() -> None:
    db = mongomock_motor.AsyncMongoMockClient()["t"]
    adapter = DisputeNoticeEmailAdapter(
        db=db, users=_Users(), academies=_Academies(), sender=_Sender()
    )
    with tenant_scope("acad_a"), pytest.raises(ValueError, match="no active owner"):
        await adapter.send_dispute_notice(payload=_payload())
