"""A single-invoice autopay retry reuses its idempotency key, on a real mongod.

The key used to carry the attempted amount and fee. A bank debit that Stripe
accepted but whose answer was lost parks the rung; if the retry then fails to
look up the payment method, the ACH discount drops, the amount changes, and a
new key would debit the parent a second time. The key is now the invoice and
its retry rung only, so Stripe refuses the changed amount and the rung parks.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
    ProcessDunningRetries,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.errors import StripeUnavailable
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_dunning_state_repo import (
    MongoDunningStateRepository,
)
from backend.v2.tests.contract.test_family_combined_charge import (
    ACAD,
    NOW,
    PARENT,
    FakeOutbox,
    _invoice,
    _Notifier,
    _seed,
)

pytestmark = pytest.mark.asyncio


class _AchSettings:
    async def get(self) -> BillingSettings:
        return BillingSettings(
            academy_id=ACAD,
            allow_platform_charge_fallback=True,
            ach_discount_enabled=True,
            ach_discount_percent=2.0,
            disclosure_version="v1",
        )


class _LostAnswerBankStripe(FakeStripeGateway):
    """Stripe debits the bank on the first call but the answer never arrives;
    after that the payment-method lookup fails once."""

    def __init__(self) -> None:
        super().__init__()
        self.seed_saved_card(
            academy_id=ACAD, parent_id=PARENT, customer_id="cus_1", payment_method_id="pm_bank"
        )
        self.payment_methods["pm_bank"] = {"id": "pm_bank", "type": "us_bank_account"}
        self.lose_answer = True
        self.lookup_down = False
        self.keys: list[str] = []

    async def retrieve_payment_method(self, pm_id: str, **kwargs: Any) -> dict[str, Any]:
        if self.lookup_down:
            raise StripeUnavailable("payment method lookup timed out")
        return await super().retrieve_payment_method(pm_id, **kwargs)

    async def create_off_session_payment_intent(self, **kwargs: Any) -> tuple[str, str, str | None]:
        self.keys.append(kwargs["idempotency_key"])
        result = await super().create_off_session_payment_intent(**kwargs)
        if self.lose_answer:
            self.lose_answer = False
            self.lookup_down = True
            raise StripeUnavailable("read timeout after Stripe accepted the request")
        return result


async def _tick(real_db: Any, stripe: FakeStripeGateway, at: Any) -> Any:
    repo = MongoDunningStateRepository(real_db)
    await repo.prepare_due_states(now=at, limit=100)
    charge = ChargeInvoiceViaAutopay(
        ledger=MongoBillingLedgerRepository(real_db),
        stripe=stripe,
        settings=_AchSettings(),
        connected_accounts=MongoConnectedAccountRepository(real_db),
        clock=lambda: at,
    )
    return await ProcessDunningRetries(
        dunning=repo,
        charge_invoice=charge,
        notifier=_Notifier(),
        outbox=FakeOutbox(),
        clock=lambda: at,
    ).execute(limit=20, worker_id="worker-1")


async def test_retry_after_lost_answer_reuses_key_and_never_debits_twice(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    stripe = _LostAnswerBankStripe()

    await _tick(real_db, stripe, NOW)
    assert len(stripe.off_session_payment_intents) == 1
    assert stripe.off_session_payment_intents[0]["amount_cents"] == 9_800  # 2% ACH off

    await _tick(real_db, stripe, NOW + timedelta(hours=1))

    assert len(stripe.keys) == 2
    assert stripe.keys[0] == stripe.keys[1]
    assert "9800" not in stripe.keys[0] and "10000" not in stripe.keys[0]
    assert len(stripe.off_session_payment_intents) == 1  # Stripe refused the new amount
    assert (await _invoice(real_db, "inv-a"))["status"] == "open"


async def test_a_new_rung_gets_a_new_key(real_db, acad) -> None:
    await _seed(real_db, "inv-a")
    stripe = FakeStripeGateway()
    stripe.seed_saved_card(
        academy_id=ACAD, parent_id=PARENT, customer_id="cus_1", payment_method_id="pm_1"
    )
    charge = ChargeInvoiceViaAutopay(
        ledger=MongoBillingLedgerRepository(real_db),
        stripe=stripe,
        settings=_AchSettings(),
        connected_accounts=MongoConnectedAccountRepository(real_db),
        clock=lambda: NOW,
    )
    seen: list[str] = []

    async def spy(**kwargs: Any) -> tuple[str, str, str | None]:
        seen.append(kwargs["idempotency_key"])
        return "", "failed", "card_declined"

    stripe.create_off_session_payment_intent = spy  # type: ignore[method-assign]
    await charge.execute("inv-a", retry_scope="dunning-attempt:1")
    await charge.execute("inv-a", retry_scope="dunning-attempt:2")
    await charge.execute("inv-a", retry_scope="dunning-attempt:1")
    assert seen[0] != seen[1] and seen[0] == seen[2]
