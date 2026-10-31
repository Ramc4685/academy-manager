"""Identity's stored-list vocabulary and billing's ``ManualPaymentMethod`` must
be the same six methods in the same order (they cannot import each other)."""

from __future__ import annotations

from typing import get_args

from backend.v2.contexts.billing.application.use_cases.record_manual_payment import (
    ManualPaymentMethod,
)
from backend.v2.contexts.identity.domain.manual_payment_methods import MANUAL_PAYMENT_METHODS


def test_identity_and_billing_agree_on_the_manual_methods() -> None:
    assert MANUAL_PAYMENT_METHODS == get_args(ManualPaymentMethod)
