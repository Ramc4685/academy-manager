"""Wiring test — drive the REAL connected-account repo through the ports/shims
that composition relies on, so a method-name mismatch fails a test (Slice B
lesson).

1. The real ``StartConnectOnboarding`` use case must persist + reuse a real
   ``MongoConnectedAccountRepository`` through the ``ConnectedAccountRepository``
   port.
2. The webhook's Connect account resolver shim (``academy_id_for_account``) must
   drive the real repo's ``get_by_stripe_account_id``.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    StartSubscriptionCheckout,
    StartSubscriptionCheckoutCommand,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.errors import ConnectOnboardingFailed
from backend.v2.contexts.billing.domain.models import Subscription
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.shared.security.redirect import InvalidRedirectUrl


class _SubscriptionRepo:
    async def save(self, subscription: Subscription) -> None:
        raise AssertionError("setup checkout should not create subscription rows")

    async def get(self, subscription_id: str) -> Subscription | None:
        return None

    async def get_by_stripe_sub(self, stripe_sub: str) -> Subscription | None:
        return None

    async def get_by_checkout_session(self, checkout_session_id: str) -> Subscription | None:
        return None

    async def latest_for_enrollment(self, enrollment_id: str) -> Subscription | None:
        return None


_ALLOWED_ORIGINS = ("https://app.test",)


class _FailingConnectAccountGateway(FakeStripeGateway):
    async def create_connected_account(
        self,
        *,
        academy_id: str,
        display_name: str | None = None,
        contact_email: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        raise ValueError("Stripe account_create_activation_required: sensitive provider detail")


async def test_start_onboarding_drives_real_repo_and_is_idempotent(db, acad) -> None:
    stripe = FakeStripeGateway()
    repo = MongoConnectedAccountRepository(db)
    use_case = StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=repo,
        allowed_redirect_origins=_ALLOWED_ORIGINS,
        academy_id=acad,
    )

    first = await use_case.start(
        academy_id=acad,
        refresh_url="https://app.test/refresh",
        return_url="https://app.test/return",
    )
    assert first["academy_id"] == acad
    assert first["stripe_account_id"].startswith("acct_fake_")
    assert first["onboarding_url"]
    assert first["status"] == "pending"

    # Second call reuses the SAME connected account (no duplicate creation).
    second = await use_case.start(
        academy_id=acad,
        refresh_url="https://app.test/refresh",
        return_url="https://app.test/return",
    )
    assert second["stripe_account_id"] == first["stripe_account_id"]
    assert len(stripe.connected_accounts) == 1
    assert await repo.collection.count_documents({}) == 1


async def test_start_onboarding_rejects_disallowed_redirect_origin(db, acad) -> None:
    """refresh_url/return_url go through the same allowlist as parent checkout
    redirects — a non-allowlisted origin must be rejected before any Stripe call."""
    stripe = FakeStripeGateway()
    repo = MongoConnectedAccountRepository(db)
    use_case = StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=repo,
        allowed_redirect_origins=_ALLOWED_ORIGINS,
        academy_id=acad,
    )

    with pytest.raises(InvalidRedirectUrl):
        await use_case.start(
            academy_id=acad,
            refresh_url="https://evil.example/refresh",
            return_url="https://app.test/return",
        )
    with pytest.raises(InvalidRedirectUrl):
        await use_case.start(
            academy_id=acad,
            refresh_url="https://app.test/refresh",
            return_url="http://blno.localhost:3001/return",
        )
    # Nothing was created on the rejected calls.
    assert len(stripe.connected_accounts) == 0
    assert await repo.collection.count_documents({}) == 0


async def test_start_onboarding_maps_stripe_failure_to_sanitized_domain_error(db, acad) -> None:
    stripe = _FailingConnectAccountGateway()
    repo = MongoConnectedAccountRepository(db)
    use_case = StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=repo,
        allowed_redirect_origins=_ALLOWED_ORIGINS,
        academy_id=acad,
    )

    with pytest.raises(ConnectOnboardingFailed) as exc_info:
        await use_case.start(
            academy_id=acad,
            refresh_url="https://app.test/refresh",
            return_url="https://app.test/return",
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.message == "Stripe Connect onboarding is temporarily unavailable."
    assert "account_create_activation_required" not in exc_info.value.message
    assert await repo.collection.count_documents({}) == 0


class _ConnectAccountResolver:
    """Same shim shape composition installs on the webhook handler."""

    def __init__(self, repo: MongoConnectedAccountRepository, academy_id: str) -> None:
        self._repo = repo
        self._academy_id = academy_id

    async def academy_id_for_account(self, stripe_account_id: str) -> str | None:
        from backend.v2.shared.tenancy import tenant_scope

        with tenant_scope(self._academy_id):
            account = await self._repo.get_by_stripe_account_id(stripe_account_id)
        return account.academy_id if account else None


async def test_webhook_resolver_shim_drives_real_repo(db, acad) -> None:
    stripe = FakeStripeGateway()
    repo = MongoConnectedAccountRepository(db)
    use_case = StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=repo,
        allowed_redirect_origins=_ALLOWED_ORIGINS,
        academy_id=acad,
    )
    created = await use_case.start(
        academy_id=acad,
        refresh_url="https://app.test/refresh",
        return_url="https://app.test/return",
    )
    acct_id = created["stripe_account_id"]

    resolver = _ConnectAccountResolver(repo, acad)

    assert await resolver.academy_id_for_account(acct_id) == acad
    assert await resolver.academy_id_for_account("acct_unknown") is None


async def test_autopay_setup_checkout_drives_real_connected_account_repo(db, acad) -> None:
    stripe = FakeStripeGateway()
    repo = MongoConnectedAccountRepository(db)
    await repo.upsert(
        ConnectedAccount.new(academy_id=acad, stripe_account_id="acct_ready").with_status(
            status="active",
            charges_enabled=True,
        )
    )
    use_case = StartSubscriptionCheckout(
        subscriptions=_SubscriptionRepo(),
        stripe=stripe,
        academy_id=acad,
        connected_accounts=repo,
    )

    await use_case.execute(
        StartSubscriptionCheckoutCommand(
            parent_id="parent-1",
            enrollment_id="enr-1",
            session_id="session-1",
            amount_cents=5_000,
            success_url="https://app.test/success",
            cancel_url="https://app.test/cancel",
        )
    )

    assert stripe.autopay_setup_checkouts[0]["connected_account_id"] == "acct_ready"
