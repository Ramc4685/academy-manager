from __future__ import annotations

from backend.v2.contexts.billing.domain.billing_settings import BillingSettings
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)


async def test_get_returns_fail_safe_defaults_when_no_doc(db, acad) -> None:
    repo = MongoBillingSettingsRepository(db)

    settings = await repo.get()

    assert settings == BillingSettings.default(acad)


async def test_upsert_then_get_round_trip(db, acad) -> None:
    repo = MongoBillingSettingsRepository(db)
    settings = BillingSettings(
        academy_id=acad,
        ach_discount_enabled=True,
        ach_discount_percent=2.0,
        disclosure_text="ACH autopay saves 2%.",
        disclosure_version="v1",
        invoice_number_prefix="INV",
    )

    await repo.upsert(settings)
    await repo.set_invoice_number_prefix("BLNO")
    fetched = await repo.get()

    assert fetched.academy_id == acad
    assert fetched.ach_discount_enabled is True
    assert fetched.ach_discount_percent == 2.0
    assert fetched.disclosure_text == "ACH autopay saves 2%."
    assert fetched.disclosure_version == "v1"
    # The prefix is platform-only: the tenant upsert ignores the model's "INV",
    # only set_invoice_number_prefix writes it (Settings overhaul P1 PR 2).
    assert fetched.invoice_number_prefix == "BLNO"


async def test_upsert_is_idempotent_and_updates_existing_doc(db, acad) -> None:
    repo = MongoBillingSettingsRepository(db)
    await repo.upsert(BillingSettings(academy_id=acad, ach_discount_percent=1.0))
    await repo.upsert(BillingSettings(academy_id=acad, ach_discount_percent=2.0))

    fetched = await repo.get()

    assert fetched.ach_discount_percent == 2.0
    assert await repo.collection.count_documents({}) == 1


async def test_tenant_isolation_academy_cannot_read_another_academys_settings(
    db, acad, other_acad
) -> None:
    from backend.v2.shared.tenancy.context import _current as _tv

    repo = MongoBillingSettingsRepository(db)

    token = _tv.set(acad)
    try:
        await repo.upsert(BillingSettings(academy_id=acad, ach_discount_percent=5.0))
    finally:
        _tv.reset(token)

    token = _tv.set(other_acad)
    try:
        other_settings = await repo.get()
    finally:
        _tv.reset(token)

    # Fail-safe default for the other academy — no leakage of academy A's config.
    assert other_settings == BillingSettings.default(other_acad)


async def test_tenant_upsert_never_persists_or_raises_the_ach_ceiling(db, acad) -> None:
    """max_ach_discount_percent is platform-owned (Settings overhaul Phase 4 PR 13)."""
    repo = MongoBillingSettingsRepository(db)
    # A platform-side stored ceiling of 1.5 (set by hand / migration).
    await repo.collection.insert_one({"academy_id": acad, "max_ach_discount_percent": 1.5})

    forged = BillingSettings(
        academy_id=acad,
        ach_discount_enabled=True,
        ach_discount_percent=1.0,
        max_ach_discount_percent=99.0,
    )
    await repo.upsert(forged)

    fetched = await repo.get()
    assert fetched.max_ach_discount_percent == 1.5
    assert fetched.ach_discount_percent == 1.0


async def test_first_tenant_upsert_stores_no_ceiling_so_the_code_default_applies(db, acad) -> None:
    repo = MongoBillingSettingsRepository(db)
    await repo.upsert(BillingSettings(academy_id=acad, ach_discount_percent=1.0))

    raw = await repo.collection.find_one({"academy_id": acad})
    assert raw is not None and "max_ach_discount_percent" not in raw
    assert (await repo.get()).max_ach_discount_percent == 3.0
