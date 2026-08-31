"""Issue #549 — `expire_checkout_session` must classify its Stripe failures.

Retiring a superseded Checkout Session is allowed to fail in exactly ONE benign
way: Stripe refuses because the session is already complete or expired, which is
the "parent paid on the old tab" race the supersede exists to survive. Every
other failure leaves the session OPEN and PAYABLE.

The gateway used to collapse both into a bare ``ValueError``, so the caller had
no way to tell them apart and swallowed the dangerous one at INFO. These tests
drive the REAL ``RealStripeGateway`` against REAL ``stripe`` exception types.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.contexts.billing.application.ports import (
    StripeCheckoutSessionNotExpirable,
    StripeTransientFailure,
)
from backend.v2.contexts.billing.infrastructure.stripe_gateway import RealStripeGateway

stripe = pytest.importorskip("stripe")


@pytest.fixture()
def gateway(monkeypatch: pytest.MonkeyPatch) -> RealStripeGateway:
    # api_key is set on the stripe module by the constructor; restore it so this
    # never leaks into another test in the same process.
    monkeypatch.setattr(stripe, "api_key", getattr(stripe, "api_key", None), raising=False)
    return RealStripeGateway(api_key="sk_test_549", webhook_secret="whsec_549")


def _raise(gw: RealStripeGateway, exc: Exception) -> None:
    def _expire(_session_id: str, **_kwargs: Any) -> None:
        raise exc

    gw._stripe.checkout.Session.expire = _expire  # type: ignore[attr-defined]


async def test_already_complete_session_is_reported_as_terminal(
    gateway: RealStripeGateway,
) -> None:
    _raise(
        gateway,
        stripe.InvalidRequestError(
            "You may only expire an open Checkout Session.",
            param=None,
            http_status=400,
        ),
    )

    with pytest.raises(StripeCheckoutSessionNotExpirable):
        await gateway.expire_checkout_session("cs_done")


async def test_connection_error_is_reported_as_transient(gateway: RealStripeGateway) -> None:
    """The case that made the old blanket swallow unsafe: we never reached
    Stripe, so the session is still open and still payable."""
    _raise(gateway, stripe.APIConnectionError("Unexpected error communicating with Stripe"))

    with pytest.raises(StripeTransientFailure):
        await gateway.expire_checkout_session("cs_open")
    # A transient failure must NOT be mistakable for the terminal one, even
    # though both remain ValueErrors for older callers.
    assert not issubclass(StripeTransientFailure, StripeCheckoutSessionNotExpirable)


async def test_rate_limit_is_reported_as_transient(gateway: RealStripeGateway) -> None:
    _raise(gateway, stripe.RateLimitError("Too many requests", http_status=429))

    with pytest.raises(StripeTransientFailure):
        await gateway.expire_checkout_session("cs_open")


async def test_server_error_is_reported_as_transient(gateway: RealStripeGateway) -> None:
    _raise(gateway, stripe.APIError("Stripe is temporarily unavailable", http_status=503))

    with pytest.raises(StripeTransientFailure):
        await gateway.expire_checkout_session("cs_open")


async def test_a_successful_expiry_raises_nothing(gateway: RealStripeGateway) -> None:
    calls: list[str] = []

    def _expire(session_id: str, **_kwargs: Any) -> None:
        calls.append(session_id)

    gateway._stripe.checkout.Session.expire = _expire  # type: ignore[attr-defined]

    await gateway.expire_checkout_session("cs_open")

    assert calls == ["cs_open"]
