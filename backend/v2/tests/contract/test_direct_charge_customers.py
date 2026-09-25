"""Direct charges: customers, saved cards and autopay live on the academy's account.

On a real ``mongod`` with every migration applied (0204's validator included)
and the account-aware fake gateway (an object minted on one Stripe account is
``resource_missing`` on every other account, like Stripe), this pins:

* a non-house academy's autopay setup checkout runs ON its connected account;
  the parent's return poll reads it back THERE, and the saved card is recorded
  with ``stripe_account_id`` = that account;
* off-session autopay then charges exactly that STORED customer and card, on
  that account (no platform Customer search), with the account in the
  idempotency key;
* a card stored for the platform is never charged on a connected account (and
  the reverse): the charge refuses instead of reaching Stripe;
* the record's account moves only with its ids: writing a customer for a
  different account drops the old account's saved cards;
* the house academy keeps the historical shape: no ``stripe_account_id``,
  platform Customer search, platform PaymentIntent, unchanged key.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo.errors import WriteError

from backend.v2.contexts.billing.application.use_cases.charge_invoice_via_autopay import (
    ChargeInvoiceViaAutopay,
)
from backend.v2.contexts.billing.application.use_cases.parent_billing import (
    GetCheckoutStatus,
    StartSubscriptionCheckout,
    StartSubscriptionCheckoutCommand,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_ledger_repo import (
    MongoBillingLedgerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_parent_billing_customer_repo import (
    MongoParentBillingCustomerRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.billing.infrastructure.mongo_subscription_repo import (
    MongoSubscriptionRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-direct-a"
ACCT = f"acct_{ACAD}"
HOUSE = "acad-house-a"
PARENT = "parent-direct-1"
ENROLLMENT = "enroll-direct-1"
INVOICE = "inv-direct-1"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


class _EnrollmentAutopay:
    def __init__(self) -> None:
        self.activated: list[str] = []

    async def mark_autopay_active_from_setup(
        self, *, enrollment_id: str, session: Any | None = None
    ) -> bool:
        self.activated.append(enrollment_id)
        return True

    async def set_autopay_state(self, **_: Any) -> bool:  # pragma: no cover - unused
        return True


class _HouseSettings:
    """The house academy's settings: platform charges allowed."""

    async def get(self) -> BillingSettings:
        return BillingSettings(academy_id=HOUSE, allow_platform_charge_fallback=True)


async def _seed_ready_account(db: Any) -> None:
    with tenant_scope(ACAD):
        await MongoConnectedAccountRepository(db).upsert(
            ConnectedAccount(
                academy_id=ACAD,
                stripe_account_id=ACCT,
                status="active",
                charges_enabled=True,
                payouts_enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )


async def _seed_invoice(db: Any, academy_id: str) -> None:
    await db["invoices"].insert_one(
        {
            "invoice_id": INVOICE,
            "academy_id": academy_id,
            "parent_id": PARENT,
            "student_id": "student-direct-1",
            "enrollment_id": ENROLLMENT,
            "period": "2026-09",
            "status": "open",
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 10_000,
            "refunded_cents": 0,
            "currency": "usd",
            "due_date": datetime(2026, 9, 30, tzinfo=UTC),
            "version": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


def _charge(db: Any, stripe: FakeStripeGateway, *, settings: Any = None) -> Any:
    return ChargeInvoiceViaAutopay(
        ledger=MongoBillingLedgerRepository(db),
        stripe=stripe,
        settings=settings or MongoBillingSettingsRepository(db),
        connected_accounts=MongoConnectedAccountRepository(db),
        parent_customers=MongoParentBillingCustomerRepository(db),
        clock=lambda: NOW,
    )


async def test_direct_setup_then_autopay_runs_entirely_on_the_academy_account(real_db) -> None:
    await _seed_ready_account(real_db)
    stripe = FakeStripeGateway()
    customers = MongoParentBillingCustomerRepository(real_db)
    enrollment_autopay = _EnrollmentAutopay()

    with tenant_scope(ACAD):
        started = await StartSubscriptionCheckout(
            subscriptions=MongoSubscriptionRepository(real_db),
            stripe=stripe,
            academy_id=ACAD,
            connected_accounts=MongoConnectedAccountRepository(real_db),
            settings=MongoBillingSettingsRepository(real_db),
        ).execute(
            StartSubscriptionCheckoutCommand(
                parent_id=PARENT,
                enrollment_id=ENROLLMENT,
                session_id="session-direct-1",
                amount_cents=10_000,
                success_url="https://app.test/ok",
                cancel_url="https://app.test/cancel",
            )
        )
        # The setup session (and so its customer and card) is ON the account.
        assert stripe.account_of(started.checkout_session_id) == ACCT
        setup = stripe.autopay_setup_checkouts[-1]
        assert setup["stripe_account"] == ACCT
        assert setup["connected_account_id"] is None

        # The parent's return poll must read the session back on the account;
        # the fake answers resource_missing anywhere else.
        status = await GetCheckoutStatus(
            payments=MongoPaymentRepository(real_db),
            stripe=stripe,
            parent_customers=customers,
            enrollment_autopay=enrollment_autopay,
            academy_id=ACAD,
            connected_accounts=MongoConnectedAccountRepository(real_db),
            settings=MongoBillingSettingsRepository(real_db),
        ).execute(started.checkout_session_id, parent_id=PARENT)
        assert status.status == "active"
        assert enrollment_autopay.activated == [ENROLLMENT]

        doc = await customers.get_academy_customer(parent_id=PARENT)
        assert doc is not None
        assert doc["stripe_account_id"] == ACCT
        assert stripe.account_of(doc["stripe_customer_id"]) == ACCT
        assert stripe.account_of(doc["default_payment_method_id"]) == ACCT
        assert stripe.customer_default_payment_methods[-1]["stripe_account"] == ACCT

        await _seed_invoice(real_db, ACAD)
        result = await _charge(real_db, stripe).execute(INVOICE)

    assert result.success is True
    pi = stripe.off_session_payment_intents[-1]
    assert pi["stripe_account"] == ACCT
    assert pi["on_behalf_of"] is None and pi["transfer_data"] is None
    assert (pi["customer_id"], pi["payment_method_id"]) == (
        doc["stripe_customer_id"],
        doc["default_payment_method_id"],
    )
    assert pi["idempotency_key"] == f"autopay:{INVOICE}:2026-09:10000:acct:{ACCT}"
    assert stripe.account_of(pi["id"]) == ACCT


async def test_a_platform_card_is_never_charged_on_the_connected_account(real_db) -> None:
    """A legacy platform customer/card (no stripe_account_id) for a non-house
    academy: the direct route finds no card on the account and refuses — it
    never sends the platform ids to the connected account."""
    await _seed_ready_account(real_db)
    stripe = FakeStripeGateway()
    stripe.seed_saved_card(
        academy_id=ACAD, parent_id=PARENT, customer_id="cus_platform", payment_method_id="pm_plat"
    )
    await real_db["parent_billing_customers"].insert_one(
        {
            "academy_id": ACAD,
            "parent_id": PARENT,
            "stripe_customer_id": "cus_platform",
            "default_payment_method_id": "pm_plat",
            "created_at": NOW,
        }
    )
    await _seed_invoice(real_db, ACAD)

    with tenant_scope(ACAD), pytest.raises(ValueError, match="no_saved_payment_method"):
        await _charge(real_db, stripe).execute(INVOICE)

    assert stripe.off_session_payment_intents == []


async def test_house_autopay_keeps_the_platform_search_and_key(real_db) -> None:
    stripe = FakeStripeGateway()
    stripe.seed_saved_card(
        academy_id=HOUSE, parent_id=PARENT, customer_id="cus_house", payment_method_id="pm_house"
    )
    # Even a stored record on some connected account must not divert the house.
    await real_db["parent_billing_customers"].insert_one(
        {
            "academy_id": HOUSE,
            "parent_id": PARENT,
            "stripe_customer_id": "cus_elsewhere",
            "default_payment_method_id": "pm_elsewhere",
            "stripe_account_id": "acct_elsewhere",
            "created_at": NOW,
        }
    )
    await _seed_invoice(real_db, HOUSE)

    with tenant_scope(HOUSE):
        result = await _charge(real_db, stripe, settings=_HouseSettings()).execute(INVOICE)

    assert result.success is True
    pi = stripe.off_session_payment_intents[-1]
    assert pi["stripe_account"] is None
    assert (pi["customer_id"], pi["payment_method_id"]) == ("cus_house", "pm_house")
    assert pi["idempotency_key"] == f"autopay:{INVOICE}:2026-09:10000"
    assert pi["application_fee_amount"] is None


async def test_customer_record_account_moves_only_with_its_ids(real_db) -> None:
    customers = MongoParentBillingCustomerRepository(real_db)
    with tenant_scope(ACAD):
        await customers.set_default_payment_method(
            parent_id=PARENT,
            stripe_customer_id="cus_on_acct",
            stripe_payment_method_id="pm_on_acct",
            payment_method_type="card",
            stripe_mandate_id=None,
            setup_intent_id="seti_on_acct",
            checkout_session_id="cs_on_acct",
            completed_at=NOW,
            payment_method_label="Visa",
            payment_method_last4="4242",
            stripe_account_id=ACCT,
        )
        await customers.promote_payment_method_to_default(
            parent_id=PARENT,
            stripe_payment_method_id="pm_on_acct",
            payment_method_type="card",
            stripe_mandate_id=None,
            payment_method_label="Visa",
            payment_method_last4="4242",
            stripe_account_id=ACCT,
        )
        assert await customers.get_saved_payment_method(
            parent_id=PARENT, stripe_account_id=ACCT
        ) == ("cus_on_acct", "pm_on_acct")
        # Asking for any other account (the platform included) finds nothing.
        assert (
            await customers.get_saved_payment_method(parent_id=PARENT, stripe_account_id=None)
            is None
        )
        assert (
            await customers.get_saved_payment_method(
                parent_id=PARENT, stripe_account_id="acct_other"
            )
            is None
        )
        # Promoting a card for another account never touches this record.
        await customers.promote_payment_method_to_default(
            parent_id=PARENT,
            stripe_payment_method_id="pm_platform",
            payment_method_type="card",
            stripe_mandate_id=None,
        )
        doc = await customers.get_academy_customer(parent_id=PARENT)
        assert doc is not None and doc["default_payment_method_id"] == "pm_on_acct"

        # A platform customer replaces the record: the account's cards go with it.
        await customers.set_stripe_customer_id(parent_id=PARENT, stripe_customer_id="cus_plat")
        doc = await customers.get_academy_customer(parent_id=PARENT)
        assert doc is not None
        assert doc["stripe_customer_id"] == "cus_plat"
        assert "stripe_account_id" not in doc
        for field in (
            "default_payment_method_id",
            "primary_payment_method_id",
            "payment_method_label",
            "payment_method_last4",
            "autopay_payment_methods",
        ):
            assert field not in doc, field
        assert await customers.has_saved_card(parent_id=PARENT) is False
        assert (
            await customers.get_saved_payment_method(parent_id=PARENT, stripe_account_id=None)
            is None
        )

        # Same account again: the customer write keeps an existing card.
        await customers.set_default_payment_method(
            parent_id=PARENT,
            stripe_customer_id="cus_plat",
            stripe_payment_method_id="pm_plat",
            payment_method_type="card",
            stripe_mandate_id=None,
            setup_intent_id="seti_plat",
            checkout_session_id=None,
            completed_at=NOW,
        )
        await customers.set_stripe_customer_id(parent_id=PARENT, stripe_customer_id="cus_plat")
        assert await customers.get_saved_payment_method(
            parent_id=PARENT, stripe_account_id=None
        ) == ("cus_plat", "pm_plat")
        doc = await customers.get_academy_customer(parent_id=PARENT)
        assert doc is not None and "stripe_account_id" not in doc


async def test_validator_accepts_the_account_and_rejects_a_non_string(real_db) -> None:
    collection = real_db["parent_billing_customers"]
    await collection.insert_one(
        {"academy_id": ACAD, "parent_id": "p-ok", "stripe_account_id": ACCT, "created_at": NOW}
    )
    with pytest.raises(WriteError):
        await collection.insert_one(
            {"academy_id": ACAD, "parent_id": "p-bad", "stripe_account_id": 42, "created_at": NOW}
        )
