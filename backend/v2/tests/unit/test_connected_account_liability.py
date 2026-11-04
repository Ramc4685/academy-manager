"""Direct charges only on accounts where Stripe, not the platform, is liable.

Accounts created before direct charges are express accounts with
``fees_collector``/``losses_collector`` = ``application``: a direct charge on
one would make the platform pay Stripe's fees and carry the account's losses.
The route must refuse unless BOTH collectors are known to be ``stripe``;
unknown (legacy rows written before the fields existed) fails closed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.application.billing_health import evaluate_billing_health
from backend.v2.contexts.billing.domain.charge_route import ChargeRoute, decide_charge_route
from backend.v2.contexts.billing.domain.connected_account import (
    ConnectedAccount,
    liability_from_stripe_account,
)


def _ready(**liability: str | None) -> ConnectedAccount:
    return ConnectedAccount.new(
        academy_id="acad", stripe_account_id="acct_x", **liability
    ).with_status(status="active", charges_enabled=True)


# --- the route ---------------------------------------------------------------


def test_legacy_row_with_unknown_liability_is_refused() -> None:
    route = decide_charge_route(is_house_academy=False, account=_ready())
    assert route.kind == "account_platform_liable"
    assert route.refused and not route.payments_possible
    assert route.connected_account_id is None
    assert route.on_account_kwargs() == {}
    assert route.refusal_message is not None
    assert "reconnect Stripe" in route.refusal_message


def test_express_application_liable_account_is_refused() -> None:
    account = _ready(
        fees_collector="application", losses_collector="application", dashboard="express"
    )
    assert decide_charge_route(is_house_academy=False, account=account).kind == (
        "account_platform_liable"
    )


def test_one_collector_on_the_platform_is_still_refused() -> None:
    for fees, losses in (("stripe", "application"), ("application", "stripe"), ("stripe", None)):
        account = _ready(fees_collector=fees, losses_collector=losses)
        route = decide_charge_route(is_house_academy=False, account=account)
        assert route.kind == "account_platform_liable", (fees, losses)


def test_stripe_liable_ready_account_is_a_direct_charge() -> None:
    account = _ready(fees_collector="stripe", losses_collector="stripe", dashboard="full")
    route = decide_charge_route(is_house_academy=False, account=account)
    assert route.kind == "connected"
    assert route.connected_account_id == "acct_x"
    assert route.refusal_message is None


def test_house_academy_is_unaffected_by_liability() -> None:
    assert decide_charge_route(is_house_academy=True, account=_ready()) == ChargeRoute.platform()


def test_not_ready_stripe_liable_account_still_reports_not_ready() -> None:
    account = ConnectedAccount.new(
        academy_id="acad",
        stripe_account_id="acct_x",
        fees_collector="stripe",
        losses_collector="stripe",
    )
    assert decide_charge_route(is_house_academy=False, account=account).kind == (
        "account_not_ready"
    )


# --- reading the liability model off Stripe -----------------------------------


def test_liability_from_a_v2_account() -> None:
    assert liability_from_stripe_account(
        {
            "id": "acct_1",
            "dashboard": "full",
            "defaults": {
                "responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"}
            },
        }
    ) == {"fees_collector": "stripe", "losses_collector": "stripe", "dashboard": "full"}


def test_liability_from_a_v1_account_controller() -> None:
    # A v1 Account (account.updated payloads, Account.retrieve): the account
    # paying fees is ``fees.payer = "account"``, i.e. Stripe collects them.
    assert liability_from_stripe_account(
        {
            "id": "acct_1",
            "controller": {
                "fees": {"payer": "account"},
                "losses": {"payments": "stripe"},
                "stripe_dashboard": {"type": "full"},
            },
        }
    ) == {"fees_collector": "stripe", "losses_collector": "stripe", "dashboard": "full"}
    assert liability_from_stripe_account(
        {
            "controller": {
                "fees": {"payer": "application_express"},
                "losses": {"payments": "application"},
                "stripe_dashboard": {"type": "express"},
            }
        }
    ) == {
        "fees_collector": "application_express",
        "losses_collector": "application",
        "dashboard": "express",
    }


def test_liability_absent_from_the_snapshot_is_empty() -> None:
    assert liability_from_stripe_account({"id": "acct_1", "charges_enabled": True}) == {}
    assert liability_from_stripe_account(None) == {}


def test_reconnect_resync_refreshes_liability_and_keeps_it_when_absent() -> None:
    legacy = _ready()
    resynced = legacy.reconnected(
        stripe_account={
            "charges_enabled": True,
            "controller": {"fees": {"payer": "application"}, "losses": {"payments": "application"}},
        }
    )
    assert resynced.fees_collector == "application"
    assert resynced.losses_collector == "application"
    assert not resynced.supports_direct_charges()

    direct = _ready(fees_collector="stripe", losses_collector="stripe")
    assert direct.reconnected(stripe_account={"charges_enabled": True}).supports_direct_charges()
    assert direct.reconnected().supports_direct_charges()


# --- billing health names the reason -----------------------------------------


def test_billing_health_uses_the_refusal_reason_when_given() -> None:
    verdict = evaluate_billing_health(
        payments_possible=False,
        connected_account_ready=True,
        quarantined_webhooks=0,
        last_run=None,
        autopay_disable_failures=0,
        now=datetime(2026, 9, 25, tzinfo=UTC),
        payments_blocked_reason="Reconnect Stripe: this account is not set up for direct charges.",
    )
    assert verdict.state == "blocked"
    reason = next(r for r in verdict.reasons if r.code == "connect_not_ready")
    assert "direct charges" in reason.detail
