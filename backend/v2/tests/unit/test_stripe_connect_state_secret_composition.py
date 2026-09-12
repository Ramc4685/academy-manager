"""Stripe Connect OAuth state secret must fail closed (#547).

The OAuth callback (``GET /academy/gateway/stripe/callback``) is unauthenticated:
the only thing binding a returning Stripe account to an academy is the HMAC over
the ``state`` parameter. Signing that HMAC with an empty key makes the state
forgeable by anyone, so a misconfigured deployment must disable the flow rather
than accept ``HMAC_SHA256("", ...)``. The webhook secret is a different-purpose
key and is no longer accepted as a fallback.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings


class _NoopStripe:
    pass


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_STRIPE_CONNECT_STATE_SECRET", raising=False)
    monkeypatch.delenv("V2_STRIPE_WEBHOOK_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


def _admin_use_cases(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_NoopStripe(),  # type: ignore[arg-type]
    )


def test_missing_state_secret_disables_stripe_connect_use_cases(mongo_db, monkeypatch) -> None:
    # Webhook secret present but no Connect state secret: the cross-purpose
    # fallback is gone, so both OAuth-state use cases must stay unwired.
    monkeypatch.setenv("V2_STRIPE_WEBHOOK_SECRET", "whsec_not_a_state_secret")
    get_settings.cache_clear()

    admin = _admin_use_cases(mongo_db)

    assert admin.start_stripe_connect_use_case is None
    assert admin.complete_stripe_connect_use_case is None


def test_blank_state_secret_disables_stripe_connect_use_cases(mongo_db, monkeypatch) -> None:
    monkeypatch.setenv("V2_STRIPE_CONNECT_STATE_SECRET", "   ")
    get_settings.cache_clear()

    admin = _admin_use_cases(mongo_db)

    assert admin.start_stripe_connect_use_case is None
    assert admin.complete_stripe_connect_use_case is None


def test_present_state_secret_enables_stripe_connect_use_cases(mongo_db, monkeypatch) -> None:
    monkeypatch.setenv("V2_STRIPE_CONNECT_STATE_SECRET", "connect_state_secret_value")
    get_settings.cache_clear()

    admin = _admin_use_cases(mongo_db)

    assert admin.start_stripe_connect_use_case is not None
    assert admin.complete_stripe_connect_use_case is not None
