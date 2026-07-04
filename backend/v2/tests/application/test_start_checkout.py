"""StartCheckout use-case tests."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckout,
    StartCheckoutCommand,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
    FakeStripeGateway,
)


class FakePaymentRepo:
    def __init__(self) -> None:
        self.saved: list[Payment] = []

    async def save(self, p: Payment) -> None:
        self.saved.append(p)

    async def get(self, pid):
        for p in self.saved:
            if p.payment_id == pid:
                return p
        return None

    async def get_by_stripe_pi(self, _):
        return None

    async def get_by_checkout_session(self, _):
        return None

    async def list_for_parent(self, _):
        return []


class _StubConnectedAccount:
    def __init__(self, *, ready: bool, stripe_account_id: str = "acct_ready_1") -> None:
        self._ready = ready
        self.stripe_account_id = stripe_account_id

    def is_ready_for_charges(self) -> bool:
        return self._ready


class _FakeConnectedAccounts:
    def __init__(self, account: _StubConnectedAccount | None) -> None:
        self._account = account

    async def get_for_academy(self):
        return self._account


class _FakeBillingSettings:
    def __init__(self, settings: BillingSettings) -> None:
        self._settings = settings

    async def get(self) -> BillingSettings:
        return self._settings


class _RaisingBillingSettings:
    async def get(self) -> BillingSettings:
        raise RuntimeError("settings store unavailable")


@pytest.mark.asyncio
async def test_start_checkout_routes_destination_charge_when_connected_account_ready() -> None:
    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(
        payment_repo=repo,
        stripe=stripe,
        academy_id="acad",
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=True)),
    )
    result = await uc.execute(
        StartCheckoutCommand(
            parent_id="p1",
            session_id="s1",
            amount_cents=15000,
            success_url="https://app/success",
            cancel_url="https://app/cancel",
        )
    )
    assert result.payment_id
    assert stripe.checkouts[0]["connected_account_id"] == "acct_ready_1"


@pytest.mark.asyncio
async def test_start_checkout_refuses_platform_charge_when_connected_account_not_ready() -> None:
    from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed

    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(
        payment_repo=repo,
        stripe=stripe,
        academy_id="acad",
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),
    )
    with pytest.raises(CheckoutCreationFailed):
        await uc.execute(
            StartCheckoutCommand(
                parent_id="p1",
                session_id="s1",
                amount_cents=15000,
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
        )
    assert stripe.checkouts == []
    assert repo.saved == []


@pytest.mark.asyncio
async def test_start_checkout_creates_payment_and_stripe_session() -> None:
    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(payment_repo=repo, stripe=stripe, academy_id="acad")
    result = await uc.execute(
        StartCheckoutCommand(
            parent_id="p1",
            session_id="s1",
            amount_cents=15000,
            success_url="https://app/success",
            cancel_url="https://app/cancel",
        )
    )
    assert result.payment_id
    assert result.redirect_url.startswith("https://fake.stripe.com/")
    assert len(repo.saved) == 1
    assert repo.saved[0].status == "pending"
    assert repo.saved[0].amount_cents == 15000
    assert len(stripe.checkouts) == 1
    assert stripe.checkouts[0]["metadata"]["payment_id"] == result.payment_id


# ---------------------------------------------------------------------------
# allow_platform_charge_fallback (temporary Connect-review escape hatch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_fallback_enabled_creates_checkout_with_platform_charge() -> None:
    """Flag on + account not ready → checkout created with connected_account_id=None."""
    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(
        payment_repo=repo,
        stripe=stripe,
        academy_id="acad",
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),
        settings=_FakeBillingSettings(
            BillingSettings(academy_id="acad", allow_platform_charge_fallback=True)
        ),
    )
    result = await uc.execute(
        StartCheckoutCommand(
            parent_id="p1",
            session_id="s1",
            amount_cents=15000,
            success_url="https://app/success",
            cancel_url="https://app/cancel",
        )
    )
    assert result.payment_id
    assert stripe.checkouts[0]["connected_account_id"] is None


@pytest.mark.asyncio
async def test_platform_fallback_disabled_still_raises_when_account_not_ready() -> None:
    """Flag off (default) + account not ready → still raises as today."""
    from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed

    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(
        payment_repo=repo,
        stripe=stripe,
        academy_id="acad",
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),
        settings=_FakeBillingSettings(
            BillingSettings(academy_id="acad", allow_platform_charge_fallback=False)
        ),
    )
    with pytest.raises(CheckoutCreationFailed):
        await uc.execute(
            StartCheckoutCommand(
                parent_id="p1",
                session_id="s1",
                amount_cents=15000,
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
        )
    assert stripe.checkouts == []
    assert repo.saved == []


@pytest.mark.asyncio
async def test_platform_fallback_settings_lookup_failure_fails_closed() -> None:
    """Settings lookup raises + account not ready → still raises (fail closed)."""
    from backend.v2.contexts.billing.domain.errors import CheckoutCreationFailed

    stripe = FakeStripeGateway()
    repo = FakePaymentRepo()
    uc = StartCheckout(
        payment_repo=repo,
        stripe=stripe,
        academy_id="acad",
        connected_accounts=_FakeConnectedAccounts(_StubConnectedAccount(ready=False)),
        settings=_RaisingBillingSettings(),
    )
    with pytest.raises(CheckoutCreationFailed):
        await uc.execute(
            StartCheckoutCommand(
                parent_id="p1",
                session_id="s1",
                amount_cents=15000,
                success_url="https://app/success",
                cancel_url="https://app/cancel",
            )
        )
    assert stripe.checkouts == []
    assert repo.saved == []
