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

from backend.v2.composition.admin_platform_fee import compose_admin_platform_fee
from backend.v2.composition.platform_application_fee import (
    compose_default_application_fee_assigner,
    compose_platform_application_fee,
)
from backend.v2.composition.platform_billing_identity import compose_invoice_prefix_assigner
from backend.v2.contexts.billing.application.use_cases.application_fee import (
    AgreementAcceptance,
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
from backend.v2.contexts.billing.domain.billing_settings import (
    APPLICATION_FEE_AGREEMENT_TEXT,
    APPLICATION_FEE_AGREEMENT_VERSION,
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
from backend.v2.contexts.platform.application.use_cases.tenant_lifecycle import (
    CreateTenantCommand,
    TenantLifecycleService,
)
from backend.v2.contexts.platform.infrastructure.mongo_tenant_lifecycle_repo import (
    MongoTenantLifecycleRepository,
)
from backend.v2.shared.tenancy.context import tenant_scope

ACAD = "acad-fee-a"
OTHER = "acad-fee-b"
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
_NO_AGREEMENT = {
    "application_fee_agreement_version": None,
    "application_fee_accepted_at": None,
    "application_fee_accepted_by": None,
}


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
                fees_collector="stripe",
                losses_collector="stripe",
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
        (
            "application_fee_changed",
            {**_NO_AGREEMENT, "application_fee_bps": 0},
            {**_NO_AGREEMENT, "application_fee_bps": 250},
        )
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


async def test_two_academies_at_two_rates_each_send_exactly_their_own_fee(real_db) -> None:
    """Phase 2 A1 regression: A at 100 bps and B at 150 bps, one charge each,
    and the gateway sees each academy's own ``application_fee_amount``."""
    await _seed_academy(real_db, ACAD)
    await _seed_academy(real_db, OTHER)
    platform = compose_platform_application_fee(real_db)
    for academy_id, bps in ((ACAD, 100), (OTHER, 150)):
        await platform.set.execute(
            SetApplicationFeeCommand(academy_id=academy_id, application_fee_bps=bps, actor_id="p")
        )
    stripe = FakeStripeGateway()

    await _checkout(real_db, stripe, ACAD, 20_000)
    await _checkout(real_db, stripe, OTHER, 20_000)

    by_account = {c["stripe_account"]: c["application_fee_amount"] for c in stripe.checkouts}
    assert by_account == {f"acct_{ACAD}": 200, f"acct_{OTHER}": 300}


async def test_agreement_acceptance_is_stored_with_the_fee_and_audited(real_db) -> None:
    await _seed_academy(real_db, ACAD)
    platform = compose_platform_application_fee(real_db)

    result = await platform.set.execute(
        SetApplicationFeeCommand(
            academy_id=ACAD,
            application_fee_bps=100,
            actor_id="platform-admin",
            agreement=AgreementAcceptance(
                version=APPLICATION_FEE_AGREEMENT_VERSION, accepted_by="Jane Owner"
            ),
        )
    )

    assert (result.agreement_version, result.accepted_by) == (
        APPLICATION_FEE_AGREEMENT_VERSION,
        "Jane Owner",
    )
    doc = await real_db["billing_settings"].find_one({"academy_id": ACAD})
    assert doc is not None
    assert doc["application_fee_bps"] == 100
    assert doc["application_fee_agreement_version"] == APPLICATION_FEE_AGREEMENT_VERSION
    assert doc["application_fee_accepted_by"] == "Jane Owner"
    assert doc["application_fee_accepted_at"] is not None
    read = await platform.get.execute(ACAD)
    assert (read.accepted_by, read.agreement_text) == ("Jane Owner", APPLICATION_FEE_AGREEMENT_TEXT)
    audit = await real_db["billing_audit_log"].find_one({"academy_id": ACAD})
    assert audit is not None
    assert audit["after"]["application_fee_accepted_by"] == "Jane Owner"
    assert audit["before"]["application_fee_accepted_by"] is None

    # The academy's own read-only view (``GET /admin/billing/platform-fee``).
    with tenant_scope(ACAD):
        mine = await compose_admin_platform_fee(real_db).execute()
    assert (mine.academy_id, mine.application_fee_bps, mine.accepted_by) == (
        ACAD,
        100,
        "Jane Owner",
    )
    # Tenant isolation: another academy's view carries nothing of ACAD's.
    await _seed_academy(real_db, OTHER)
    with tenant_scope(OTHER):
        theirs = await compose_admin_platform_fee(real_db).execute()
    assert (theirs.academy_id, theirs.application_fee_bps, theirs.accepted_by) == (OTHER, 0, None)

    # The academy-side settings write cannot touch the acceptance either.
    repo = MongoBillingSettingsRepository(real_db)
    with tenant_scope(ACAD):
        current = await repo.get()
        await repo.upsert(current.model_copy(update={"application_fee_accepted_by": "Mallory"}))
        assert (await repo.get()).application_fee_accepted_by == "Jane Owner"


async def test_a_newly_created_tenant_starts_at_100_bps_with_no_acceptance(real_db) -> None:
    """``TenantLifecycleService.create_tenant`` with the real assigners: the new
    academy's billing settings carry 100 bps and nothing accepted yet, while an
    academy created before this slice (no setting) stays at 0."""
    service = TenantLifecycleService(
        tenants=MongoTenantLifecycleRepository(real_db),
        invoice_prefix_assigner=compose_invoice_prefix_assigner(real_db),
        default_application_fee_assigner=compose_default_application_fee_assigner(real_db),
    )

    tenant = await service.create_tenant(
        CreateTenantCommand(
            display_name="Ace Badminton",
            slug="ace-badminton",
            primary_domain="ace.example.test",
            plan_code="starter",
            actor_user_id="platform-admin",
        )
    )

    doc = await real_db["billing_settings"].find_one({"academy_id": tenant.academy_id})
    assert doc is not None
    assert doc["application_fee_bps"] == 100
    assert doc["invoice_number_prefix"]  # the prefix assigner still ran
    assert doc.get("application_fee_accepted_by") is None
    platform = compose_platform_application_fee(real_db)
    read = await platform.get.execute(tenant.academy_id)
    assert (read.application_fee_bps, read.agreement_version) == (100, None)
    audit = await real_db["billing_audit_log"].find_one({"academy_id": tenant.academy_id})
    assert audit is not None and audit["reason"] == "default for new academies"

    # Pre-existing academies are untouched: no setting still means 0 sent.
    await _seed_academy(real_db, OTHER)
    stripe = FakeStripeGateway()
    await _checkout(real_db, stripe, OTHER, 10_000)
    assert stripe.checkouts[-1]["application_fee_amount"] == 0
