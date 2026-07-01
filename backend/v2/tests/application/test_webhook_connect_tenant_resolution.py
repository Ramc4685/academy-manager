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

    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        return self._mapping.get(stripe_account_id)


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
