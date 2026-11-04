"""Slice I — Connect webhook tenant-resolution-by-account.

Connect events carry a top-level ``account`` field (the connected account the
event happened on). The tenant guard must resolve that account to the owning
academy via the connected-account repo, accept it when it matches this
handler's academy, and quarantine an unknown / mismatched account.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
    _QuarantineStripeEvent,
)


class _FakeConnectAccountResolver:
    """Maps a connected stripe account id -> academy_id (tenant-scoped view)."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self.status_updates: list[dict[str, object]] = []

    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        return self._mapping.get(stripe_account_id)

    async def update_status(
        self,
        *,
        stripe_account_id: str,
        status: str,
        charges_enabled: bool | None,
        payouts_enabled: bool | None,
        capabilities: dict[str, str],
        skip_if_disconnected: bool = False,
        liability: dict[str, str] | None = None,
    ) -> bool:
        self.status_updates.append(
            {
                "stripe_account_id": stripe_account_id,
                "status": status,
                "charges_enabled": charges_enabled,
                "payouts_enabled": payouts_enabled,
                "capabilities": capabilities,
                "skip_if_disconnected": skip_if_disconnected,
                "liability": liability,
            }
        )
        return True


def _handler(*, academy_id: str, resolver: _FakeConnectAccountResolver) -> HandleWebhookEvent:
    class _NoopDedup:
        async def claim(self, *a, **k):
            return True

        async def mark_processed(self, *a, **k):
            return None

        async def mark_failed(self, *a, **k):
            return None

    return HandleWebhookEvent(
        stripe=object(),  # not used by the guard
        dedup=_NoopDedup(),
        payments=object(),
        subscriptions=object(),
        outbox=object(),
        academy_id=academy_id,
        connected_accounts=resolver,
    )


def _connect_event(*, account: str | None) -> dict:
    event: dict = {
        "id": "evt_1",
        "type": "account.updated",
        "data": {"object": {"id": account or "acct_x", "object": "account"}},
    }
    if account is not None:
        event["account"] = account
    return event


async def test_connect_event_resolves_to_matching_academy() -> None:
    resolver = _FakeConnectAccountResolver({"acct_A": "acad-1"})
    handler = _handler(academy_id="acad-1", resolver=resolver)

    resolved = await handler.resolve_academy_for_event(_connect_event(account="acct_A"))

    assert resolved == "acad-1"


async def test_connect_event_for_other_academy_is_quarantined() -> None:
    resolver = _FakeConnectAccountResolver({"acct_A": "acad-1"})
    # This handler serves a DIFFERENT academy — the account belongs to acad-1,
    # so processing it here must be rejected.
    handler = _handler(academy_id="acad-2", resolver=resolver)

    with pytest.raises(_QuarantineStripeEvent):
        await handler.resolve_academy_for_event(_connect_event(account="acct_A"))


async def test_connect_event_for_unknown_account_is_quarantined() -> None:
    resolver = _FakeConnectAccountResolver({})
    handler = _handler(academy_id="acad-1", resolver=resolver)

    with pytest.raises(_QuarantineStripeEvent):
        await handler.resolve_academy_for_event(_connect_event(account="acct_unknown"))


async def test_non_connect_event_falls_back_to_handler_academy() -> None:
    resolver = _FakeConnectAccountResolver({"acct_A": "acad-1"})
    handler = _handler(academy_id="acad-1", resolver=resolver)

    # No top-level account => platform (non-Connect) event; keep the handler's academy.
    resolved = await handler.resolve_academy_for_event(_connect_event(account=None))

    assert resolved == "acad-1"


async def test_validate_event_guards_quarantines_unknown_connect_account() -> None:
    resolver = _FakeConnectAccountResolver({})
    handler = _handler(academy_id="acad-1", resolver=resolver)

    with pytest.raises(_QuarantineStripeEvent):
        await handler._validate_event_guards_async(_connect_event(account="acct_unknown"))


async def test_account_updated_projects_connected_account_status() -> None:
    resolver = _FakeConnectAccountResolver({"acct_A": "acad-1"})
    handler = _handler(academy_id="acad-1", resolver=resolver)

    await handler._dispatch(
        "account.updated",
        {
            "id": "evt_account_updated",
            "type": "account.updated",
            "account": "acct_A",
            "data": {
                "object": {
                    "id": "acct_A",
                    "object": "account",
                    "charges_enabled": True,
                    "payouts_enabled": True,
                    "capabilities": {"card_payments": "active"},
                }
            },
        },
    )

    assert resolver.status_updates == [
        {
            "stripe_account_id": "acct_A",
            "status": "active",
            "charges_enabled": True,
            "payouts_enabled": True,
            "capabilities": {"card_payments": "active"},
            "skip_if_disconnected": True,
            # The payload names no controller: the liability is left alone.
            "liability": {},
        }
    ]


# --- ingest/processing hardening ----------------------------------------------


class _RecordingStripe:
    """Records every Stripe read; verifies any payload into ``event``."""

    def __init__(self, event: dict | None = None) -> None:
        self.event = event
        self.reads: list[tuple[str, str, dict]] = []

    def verify_webhook(self, payload: bytes, signature: str) -> dict:
        assert self.event is not None
        return self.event

    async def retrieve_payment_intent(self, object_id: str, **kwargs: object) -> dict:
        self.reads.append(("payment_intent", object_id, dict(kwargs)))
        return {"id": object_id}

    async def retrieve_checkout_session(self, object_id: str, **kwargs: object) -> dict:
        self.reads.append(("checkout_session", object_id, dict(kwargs)))
        return {"id": object_id}


class _StoredEventDedup:
    def __init__(self, event: dict) -> None:
        self._event = event
        self.stored: list[dict] = []
        self.quarantined: list[tuple[str, str]] = []
        self.processed: list[str] = []

    async def claim_next(self, **_: object) -> dict | None:
        return {
            "event_id": self._event["id"],
            "event_type": self._event["type"],
            "raw_payload": self._event,
        }

    async def mark_quarantined(self, event_id: str, reason: str, **_: object) -> None:
        self.quarantined.append((event_id, reason))

    async def mark_processed(self, event_id: str) -> None:
        self.processed.append(event_id)

    async def mark_failed(self, event_id: str, error: str) -> str:
        return "failed"

    async def store_received(self, event: dict, **_: object) -> bool:
        self.stored.append(event)
        return True


def _pi_event(account: str) -> dict:
    return {
        "id": "evt_pi",
        "type": "payment_intent.succeeded",
        "account": account,
        "livemode": False,
        "data": {"object": {"id": "pi_1", "object": "payment_intent", "metadata": {}}},
    }


async def test_unknown_account_is_quarantined_before_any_stripe_read() -> None:
    """Hydration reads the object with a ``Stripe-Account`` header; for an
    account no academy owns that read must never happen."""
    event = _pi_event("acct_unknown")
    stripe = _RecordingStripe()
    dedup = _StoredEventDedup(event)
    handler = HandleWebhookEvent(
        stripe=stripe,  # type: ignore[arg-type]
        dedup=dedup,  # type: ignore[arg-type]
        payments=object(),  # type: ignore[arg-type]
        subscriptions=object(),  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        academy_id="acad-1",
        connected_accounts=_FakeConnectAccountResolver({}),  # type: ignore[arg-type]
    )

    result = await handler.process_next(processor_id="p1")

    assert result["status"] == "quarantined"
    assert dedup.quarantined and dedup.quarantined[0][0] == "evt_pi"
    assert stripe.reads == []


async def test_other_academys_account_is_quarantined_before_any_stripe_read() -> None:
    event = _pi_event("acct_B")
    stripe = _RecordingStripe()
    dedup = _StoredEventDedup(event)
    handler = HandleWebhookEvent(
        stripe=stripe,  # type: ignore[arg-type]
        dedup=dedup,  # type: ignore[arg-type]
        payments=object(),  # type: ignore[arg-type]
        subscriptions=object(),  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        academy_id="acad-1",
        connected_accounts=_FakeConnectAccountResolver({"acct_B": "acad-2"}),  # type: ignore[arg-type]
    )

    result = await handler.process_next(processor_id="p1")

    assert result["status"] == "quarantined"
    assert stripe.reads == []


class _BrokenResolver(_FakeConnectAccountResolver):
    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        raise RuntimeError("mongo unavailable")


async def test_owner_lookup_failure_at_ingest_propagates_so_stripe_retries() -> None:
    from backend.v2.contexts.billing.domain.errors import WebhookAccountLookupUnavailable

    event = _pi_event("acct_A")
    dedup = _StoredEventDedup(event)
    handler = HandleWebhookEvent(
        stripe=_RecordingStripe(event),  # type: ignore[arg-type]
        dedup=dedup,  # type: ignore[arg-type]
        payments=object(),  # type: ignore[arg-type]
        subscriptions=object(),  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        academy_id="acad-1",
        connected_accounts=_BrokenResolver({}),  # type: ignore[arg-type]
    )

    with pytest.raises(WebhookAccountLookupUnavailable) as caught:
        await handler.accept(b"{}", "sig")

    # 5xx so Stripe redelivers; nothing was stored under the boot academy.
    assert caught.value.status_code >= 500
    assert dedup.stored == []


async def test_unknown_account_at_ingest_is_still_stored_not_5xx() -> None:
    event = _pi_event("acct_unknown")
    dedup = _StoredEventDedup(event)
    handler = HandleWebhookEvent(
        stripe=_RecordingStripe(event),  # type: ignore[arg-type]
        dedup=dedup,  # type: ignore[arg-type]
        payments=object(),  # type: ignore[arg-type]
        subscriptions=object(),  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        academy_id="acad-1",
        connected_accounts=_FakeConnectAccountResolver({}),  # type: ignore[arg-type]
    )

    result = await handler.accept(b"{}", "sig")

    assert result["stored"] is True
    assert len(dedup.stored) == 1
