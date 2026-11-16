"""Off-session charge errors: a decline vs our side of the wire (L1 A4-3, A4-1)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from backend.v2.contexts.billing.domain.errors import StripeUnavailable
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


def _gateway(monkeypatch: pytest.MonkeyPatch, raises: Exception) -> RealStripeGateway:
    mod = types.ModuleType("stripe")

    def _create(**_kwargs: Any) -> Any:
        raise raises

    mod.StripeError = _StripeError  # type: ignore[attr-defined]
    mod.CardError = _CardError  # type: ignore[attr-defined]
    mod.InvalidRequestError = _InvalidRequestError  # type: ignore[attr-defined]
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
