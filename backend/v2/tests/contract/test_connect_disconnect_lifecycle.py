"""Stripe Connect disconnect / reconnect lifecycle (audit 2026-09-25 X6, X9).

Drives the REAL ``MongoConnectedAccountRepository`` through the same shims
composition wires (``ConnectedAccountGatewayDisabler`` for the owner
disconnect, ``_ConnectAccountResolver`` for the webhook handler) so the
stickiness rule is proven against real update semantics, not a permissive fake.

- X6: a disconnect is local only, so Stripe keeps emitting ``account.updated``
  for the account. That must not silently re-activate it.
- X9: reconnecting (starting onboarding again) must reset the status and
  resync it from Stripe instead of reusing the ``disabled`` row as-is.
"""

from __future__ import annotations

from typing import Any

from backend.v2.composition.connected_account_adapters import (
    ConnectedAccountGatewayDisabler,
)
from backend.v2.composition.parent import _ConnectAccountResolver
from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.application.use_cases.handle_webhook_event import (
    HandleWebhookEvent,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_directory import (
    MongoConnectedAccountDirectory,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)

_ACCT = "acct_live_blno"
_ALLOWED_ORIGINS = ("https://app.test",)


async def _seed_active(repo: MongoConnectedAccountRepository, academy_id: str) -> None:
    account = ConnectedAccount.new(academy_id=academy_id, stripe_account_id=_ACCT).with_status(
        status="active",
        charges_enabled=True,
        payouts_enabled=True,
        capabilities={"card_payments": "active", "transfers": "active"},
    )
    await repo.upsert(account)


def _webhook_handler(repo: MongoConnectedAccountRepository, academy_id: str) -> HandleWebhookEvent:
    return HandleWebhookEvent(
        stripe=object(),  # type: ignore[arg-type]
        dedup=object(),  # type: ignore[arg-type]
        payments=object(),  # type: ignore[arg-type]
        subscriptions=object(),  # type: ignore[arg-type]
        outbox=object(),  # type: ignore[arg-type]
        academy_id=academy_id,
        connected_accounts=_ConnectAccountResolver(
            repo, academy_id, directory=MongoConnectedAccountDirectory(repo._db)
        ),
    )


def _account_updated(*, charges_enabled: bool) -> dict[str, Any]:
    return {
        "id": "evt_account_updated",
        "type": "account.updated",
        "account": _ACCT,
        "data": {
            "object": {
                "id": _ACCT,
                "object": "account",
                "charges_enabled": charges_enabled,
                "payouts_enabled": charges_enabled,
                "capabilities": {"card_payments": "active", "transfers": "active"},
            }
        },
    }


def _capability_updated() -> dict[str, Any]:
    # capability.* payloads carry no account-level charges_enabled.
    return {
        "id": "evt_capability_updated",
        "type": "capability.updated",
        "account": _ACCT,
        "data": {
            "object": {
                "id": "card_payments",
                "object": "capability",
                "account": _ACCT,
                "status": "active",
            }
        },
    }


def _onboarding(stripe: FakeStripeGateway, repo, academy_id: str) -> StartConnectOnboarding:
    return StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=repo,
        allowed_redirect_origins=_ALLOWED_ORIGINS,
        academy_id=academy_id,
    )


async def _start(use_case: StartConnectOnboarding, academy_id: str) -> dict[str, str]:
    return await use_case.start(
        academy_id=academy_id,
        refresh_url="https://app.test/admin/settings?panel=gateway&stripe=refresh",
        return_url="https://app.test/admin/settings?panel=gateway&stripe=connected",
    )


# --- X6: disconnect is sticky against webhooks -------------------------------


async def test_account_updated_after_disconnect_does_not_reactivate(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)

    await ConnectedAccountGatewayDisabler(repo).disable_for_academy(acad)
    await _webhook_handler(repo, acad)._dispatch(
        "account.updated", _account_updated(charges_enabled=True)
    )

    account = await repo.get_for_academy()
    assert account is not None
    assert account.status == "disabled"
    assert account.charges_enabled is False
    assert account.is_disconnected
    assert not account.is_ready_for_charges()


async def test_capability_event_after_disconnect_does_not_reactivate(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)

    await ConnectedAccountGatewayDisabler(repo).disable_for_academy(acad)
    await _webhook_handler(repo, acad)._dispatch("capability.updated", _capability_updated())

    account = await repo.get_for_academy()
    assert account is not None
    assert account.status == "disabled"
    assert not account.is_ready_for_charges()


async def test_capability_event_keeps_status_through_the_composition_resolver(db, acad) -> None:
    """The capability branch reads the existing row through the resolver shim.
    The shim used to lack ``get_by_stripe_account_id``, so every capability.*
    event raised AttributeError in production wiring."""
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)

    await _webhook_handler(repo, acad)._dispatch("capability.updated", _capability_updated())

    account = await repo.get_for_academy()
    assert account is not None
    assert account.status == "active"
    assert account.is_ready_for_charges()


async def test_account_updated_still_activates_a_connected_account(db, acad) -> None:
    """Regression guard: stickiness applies only to disconnected rows."""
    repo = MongoConnectedAccountRepository(db)
    await repo.upsert(ConnectedAccount.new(academy_id=acad, stripe_account_id=_ACCT))

    await _webhook_handler(repo, acad)._dispatch(
        "account.updated", _account_updated(charges_enabled=True)
    )

    account = await repo.get_for_academy()
    assert account is not None
    assert account.status == "active"
    assert account.is_ready_for_charges()


async def test_legacy_disabled_row_without_marker_stays_webhook_updatable(db, acad) -> None:
    """Rows disabled before the marker existed have no ``disconnected_at``.
    The conditional write must still match them (a missing field reads as
    not-disconnected), so this change does not freeze pre-existing rows."""
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)
    await repo.collection.update_one(
        {"stripe_account_id": _ACCT},
        {"$set": {"status": "disabled", "charges_enabled": False}},
    )

    await _webhook_handler(repo, acad)._dispatch(
        "account.updated", _account_updated(charges_enabled=True)
    )

    account = await repo.get_for_academy()
    assert account is not None
    assert account.status == "active"


# --- X9: reconnect resets and resyncs ----------------------------------------


async def test_reconnect_resets_marker_and_resyncs_from_stripe(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)
    await ConnectedAccountGatewayDisabler(repo).disable_for_academy(acad)
    stripe = FakeStripeGateway()
    stripe.account_snapshots[_ACCT] = {
        "id": _ACCT,
        "object": "account",
        "charges_enabled": True,
        "payouts_enabled": True,
        "capabilities": {"card_payments": "active", "transfers": "active"},
        "requirements": {"disabled_reason": None},
    }

    result = await _start(_onboarding(stripe, repo, acad), acad)

    assert result["stripe_account_id"] == _ACCT  # same Stripe account reused
    assert result["status"] == "active"
    assert stripe.connected_accounts == []  # no new Stripe account created
    assert stripe.retrieved_connected_accounts == [_ACCT]
    account = await repo.get_for_academy()
    assert account is not None
    assert account.disconnected_at is None
    assert account.status == "active"
    assert account.is_ready_for_charges()


async def test_reconnect_of_unfinished_account_resyncs_to_restricted(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)
    await ConnectedAccountGatewayDisabler(repo).disable_for_academy(acad)
    stripe = FakeStripeGateway()  # default snapshot: charges not enabled

    result = await _start(_onboarding(stripe, repo, acad), acad)

    assert result["status"] == "restricted"
    account = await repo.get_for_academy()
    assert account is not None
    assert account.disconnected_at is None
    assert not account.is_ready_for_charges()


async def test_reconnect_then_webhook_updates_status_again(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)
    await ConnectedAccountGatewayDisabler(repo).disable_for_academy(acad)
    await _start(_onboarding(FakeStripeGateway(), repo, acad), acad)

    await _webhook_handler(repo, acad)._dispatch(
        "account.updated", _account_updated(charges_enabled=True)
    )

    account = await repo.get_for_academy()
    assert account is not None
    assert account.status == "active"
    assert account.is_ready_for_charges()


class _ResyncFailingGateway(FakeStripeGateway):
    async def retrieve_connected_account(self, stripe_account_id: str) -> dict[str, Any]:
        raise ValueError("Stripe Account lookup failed: api_connection_error")


async def test_reconnect_with_failed_resync_resets_to_pending(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)
    await ConnectedAccountGatewayDisabler(repo).disable_for_academy(acad)
    stripe = _ResyncFailingGateway()

    result = await _start(_onboarding(stripe, repo, acad), acad)

    assert result["onboarding_url"]  # the owner still gets the onboarding link
    assert result["status"] == "pending"
    account = await repo.get_for_academy()
    assert account is not None
    assert account.disconnected_at is None
    assert account.status == "pending"
    assert account.charges_enabled is False


async def test_refreshing_link_on_live_account_does_not_resync(db, acad) -> None:
    repo = MongoConnectedAccountRepository(db)
    await _seed_active(repo, acad)
    stripe = FakeStripeGateway()

    result = await _start(_onboarding(stripe, repo, acad), acad)

    assert result["status"] == "active"
    assert stripe.retrieved_connected_accounts == []
