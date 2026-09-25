"""House-academy regression: the exact Stripe SDK calls stay byte-identical.

The house academy (BLNO) charges on the PLATFORM account. Threading an
optional ``stripe_account`` through the gateway (direct charges for every
other academy) must not change a single kwarg of a platform call: no
``stripe_account`` key at all, same idempotency keys, same params. Each test
pins the full kwargs of the house call, then shows that passing
``stripe_account`` adds exactly one kwarg — the Stripe-Account header — and
nothing else.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway

ACCT = "acct_tenant_1"


class _Obj(dict):
    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc


class _Calls:
    def __init__(self) -> None:
        self.log: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def last(self, name: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
        for call_name, args, kwargs in reversed(self.log):
            if call_name == name:
                return args, kwargs
        raise AssertionError(f"{name} was never called")


@pytest.fixture()
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    rec = _Calls()
    mod = types.ModuleType("stripe")

    class _StripeError(Exception):
        pass

    class _CardError(_StripeError):
        pass

    def _method(name: str, result: Any) -> Any:
        def _fn(*args: Any, **kwargs: Any) -> Any:
            rec.log.append((name, args, kwargs))
            return result(*args, **kwargs) if callable(result) else result

        return staticmethod(_fn)

    session_obj = _Obj(id="cs_1", url="https://stripe.test/cs_1")
    customer = _Obj(id="cus_1", invoice_settings=_Obj(default_payment_method="pm_1"))

    mod.StripeError = _StripeError  # type: ignore[attr-defined]
    mod.CardError = _CardError  # type: ignore[attr-defined]
    mod.checkout = types.SimpleNamespace(  # type: ignore[attr-defined]
        Session=type(
            "Session",
            (),
            {
                "create": _method("checkout.Session.create", session_obj),
                "retrieve": _method("checkout.Session.retrieve", _Obj(id="cs_1")),
                "expire": _method("checkout.Session.expire", None),
            },
        )
    )
    mod.billing_portal = types.SimpleNamespace(  # type: ignore[attr-defined]
        Session=type(
            "Session",
            (),
            {"create": _method("billing_portal.Session.create", _Obj(url="https://p"))},
        )
    )
    mod.PaymentIntent = type(  # type: ignore[attr-defined]
        "PaymentIntent",
        (),
        {
            "create": _method("PaymentIntent.create", _Obj(id="pi_1", status="succeeded")),
            "retrieve": _method("PaymentIntent.retrieve", _Obj(id="pi_1")),
            "search": _method("PaymentIntent.search", _Obj(data=[])),
        },
    )
    mod.SetupIntent = type(  # type: ignore[attr-defined]
        "SetupIntent", (), {"retrieve": _method("SetupIntent.retrieve", _Obj(id="seti_1"))}
    )
    mod.PaymentMethod = type(  # type: ignore[attr-defined]
        "PaymentMethod", (), {"retrieve": _method("PaymentMethod.retrieve", _Obj(id="pm_1"))}
    )
    mod.Customer = type(  # type: ignore[attr-defined]
        "Customer",
        (),
        {
            "modify": _method("Customer.modify", customer),
            "search": _method("Customer.search", _Obj(data=[customer])),
        },
    )
    mod.Charge = type(  # type: ignore[attr-defined]
        "Charge", (), {"list": _method("Charge.list", _Obj(data=[]))}
    )
    mod.Refund = type(  # type: ignore[attr-defined]
        "Refund", (), {"create": _method("Refund.create", _Obj(id="re_1"))}
    )
    mod.StripeClient = lambda api_key: types.SimpleNamespace()  # type: ignore[attr-defined]
    mod.api_key = None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stripe", mod)
    return rec


def _gw() -> RealStripeGateway:
    return RealStripeGateway(api_key="sk_test", webhook_secret="whsec_test")


def _assert_only_header_added(house: dict[str, Any], direct: dict[str, Any]) -> None:
    assert "stripe_account" not in house
    assert direct == {**house, "stripe_account": ACCT}


# --- checkout (registration) -------------------------------------------------


async def test_house_registration_checkout_kwargs(calls: _Calls) -> None:
    await _gw().create_checkout_session(
        parent_id="par-1",
        session_id="sess-1",
        amount_cents=15_000,
        success_url="https://app.test/ok",
        cancel_url="https://app.test/cancel",
        metadata={"academy_id": "acad_blno", "payment_id": "pay-1"},
    )
    _, house = calls.last("checkout.Session.create")
    expires_at = house.pop("expires_at")
    assert isinstance(expires_at, int)
    assert house == {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Academy session sess-1"},
                    "unit_amount": 15_000,
                },
                "quantity": 1,
            }
        ],
        "success_url": "https://app.test/ok",
        "cancel_url": "https://app.test/cancel",
        "metadata": {"academy_id": "acad_blno", "payment_id": "pay-1"},
    }

    await _gw().create_checkout_session(
        parent_id="par-1",
        session_id="sess-1",
        amount_cents=15_000,
        success_url="https://app.test/ok",
        cancel_url="https://app.test/cancel",
        metadata={"academy_id": "acad_blno", "payment_id": "pay-1"},
        stripe_account=ACCT,
    )
    _, direct = calls.last("checkout.Session.create")
    direct.pop("expires_at")
    _assert_only_header_added(house, direct)


# --- autopay setup checkout --------------------------------------------------


async def test_house_autopay_setup_checkout_kwargs(calls: _Calls) -> None:
    kwargs: dict[str, Any] = {
        "parent_id": "par-1",
        "enrollment_id": "enr-1",
        "session_id": "st-1",
        "success_url": "https://app.test/ok",
        "cancel_url": "https://app.test/cancel",
        "metadata": {"academy_id": "acad_blno", "source": "autopay_setup"},
    }
    await _gw().create_autopay_setup_checkout_session(**kwargs)
    _, house = calls.last("checkout.Session.create")
    setup_metadata = {
        "academy_id": "acad_blno",
        "source": "autopay_setup",
        "enrollment_id": "enr-1",
        "session_id": "st-1",
    }
    assert house == {
        "mode": "setup",
        "currency": "usd",
        "success_url": "https://app.test/ok",
        "cancel_url": "https://app.test/cancel",
        "client_reference_id": "par-1",
        "customer_creation": "always",
        "metadata": setup_metadata,
        "setup_intent_data": {"metadata": setup_metadata},
    }

    await _gw().create_autopay_setup_checkout_session(**kwargs, stripe_account=ACCT)
    _, direct = calls.last("checkout.Session.create")
    _assert_only_header_added(house, direct)


# --- invoice checkout (pay link / balance) ----------------------------------


@pytest.mark.parametrize("autopay_optin", [False, True])
async def test_house_invoice_checkout_kwargs(calls: _Calls, autopay_optin: bool) -> None:
    kwargs: dict[str, Any] = {
        "invoice_id": "inv-1",
        "amount_cents": 4100,
        "currency": "usd",
        "success_url": "https://app.test/ok",
        "cancel_url": "https://app.test/cancel",
        "metadata": {"academy_id": "acad_blno", "parent_id": "par-1"},
        "idempotency_key": "invoice-checkout:inv-1:4100",
    }
    if autopay_optin:
        kwargs |= {"save_payment_method_for_autopay": True, "autopay_enrollment_ids": ["e1"]}
    await _gw().create_invoice_checkout_session(**kwargs)
    _, house = calls.last("checkout.Session.create")
    metadata = {"academy_id": "acad_blno", "parent_id": "par-1"}
    if autopay_optin:
        metadata |= {"autopay_optin": "true", "enrollment_ids": "e1"}
    payment_intent_data: dict[str, Any] = {"metadata": metadata}
    if autopay_optin:
        payment_intent_data["setup_future_usage"] = "off_session"
    expected: dict[str, Any] = {
        "mode": "payment",
        "line_items": [
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Academy invoice inv-1"},
                    "unit_amount": 4100,
                },
                "quantity": 1,
            }
        ],
        "success_url": "https://app.test/ok",
        "cancel_url": "https://app.test/cancel",
        "client_reference_id": "par-1",
        "metadata": metadata,
        "payment_intent_data": payment_intent_data,
        # Same idempotency key the house path always sent.
        "idempotency_key": "invoice-checkout:inv-1:4100",
    }
    if autopay_optin:
        expected["customer_creation"] = "always"
    assert house == expected

    await _gw().create_invoice_checkout_session(**kwargs, stripe_account=ACCT)
    _, direct = calls.last("checkout.Session.create")
    _assert_only_header_added(house, direct)


# --- autopay: saved card lookup + off-session charge -------------------------


async def test_house_autopay_saved_card_lookup_kwargs(calls: _Calls) -> None:
    found = await _gw().get_default_payment_method(academy_id="acad_blno", parent_id="par-1")
    assert found == ("cus_1", "pm_1")
    _, house = calls.last("Customer.search")
    assert house == {
        "query": 'metadata["academy_id"]:"acad_blno" AND metadata["parent_id"]:"par-1"',
        "limit": 1,
    }

    await _gw().get_default_payment_method(
        academy_id="acad_blno", parent_id="par-1", stripe_account=ACCT
    )
    _, direct = calls.last("Customer.search")
    _assert_only_header_added(house, direct)


async def test_house_autopay_off_session_payment_intent_kwargs(calls: _Calls) -> None:
    kwargs: dict[str, Any] = {
        "amount_cents": 4100,
        "currency": "usd",
        "customer_id": "cus_1",
        "payment_method_id": "pm_1",
        "idempotency_key": "autopay:inv-1:2026-09:4100",
        "metadata": {"invoice_id": "inv-1", "academy_id": "acad_blno"},
    }
    await _gw().create_off_session_payment_intent(**kwargs)
    _, house = calls.last("PaymentIntent.create")
    assert house == {
        "amount": 4100,
        "currency": "usd",
        "customer": "cus_1",
        "payment_method": "pm_1",
        "off_session": True,
        "confirm": True,
        "idempotency_key": "autopay:inv-1:2026-09:4100",
        "metadata": {"invoice_id": "inv-1", "academy_id": "acad_blno"},
    }

    await _gw().create_off_session_payment_intent(**kwargs, stripe_account=ACCT)
    _, direct = calls.last("PaymentIntent.create")
    _assert_only_header_added(house, direct)


async def test_direct_charge_fee_rides_on_the_connected_account(calls: _Calls) -> None:
    await _gw().create_off_session_payment_intent(
        amount_cents=10_000,
        currency="usd",
        customer_id="cus_1",
        payment_method_id="pm_1",
        idempotency_key="k",
        metadata={},
        application_fee_cents=250,
        stripe_account=ACCT,
    )
    _, call = calls.last("PaymentIntent.create")
    assert call["stripe_account"] == ACCT
    assert call["application_fee_amount"] == 250
    assert "on_behalf_of" not in call and "transfer_data" not in call


async def test_destination_and_direct_at_once_is_refused(calls: _Calls) -> None:
    with pytest.raises(ValueError, match="both"):
        await _gw().create_off_session_payment_intent(
            amount_cents=100,
            currency="usd",
            customer_id="cus_1",
            payment_method_id="pm_1",
            idempotency_key="k",
            metadata={},
            connected_account_id=ACCT,
            stripe_account=ACCT,
        )


async def test_platform_fee_without_any_connected_account_is_refused(calls: _Calls) -> None:
    with pytest.raises(ValueError):
        await _gw().create_off_session_payment_intent(
            amount_cents=100,
            currency="usd",
            customer_id="cus_1",
            payment_method_id="pm_1",
            idempotency_key="k",
            metadata={},
            application_fee_cents=5,
        )


# --- reads, customer updates, portal, refunds --------------------------------


@pytest.mark.parametrize(
    ("method", "sdk_name", "object_id"),
    [
        ("retrieve_checkout_session", "checkout.Session.retrieve", "cs_1"),
        ("expire_checkout_session", "checkout.Session.expire", "cs_1"),
        ("retrieve_payment_intent", "PaymentIntent.retrieve", "pi_1"),
        ("retrieve_setup_intent", "SetupIntent.retrieve", "seti_1"),
        ("retrieve_payment_method", "PaymentMethod.retrieve", "pm_1"),
    ],
)
async def test_house_object_reads_send_only_the_id(
    calls: _Calls, method: str, sdk_name: str, object_id: str
) -> None:
    await getattr(_gw(), method)(object_id)
    args, house = calls.last(sdk_name)
    assert args == (object_id,)
    assert house == {}

    await getattr(_gw(), method)(object_id, stripe_account=ACCT)
    args, direct = calls.last(sdk_name)
    assert args == (object_id,)
    _assert_only_header_added(house, direct)


async def test_house_set_default_payment_method_kwargs(calls: _Calls) -> None:
    kwargs: dict[str, Any] = {
        "stripe_customer_id": "cus_1",
        "stripe_payment_method_id": "pm_1",
        "metadata": {"academy_id": "acad_blno"},
    }
    await _gw().set_customer_default_payment_method(**kwargs)
    args, house = calls.last("Customer.modify")
    assert args == ("cus_1",)
    assert house == {
        "invoice_settings": {"default_payment_method": "pm_1"},
        "metadata": {"academy_id": "acad_blno"},
    }

    await _gw().set_customer_default_payment_method(**kwargs, stripe_account=ACCT)
    _, direct = calls.last("Customer.modify")
    _assert_only_header_added(house, direct)


async def test_house_portal_and_charge_list_kwargs(calls: _Calls) -> None:
    await _gw().create_customer_portal_session(
        parent_id="par-1", return_url="https://app.test/r", stripe_customer_id="cus_1"
    )
    _, house_portal = calls.last("billing_portal.Session.create")
    assert house_portal == {"customer": "cus_1", "return_url": "https://app.test/r"}
    await _gw().create_customer_portal_session(
        parent_id="par-1",
        return_url="https://app.test/r",
        stripe_customer_id="cus_1",
        stripe_account=ACCT,
    )
    _, direct_portal = calls.last("billing_portal.Session.create")
    _assert_only_header_added(house_portal, direct_portal)

    await _gw().list_charges_for_customer(stripe_customer_id="cus_1")
    _, house_list = calls.last("Charge.list")
    assert house_list == {"customer": "cus_1", "limit": 100}
    await _gw().list_charges_for_customer(stripe_customer_id="cus_1", stripe_account=ACCT)
    _, direct_list = calls.last("Charge.list")
    _assert_only_header_added(house_list, direct_list)


async def test_house_refund_kwargs(calls: _Calls) -> None:
    await _gw().issue_refund("pi_1", 500, idempotency_key="refund:pay-1:500")
    args, house_pi = calls.last("PaymentIntent.retrieve")
    assert args == ("pi_1",) and house_pi == {}
    _, house = calls.last("Refund.create")
    # A platform charge (no transfer_data) gets no destination-refund flags.
    assert house == {
        "payment_intent": "pi_1",
        "amount": 500,
        "idempotency_key": "refund:pay-1:500",
    }

    await _gw().issue_refund("pi_1", 500, idempotency_key="refund:pay-1:500", stripe_account=ACCT)
    _, direct_pi = calls.last("PaymentIntent.retrieve")
    assert direct_pi == {"stripe_account": ACCT}
    _, direct = calls.last("Refund.create")
    _assert_only_header_added(house, direct)
