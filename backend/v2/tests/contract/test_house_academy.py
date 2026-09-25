"""House academy: only it may charge on the platform Stripe account.

``allow_platform_charge_fallback`` is derived on read from the deploy-time
``HOUSE_ACADEMY_ID``; the stored per-academy flag is ignored once that is set,
and the app never writes the flag back.
"""

from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.connect_onboarding import (
    StartConnectOnboarding,
)
from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.domain.errors import HouseAcademyUsesPlatformAccount
from backend.v2.contexts.billing.infrastructure import house_academy
from backend.v2.contexts.billing.infrastructure.fake_stripe_gateway import FakeStripeGateway
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.contexts.billing.infrastructure.mongo_connected_account_repo import (
    MongoConnectedAccountRepository,
)
from backend.v2.shared.tenancy import tenant_scope


@pytest.fixture(autouse=True)
def _reset_house_academy():
    house_academy.configure_house_academy(None)
    yield
    house_academy.configure_house_academy(None)


async def _store_flag(db, academy_id: str, value: bool) -> None:
    # Simulates a legacy doc written before the flag became derived.
    await db["billing_settings"].update_one(
        {"academy_id": academy_id},
        {"$set": {"allow_platform_charge_fallback": value}},
        upsert=True,
    )


def test_policy_unconfigured_uses_stored_flag() -> None:
    assert house_academy.platform_charges_allowed("acad_a", True) is True
    assert house_academy.platform_charges_allowed("acad_a", False) is False


def test_policy_configured_ignores_stored_flag() -> None:
    house_academy.configure_house_academy("acad_house")

    assert house_academy.platform_charges_allowed("acad_house", False) is True
    assert house_academy.platform_charges_allowed("acad_other", True) is False


def test_blank_configuration_means_unconfigured() -> None:
    house_academy.configure_house_academy("   ")

    assert house_academy.house_academy_id() is None
    assert house_academy.platform_charges_allowed("acad_a", True) is True


async def test_unconfigured_repo_reads_stored_flag(db, acad) -> None:
    await _store_flag(db, acad, True)

    assert (await MongoBillingSettingsRepository(db).get()).allow_platform_charge_fallback


async def test_house_academy_charges_on_platform_even_without_a_settings_doc(db, acad) -> None:
    house_academy.configure_house_academy(acad)

    settings = await MongoBillingSettingsRepository(db).get()

    assert settings.allow_platform_charge_fallback is True


async def test_house_academy_charges_on_platform_even_if_stored_flag_is_off(db, acad) -> None:
    house_academy.configure_house_academy(acad)
    await _store_flag(db, acad, False)

    assert (await MongoBillingSettingsRepository(db).get()).allow_platform_charge_fallback


async def test_other_academy_cannot_charge_on_platform_even_if_stored_flag_is_on(
    db, acad, other_acad
) -> None:
    house_academy.configure_house_academy(other_acad)
    await _store_flag(db, acad, True)

    with tenant_scope(acad):
        settings = await MongoBillingSettingsRepository(db).get()

    assert settings.allow_platform_charge_fallback is False


async def test_upsert_never_writes_the_derived_flag(db, acad) -> None:
    house_academy.configure_house_academy(acad)
    repo = MongoBillingSettingsRepository(db)

    # Read-modify-write, as every admin settings save does.
    current = await repo.get()
    await repo.upsert(current.model_copy(update={"ach_discount_percent": 1.0}))

    raw = await db["billing_settings"].find_one({"academy_id": acad})
    assert raw is not None
    assert raw["ach_discount_percent"] == 1.0
    assert "allow_platform_charge_fallback" not in raw


async def test_upsert_leaves_a_legacy_stored_flag_untouched(db, acad) -> None:
    await _store_flag(db, acad, True)
    repo = MongoBillingSettingsRepository(db)

    await repo.upsert(BillingSettings(academy_id=acad, allow_platform_charge_fallback=False))

    raw = await db["billing_settings"].find_one({"academy_id": acad})
    assert raw is not None
    assert raw["allow_platform_charge_fallback"] is True


def _onboarding(
    stripe: FakeStripeGateway, db, academy_id: str, house: str | None
) -> StartConnectOnboarding:
    return StartConnectOnboarding(
        stripe=stripe,
        connected_accounts=MongoConnectedAccountRepository(db),
        allowed_redirect_origins=("https://app.test",),
        academy_id=academy_id,
        house_academy_id=house,
    )


async def _start(use_case: StartConnectOnboarding, academy_id: str) -> dict[str, str]:
    return await use_case.start(
        academy_id=academy_id,
        refresh_url="https://app.test/admin/settings?panel=gateway&stripe=refresh",
        return_url="https://app.test/admin/settings?panel=gateway&stripe=connected",
    )


async def test_house_academy_cannot_start_connect_onboarding(db, acad) -> None:
    stripe = FakeStripeGateway()

    with pytest.raises(HouseAcademyUsesPlatformAccount):
        await _start(_onboarding(stripe, db, acad, house=acad), acad)

    assert stripe.connected_accounts == []
    with tenant_scope(acad):
        assert await MongoConnectedAccountRepository(db).get_for_academy() is None


async def test_other_academy_can_still_start_connect_onboarding(db, acad, other_acad) -> None:
    stripe = FakeStripeGateway()

    with tenant_scope(acad):
        result = await _start(_onboarding(stripe, db, acad, house=other_acad), acad)

    assert result["onboarding_url"]
    assert len(stripe.connected_accounts) == 1
