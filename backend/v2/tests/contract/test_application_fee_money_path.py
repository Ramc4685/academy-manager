"""Per-academy platform application fee on a real MongoDB (roadmap L9b).

Pins, on a real ``mongod`` with every migration applied:

* an academy with no setting (every academy today) sends
  ``application_fee_amount=0`` on its destination charges: no behaviour change;
* a fee a PLATFORM admin sets (through the composed platform use case, the
  same object the platform BFF route calls) is sent on the next charge,
  computed from the charge amount, floored;
* the fee is per academy: setting one academy's fee leaves another's at 0;
* the academy-side settings write (the admin invoice-schedule panel's
  read-modify-write) can never overwrite the platform's fee, even from a
  stale read;
* an unknown academy is refused, and nothing is written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.platform_application_fee import compose_platform_application_fee
from backend.v2.contexts.billing.application.use_cases.application_fee import (
    SetApplicationFeeCommand,
)
from backend.v2.contexts.billing.application.use_cases.billing_settings_admin import (
    SetInvoiceScheduleCommand,
    SetInvoiceScheduleSettings,
)
from backend.v2.contexts.billing.application.use_cases.start_checkout import (
    StartCheckout,
    StartCheckoutCommand,
)
from backend.v2.contexts.billing.domain.connected_account import ConnectedAccount
from backend.v2.contexts.billing.domain.errors import ApplicationFeeAcademyNotFound
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-fee-a"
OTHER = "acad-fee-b"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


async def _seed_academy(db: Any, academy_id: str) -> None:
    await db["academies"].insert_one(
        {
            "_id": academy_id,
            "academy_id": academy_id,
            "slug": academy_id,
            "display_name": f"Synthetic {academy_id}",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
        }
    )
    with tenant_scope(academy_id):
        await MongoConnectedAccountRepository(db).upsert(
            ConnectedAccount(
                academy_id=academy_id,
                stripe_account_id=f"acct_{academy_id}",
                status="active",
                charges_enabled=True,
                payouts_enabled=True,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def _start_checkout(db: Any, stripe: FakeStripeGateway, academy_id: str) -> StartCheckout:
    return StartCheckout(
        payment_repo=MongoPaymentRepository(db),
        stripe=stripe,
        academy_id=academy_id,
        connected_accounts=MongoConnectedAccountRepository(db),
        settings=MongoBillingSettingsRepository(db),
    )


async def _checkout(db: Any, stripe: FakeStripeGateway, academy_id: str, amount: int) -> None:
    with tenant_scope(academy_id):
        await _start_checkout(db, stripe, academy_id).execute(
            StartCheckoutCommand(
                parent_id=f"parent-{academy_id}",
                session_id=f"sess-{academy_id}",
                amount_cents=amount,
                success_url="https://app.test/ok",
                cancel_url="https://app.test/cancel",
            )
        )


async def test_default_fee_is_zero_and_a_platform_set_fee_is_sent(real_db) -> None:
    await _seed_academy(real_db, ACAD)
    await _seed_academy(real_db, OTHER)
    stripe = FakeStripeGateway()

    # Default: no settings document at all -> application_fee_amount 0.
    await _checkout(real_db, stripe, ACAD, 15_000)
    assert stripe.checkouts[-1]["stripe_account"] == f"acct_{ACAD}"
    assert stripe.checkouts[-1]["application_fee_amount"] == 0

    # A platform admin sets 2.5% for ACAD only (the platform route's use case).
    platform = compose_platform_application_fee(real_db)
    result = await platform.set.execute(
        SetApplicationFeeCommand(
            academy_id=ACAD, application_fee_bps=250, actor_id="platform-admin", reason="contract"
        )
    )
    assert result.application_fee_bps == 250
    assert (await platform.get.execute(ACAD)).application_fee_bps == 250

    await _checkout(real_db, stripe, ACAD, 15_000)
    assert stripe.checkouts[-1]["application_fee_amount"] == 375

    # Floor rounding: 2.5% of $41.00 is 102.5 cents -> 102.
    await _checkout(real_db, stripe, ACAD, 4_100)
    assert stripe.checkouts[-1]["application_fee_amount"] == 102

    # The other academy is untouched.
    await _checkout(real_db, stripe, OTHER, 15_000)
    assert stripe.checkouts[-1]["stripe_account"] == f"acct_{OTHER}"
    assert stripe.checkouts[-1]["application_fee_amount"] == 0
    assert (await platform.get.execute(OTHER)).application_fee_bps == 0

    # Audited, in the academy's own billing audit trail.
    audit = await real_db["billing_audit_log"].find({"academy_id": ACAD}).to_list(None)
    assert [(a["action"], a["before"], a["after"]) for a in audit] == [
        ("application_fee_changed", {"application_fee_bps": 0}, {"application_fee_bps": 250})
    ]
    assert await real_db["billing_audit_log"].count_documents({"academy_id": OTHER}) == 0


async def test_academy_settings_write_never_overwrites_the_platform_fee(real_db) -> None:
    await _seed_academy(real_db, ACAD)
    repo = MongoBillingSettingsRepository(real_db)

    # The academy admin reads settings BEFORE the platform sets the fee...
    with tenant_scope(ACAD):
        stale = await repo.get()
    assert stale.application_fee_bps == 0

    await compose_platform_application_fee(real_db).set.execute(
        SetApplicationFeeCommand(academy_id=ACAD, application_fee_bps=300, actor_id="p")
    )

    with tenant_scope(ACAD):
        # ...then writes a model carrying the stale 0 (and one forging 1000).
        await repo.upsert(stale.model_copy(update={"billing_day": 5}))
        await repo.upsert(stale.model_copy(update={"application_fee_bps": 1_000}))
        # And the real admin panel use case, end to end.
        await SetInvoiceScheduleSettings(settings=repo).execute(
            SetInvoiceScheduleCommand(billing_day=9, invoice_due_days=10, actor_id="admin-1")
        )
        current = await repo.get()

    assert current.application_fee_bps == 300
    assert current.billing_day == 9
    doc = await real_db["billing_settings"].find_one({"academy_id": ACAD})
    assert doc is not None and doc["application_fee_bps"] == 300
    assert await real_db["billing_settings"].count_documents({"academy_id": ACAD}) == 1


async def test_setting_a_fee_for_an_unknown_academy_is_refused(real_db) -> None:
    platform = compose_platform_application_fee(real_db)

    with pytest.raises(ApplicationFeeAcademyNotFound):
        await platform.set.execute(
            SetApplicationFeeCommand(
                academy_id="acad-missing", application_fee_bps=100, actor_id="p"
            )
        )

    assert await real_db["billing_settings"].count_documents({}) == 0
    assert await real_db["billing_audit_log"].count_documents({}) == 0
