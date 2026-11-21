"""Off-session charge errors: a decline vs our side of the wire (L1 A4-3, A4-1)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from backend.v2.contexts.billing.domain.errors import (
    StripeIdempotencyConflict,
    StripeUnavailable,
)
from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway


class _StripeError(Exception):
    def __init__(self, message: str = "", *, code: str | None = None, decline_code=None) -> None:
        super().__init__(message)
        self.code = code
        self.error = types.SimpleNamespace(code=code, decline_code=decline_code)


class _CardError(_StripeError):
    pass


class _InvalidRequestError(_StripeError):
    pass


class _APIConnectionError(_StripeError):
    pass


class _IdempotencyError(_StripeError):
    pass


def _gateway(monkeypatch: pytest.MonkeyPatch, raises: Exception) -> RealStripeGateway:
    mod = types.ModuleType("stripe")

    def _create(**_kwargs: Any) -> Any:
        raise raises

    mod.StripeError = _StripeError  # type: ignore[attr-defined]
    mod.CardError = _CardError  # type: ignore[attr-defined]
    mod.InvalidRequestError = _InvalidRequestError  # type: ignore[attr-defined]
    mod.IdempotencyError = _IdempotencyError  # type: ignore[attr-defined]
    mod.PaymentIntent = types.SimpleNamespace(create=_create)  # type: ignore[attr-defined]
    mod.StripeClient = lambda api_key: types.SimpleNamespace()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "stripe", mod)
    return RealStripeGateway(api_key="sk_test", webhook_secret="whsec_test")


async def _charge(gateway: RealStripeGateway) -> tuple[str, str, str | None]:
    return await gateway.create_off_session_payment_intent(
        amount_cents=100,
        currency="usd",
        customer_id="cus_1",
        payment_method_id="pm_1",
        idempotency_key="k",
        metadata={},
    )


@pytest.mark.asyncio
async def test_card_decline_returns_decline_code(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = _gateway(
        monkeypatch, _CardError("declined", code="card_declined", decline_code="insufficient_funds")
    )
    assert await _charge(gw) == ("", "failed", "insufficient_funds")


@pytest.mark.asyncio
async def test_card_error_without_decline_code_returns_the_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A blocked bank account arrives as a 402 CardError with only `code`.
    gw = _gateway(
        monkeypatch, _CardError("Your bank account is unusable", code="bank_account_unusable")
    )
    assert await _charge(gw) == ("", "failed", "bank_account_unusable")


@pytest.mark.asyncio
async def test_removed_payment_method_is_no_saved_payment_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _gateway(
        monkeypatch, _InvalidRequestError("No such PaymentMethod", code="resource_missing")
    )
    assert await _charge(gw) == ("", "failed", "no_saved_payment_method")


@pytest.mark.asyncio
async def test_network_and_api_errors_raise_stripe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _gateway(monkeypatch, _APIConnectionError("connection reset"))
    with pytest.raises(StripeUnavailable):
        await _charge(gw)


@pytest.mark.asyncio
async def test_a_reused_key_with_other_parameters_is_its_own_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stripe refusing a key reused with other parameters is not an outage: an
    earlier request under this key exists, so it must not read as StripeUnavailable."""
    gw = _gateway(
        monkeypatch,
        _IdempotencyError("Keys for idempotent requests can only...", code="idempotency_error"),
    )
    with pytest.raises(StripeIdempotencyConflict) as raised:
        await _charge(gw)
    assert not isinstance(raised.value, StripeUnavailable)


@pytest.mark.asyncio
async def test_a_key_still_in_use_is_retried_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``idempotency_key_in_use``: a concurrent request with the key is still in
    flight. Retriable, so it is an outage-style park, not a review."""
    gw = _gateway(
        monkeypatch, _IdempotencyError("request in progress", code="idempotency_key_in_use")
    )
    with pytest.raises(StripeUnavailable):
        await _charge(gw)


def _cancel_gateway(monkeypatch: pytest.MonkeyPatch, raises: Exception) -> RealStripeGateway:
    gw = _gateway(monkeypatch, raises)

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise raises

    sys.modules["stripe"].Subscription = types.SimpleNamespace(  # type: ignore[attr-defined]
        modify=_raise, delete=_raise
    )
    return gw


@pytest.mark.asyncio
@pytest.mark.parametrize("at_period_end", [True, False])
async def test_cancel_of_a_subscription_stripe_no_longer_has_succeeds(
    monkeypatch: pytest.MonkeyPatch, at_period_end: bool
) -> None:
    gw = _cancel_gateway(
        monkeypatch, _InvalidRequestError("No such subscription", code="resource_missing")
    )
    await gw.cancel_subscription("sub_gone", at_period_end=at_period_end)


@pytest.mark.asyncio
async def test_cancel_still_raises_other_stripe_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = _cancel_gateway(monkeypatch, _InvalidRequestError("bad", code="parameter_invalid"))
    with pytest.raises(_InvalidRequestError):
        await gw.cancel_subscription("sub_1", at_period_end=False)
