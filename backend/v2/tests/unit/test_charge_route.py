"""The one charge-route resolver (house platform / connected / refused)."""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.charge_route import resolve_charge_route
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.charge_route import ChargeRoute, decide_charge_route
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount


def _account(*, ready: bool, stripe_account_id: str = "acct_x") -> ConnectedAccount:
    account = ConnectedAccount.new(academy_id="acad", stripe_account_id=stripe_account_id)
    if ready:
        account = account.with_status(status="active", charges_enabled=True)
    return account


class _Accounts:
    def __init__(self, account: ConnectedAccount | None) -> None:
        self._account = account
        self.calls = 0

    async def get_for_academy(self) -> ConnectedAccount | None:
        self.calls += 1
        return self._account


class _Settings:
    def __init__(self, settings: BillingSettings | Exception) -> None:
        self._settings = settings

    async def get(self) -> BillingSettings:
        if isinstance(self._settings, Exception):
            raise self._settings
        return self._settings


# --- domain rule ------------------------------------------------------------


def test_house_academy_is_platform_even_with_a_ready_account() -> None:
    route = decide_charge_route(is_house_academy=True, account=_account(ready=True))
    assert route == ChargeRoute.platform()
    assert route.connected_account_id is None
    assert route.payments_possible and not route.refused
    assert route.application_fee_cents(10_000) == 0


def test_ready_account_is_connected_with_fee() -> None:
    route = decide_charge_route(
        is_house_academy=False, account=_account(ready=True), application_fee_bps=250
    )
    assert route.kind == "connected"
    assert route.connected_account_id == "acct_x"
    assert route.application_fee_cents(10_001) == 250  # floor


def test_no_account_and_not_ready_are_refused() -> None:
    assert decide_charge_route(is_house_academy=False, account=None).kind == "no_account"
    not_ready = decide_charge_route(is_house_academy=False, account=_account(ready=False))
    assert not_ready.kind == "account_not_ready"
    assert not_ready.refused and not not_ready.payments_possible
    assert not_ready.connected_account_id is None


def test_disconnected_account_is_not_ready() -> None:
    from datetime import UTC, datetime

    account = _account(ready=True).model_copy(update={"disconnected_at": datetime.now(UTC)})
    assert decide_charge_route(is_house_academy=False, account=account).kind == (
        "account_not_ready"
    )


# --- application resolver ---------------------------------------------------


async def test_unwired_store_is_unconfigured() -> None:
    route = await resolve_charge_route(connected_accounts=None, settings=None, context="t")
    assert route.kind == "unconfigured"
    assert not route.refused
    assert route.connected_account_id is None


async def test_house_academy_skips_the_account_read() -> None:
    accounts = _Accounts(_account(ready=True))
    route = await resolve_charge_route(
        connected_accounts=accounts,
        settings=_Settings(BillingSettings(academy_id="acad", allow_platform_charge_fallback=True)),
        context="t",
    )
    assert route.is_platform
    assert accounts.calls == 0


async def test_non_house_ready_account_carries_fee_bps() -> None:
    route = await resolve_charge_route(
        connected_accounts=_Accounts(_account(ready=True, stripe_account_id="acct_t")),
        settings=_Settings(BillingSettings(academy_id="acad", application_fee_bps=100)),
        context="t",
    )
    assert route == ChargeRoute.connected("acct_t", application_fee_bps=100)


@pytest.mark.parametrize("ready", [True, False])
async def test_settings_failure_fails_closed_and_charges_no_fee(ready: bool) -> None:
    route = await resolve_charge_route(
        connected_accounts=_Accounts(_account(ready=ready)),
        settings=_Settings(RuntimeError("mongo down")),
        context="t",
    )
    if ready:
        assert route.kind == "connected"
        assert route.application_fee_cents(10_000) == 0
    else:
        assert route.kind == "account_not_ready"


# --- use cases route through the resolver -----------------------------------


class _Payments:
    def __init__(self) -> None:
        self.saved: list[object] = []

    async def save(self, payment: object) -> None:
        self.saved.append(payment)


@pytest.mark.parametrize("ready_account", [False, True])
async def test_start_checkout_house_academy_is_a_platform_charge(ready_account: bool) -> None:
    from backend.v2.contexts.billing.application.use_cases.start_checkout import (
        StartCheckout,
        StartCheckoutCommand,
    )
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
        FakeStripeGateway,
    )

    stripe = FakeStripeGateway()
    uc = StartCheckout(
        payment_repo=_Payments(),  # type: ignore[arg-type]
        stripe=stripe,
        academy_id="acad_blno",
        connected_accounts=_Accounts(_account(ready=ready_account)),  # type: ignore[arg-type]
        settings=_Settings(  # type: ignore[arg-type]
            BillingSettings(
                academy_id="acad_blno",
                allow_platform_charge_fallback=True,
                application_fee_bps=500,
            )
        ),
    )
    await uc.execute(
        StartCheckoutCommand(
            parent_id="par-1",
            session_id="sess-1",
            amount_cents=10_000,
            success_url="https://ok",
            cancel_url="https://cancel",
        )
    )
    record = stripe.checkouts[-1]
    assert record["connected_account_id"] is None
    assert record["stripe_account"] is None
    assert record["application_fee_amount"] is None


async def test_start_checkout_tenant_with_ready_account_is_a_direct_charge() -> None:
    from backend.v2.contexts.billing.application.use_cases.start_checkout import (
        StartCheckout,
        StartCheckoutCommand,
    )
    from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import (
        FakeStripeGateway,
    )

    stripe = FakeStripeGateway()
    uc = StartCheckout(
        payment_repo=_Payments(),  # type: ignore[arg-type]
        stripe=stripe,
        academy_id="acad_t",
        connected_accounts=_Accounts(  # type: ignore[arg-type]
            _account(ready=True, stripe_account_id="acct_t")
        ),
        settings=_Settings(  # type: ignore[arg-type]
            BillingSettings(academy_id="acad_t", application_fee_bps=100)
        ),
    )
    await uc.execute(
        StartCheckoutCommand(
            parent_id="par-1",
            session_id="sess-1",
            amount_cents=10_000,
            success_url="https://ok",
            cancel_url="https://cancel",
        )
    )
    record = stripe.checkouts[-1]
    # A direct charge ON the academy's account, carrying the academy's fee.
    assert record["stripe_account"] == "acct_t"
    assert record["connected_account_id"] is None
    assert record["application_fee_amount"] == 100
    assert stripe.account_of(record["checkout_id"]) == "acct_t"


# --- per-call helpers: account kwarg and idempotency key ---------------------


@pytest.mark.parametrize(
    "route",
    [
        ChargeRoute.platform(),
        ChargeRoute(kind="unconfigured"),
        ChargeRoute(kind="no_account"),
        ChargeRoute(kind="account_not_ready"),
    ],
)
def test_non_connected_routes_leave_the_call_and_key_unchanged(route: ChargeRoute) -> None:
    assert route.on_account_kwargs() == {}
    assert route.idempotency_key("autopay:inv-1:2026-09:100") == "autopay:inv-1:2026-09:100"


def test_connected_route_puts_the_call_and_key_on_the_account() -> None:
    route = ChargeRoute.connected("acct_x", application_fee_bps=250)
    assert route.on_account_kwargs() == {"stripe_account": "acct_x"}
    assert route.idempotency_key("k:fee25") == "k:fee25:acct:acct_x"
    # Two accounts never share a key.
    other = ChargeRoute.connected("acct_y")
    assert route.idempotency_key("k") != other.idempotency_key("k")


@pytest.mark.parametrize(
    ("amount", "bps", "fee"),
    [
        (10_000, 0, 0),  # default: no fee
        (10_000, 250, 250),
        (10_001, 250, 250),  # floor: the fraction stays with the academy
        (1, 9_999, 0),
        (15_000, 250, 375),
        (0, 250, 0),
    ],
)
def test_connected_route_fee_math(amount: int, bps: int, fee: int) -> None:
    assert (
        ChargeRoute.connected("acct_x", application_fee_bps=bps).application_fee_cents(amount)
        == fee
    )
