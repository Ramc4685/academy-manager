"""Request-shape contract tests for the Stripe gateway (Slice I — Connect).

These assert the exact params the RealStripeGateway sends to Stripe without
hitting the network: we install a fake ``stripe`` module, capture kwargs, and
assert on them. The LOCKED design decisions verified here:

* Accounts v2 (``/v2/core/accounts``) via v2 ``configuration`` and
  ``defaults.responsibilities`` — never legacy ``type`` or v1 ``controller``.
* Destination charges: ``on_behalf_of`` + ``transfer_data.destination`` are
  PRESENT on the off-session PaymentIntent and the autopay setup checkout.
* ``payment_method_types`` is ABSENT everywhere (dynamic payment methods).
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway


class _FakeResult(dict):
    """Behaves like a stripe object: attribute + item access over a dict."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc


class _Recorder:
    def __init__(self) -> None:
        self.calls: dict[str, dict[str, Any]] = {}

    def record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls[name] = kwargs


@pytest.fixture()
def fake_stripe(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    recorder = _Recorder()
    mod = types.ModuleType("stripe")

    class _StripeError(Exception):
        pass

    class _CardError(_StripeError):
        pass

    mod.StripeError = _StripeError  # type: ignore[attr-defined]
    mod.CardError = _CardError  # type: ignore[attr-defined]

    # checkout.Session.create
    checkout = types.SimpleNamespace()

    class _Session:
        @staticmethod
        def create(**kwargs: Any) -> _FakeResult:
            recorder.record("checkout.Session.create", kwargs)
            return _FakeResult(id="cs_test_123", url="https://stripe.test/cs_test_123")

    checkout.Session = _Session
    mod.checkout = checkout  # type: ignore[attr-defined]

    # PaymentIntent.create
    class _PaymentIntent:
        @staticmethod
        def create(**kwargs: Any) -> _FakeResult:
            recorder.record("PaymentIntent.create", kwargs)
            return _FakeResult(id="pi_test_123", status="succeeded")

    mod.PaymentIntent = _PaymentIntent  # type: ignore[attr-defined]

    # v2 accounts + account links (Accounts v2)
    class _AccountsV2:
        @staticmethod
        def create(**kwargs: Any) -> _FakeResult:
            recorder.record("v2.core.accounts.create", kwargs)
            return _FakeResult(id="acct_v2_123")

    class _AccountLink:
        @staticmethod
        def create(**kwargs: Any) -> _FakeResult:
            recorder.record("AccountLink.create", kwargs)
            return _FakeResult(url="https://connect.stripe.test/onboard/abc")

    v2 = types.SimpleNamespace(
        core=types.SimpleNamespace(accounts=_AccountsV2()),
    )
    mod.v2 = v2  # type: ignore[attr-defined]
    mod.AccountLink = _AccountLink  # type: ignore[attr-defined]
    mod.api_key = None  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "stripe", mod)
    return recorder


def _gateway() -> RealStripeGateway:
    return RealStripeGateway(api_key="sk_test", webhook_secret="whsec_test")


async def test_create_connected_account_uses_accounts_v2_payload_not_legacy_controller(
    fake_stripe: _Recorder,
) -> None:
    gw = _gateway()

    account_id = await gw.create_connected_account(
        academy_id="acad-1",
        display_name="North Shore Badminton",
        contact_email="owner@example.com",
    )

    assert account_id == "acct_v2_123"
    call = fake_stripe.calls["v2.core.accounts.create"]
    assert "type" not in call
    assert "controller" not in call
    assert call["dashboard"] == "full"
    assert call["configuration"] == {
        "merchant": {
            "capabilities": {
                "card_payments": {"requested": True},
            }
        }
    }
    assert call["defaults"] == {
        "currency": "usd",
        "responsibilities": {
            "fees_collector": "application",
            "losses_collector": "application",
        },
    }
    assert call["idempotency_key"] == "connect-account:acad-1"


async def test_create_account_onboarding_link_uses_account_link(
    fake_stripe: _Recorder,
) -> None:
    gw = _gateway()

    url = await gw.create_account_onboarding_link(
        stripe_account_id="acct_v2_123",
        refresh_url="https://app.test/connect/refresh",
        return_url="https://app.test/connect/return",
    )

    assert url == "https://connect.stripe.test/onboard/abc"
    call = fake_stripe.calls["AccountLink.create"]
    assert call["account"] == "acct_v2_123"
    assert call["refresh_url"] == "https://app.test/connect/refresh"
    assert call["return_url"] == "https://app.test/connect/return"


async def test_off_session_payment_intent_has_connect_params_and_no_pmt_types(
    fake_stripe: _Recorder,
) -> None:
    gw = _gateway()

    await gw.create_off_session_payment_intent(
        amount_cents=2500,
        currency="usd",
        customer_id="cus_1",
        payment_method_id="pm_1",
        idempotency_key="idem-1",
        metadata={"academy_id": "acad-1"},
        connected_account_id="acct_v2_123",
    )

    call = fake_stripe.calls["PaymentIntent.create"]
    assert call["on_behalf_of"] == "acct_v2_123"
    assert call["transfer_data"] == {"destination": "acct_v2_123"}
    assert call.get("application_fee_amount", 0) == 0
    # Dynamic payment methods: never pin payment_method_types.
    assert "payment_method_types" not in call
    # Customers are created on the PLATFORM, not the connected account.
    assert "stripe_account" not in call


async def test_off_session_payment_intent_without_connected_account_omits_connect_params(
    fake_stripe: _Recorder,
) -> None:
    gw = _gateway()

    await gw.create_off_session_payment_intent(
        amount_cents=2500,
        currency="usd",
        customer_id="cus_1",
        payment_method_id="pm_1",
        idempotency_key="idem-1",
        metadata={"academy_id": "acad-1"},
        connected_account_id=None,
    )

    call = fake_stripe.calls["PaymentIntent.create"]
    assert "on_behalf_of" not in call
    assert "transfer_data" not in call
    assert "payment_method_types" not in call


async def test_autopay_setup_checkout_has_connect_params_and_no_pmt_types(
    fake_stripe: _Recorder,
) -> None:
    gw = _gateway()

    await gw.create_autopay_setup_checkout_session(
        parent_id="parent-1",
        enrollment_id="enr-1",
        session_id="sess-1",
        success_url="https://app.test/ok",
        cancel_url="https://app.test/cancel",
        metadata={"academy_id": "acad-1"},
        connected_account_id="acct_v2_123",
    )

    call = fake_stripe.calls["checkout.Session.create"]
    # setup-mode checkout routes the eventual off-session merchant of record.
    assert call["setup_intent_data"]["on_behalf_of"] == "acct_v2_123"
    assert "payment_method_types" not in call
    # Customer created on the platform.
    assert "stripe_account" not in call
