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

from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)


async def test_start_onboarding_drives_real_repo_and_is_idempotent(db, acad) -> None:
    stripe = FakeStripeGateway()
    repo = MongoConnectedAccountRepository(db)
    use_case = StartConnectOnboarding(stripe=stripe, connected_accounts=repo, academy_id=acad)

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
    use_case = StartConnectOnboarding(stripe=stripe, connected_accounts=repo, academy_id=acad)
    created = await use_case.start(
        academy_id=acad,
        refresh_url="https://app.test/refresh",
        return_url="https://app.test/return",
    )
    acct_id = created["stripe_account_id"]

    resolver = _ConnectAccountResolver(repo, acad)

    assert await resolver.academy_id_for_account(acct_id) == acad
    assert await resolver.academy_id_for_account("acct_unknown") is None
