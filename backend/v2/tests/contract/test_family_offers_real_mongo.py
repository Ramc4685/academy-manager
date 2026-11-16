"""Settings -> Billing rules -> Family offers on a real ``mongod`` (L9 C1).

The real route, use case, settings repository and audit log, driven through
httpx's ASGI transport in the test's own event loop (so Motor and the tenant
ContextVar both work). Proves: every field is stored and read back as sent,
each bound returns a 422 naming the field, enabling the sibling discount needs
every field, switching referrals on needs its fields and stamps
``effective_from`` server side (never from the request), each change leaves one
audit row with the whole block before and after, other settings writes cannot
clobber the blocks, and a non-owner admin gets 404.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.composition.family_offers import compose_admin_family_offers
from backend.v2.contexts.billing.infrastructure.mongo_billing_settings_repo import (
    MongoBillingSettingsRepository,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

pytestmark = pytest.mark.asyncio

ROUTE = "/api/v2/admin/billing/family-offers"

SIBLING_ON = {
    "enabled": True,
    "percent_bps": 1_000,
    "full_price_child": "highest_tuition",
    "applies_to": "all_classes",
}
REFERRAL_FULL = {
    "referrer_credit_cents": 2_500,
    "referred_credit_cents": 2_500,
    "hold_days": 7,
    "max_rewards_per_referrer_per_year": 10,
    "credit_expiry_days": None,
    "trigger": "first_paid_invoice",
}


def _app(db: Any, *, roles: tuple[str, ...]) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    claims = AuthClaims(
        user_id="u-owner", email="o@example.com", academy_id="test-academy", roles=roles
    )  # type: ignore[arg-type]
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.state.admin_family_offers = compose_admin_family_offers(db)
    return app


@pytest.fixture
async def owner(real_db, acad) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=_app(real_db, roles=("admin", "owner")))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client


async def _stored(db: Any) -> dict[str, Any]:
    doc = await db["billing_settings"].find_one({"academy_id": "test-academy"})
    assert doc is not None
    return doc


async def test_a_fresh_academy_has_both_offers_off_and_unset(owner) -> None:
    body = (await owner.get(ROUTE)).json()
    assert body["sibling_discount"] == {
        "enabled": False,
        "percent_bps": None,
        "full_price_child": None,
        "applies_to": None,
    }
    assert body["referral_program"]["enabled"] is False
    assert body["referral_program"]["referrer_credit_cents"] is None
    assert "effective_from" not in body["referral_program"]


@pytest.mark.parametrize(
    ("block", "field", "value"),
    [
        ("sibling_discount", "percent_bps", 1_250),
        ("sibling_discount", "full_price_child", "first_enrolled"),
        ("sibling_discount", "applies_to", "one_class_per_child"),
        ("sibling_discount", "enabled", True),
        ("referral_program", "referrer_credit_cents", 4_000),
        ("referral_program", "referred_credit_cents", 1_500),
        ("referral_program", "hold_days", 0),
        ("referral_program", "max_rewards_per_referrer_per_year", 3),
        ("referral_program", "credit_expiry_days", 365),
        ("referral_program", "trigger", "first_paid_monthly_invoice"),
    ],
)
async def test_each_field_reads_back_the_stored_value(
    owner, real_db, block: str, field: str, value: Any
) -> None:
    seed = SIBLING_ON if block == "sibling_discount" else REFERRAL_FULL
    patch = {**seed, field: value}
    if field != "enabled":
        patch.pop("enabled", None)
    response = await owner.put(ROUTE, json={block: patch})
    assert response.status_code == 200, response.text
    assert response.json()[block][field] == value
    assert (await _stored(real_db))[block][field] == value
    assert (await owner.get(ROUTE)).json()[block][field] == value
    settings = await MongoBillingSettingsRepository(real_db).get()
    assert getattr(getattr(settings, block), field) == value


@pytest.mark.parametrize(
    ("block", "field", "value"),
    [
        ("referral_program", "referrer_credit_cents", 0),
        ("referral_program", "referrer_credit_cents", 50_001),
        ("referral_program", "referred_credit_cents", 0),
        ("referral_program", "referred_credit_cents", 50_001),
        ("referral_program", "hold_days", -1),
        ("referral_program", "hold_days", 61),
        ("referral_program", "max_rewards_per_referrer_per_year", 0),
        ("referral_program", "max_rewards_per_referrer_per_year", 101),
        ("referral_program", "credit_expiry_days", 29),
        ("referral_program", "credit_expiry_days", 1_096),
        ("sibling_discount", "percent_bps", 0),
        ("sibling_discount", "percent_bps", 10_001),
    ],
)
async def test_each_bound_is_a_422_naming_the_field(
    owner, real_db, block: str, field: str, value: int
) -> None:
    response = await owner.put(ROUTE, json={block: {field: value}})
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["field"] == f"{block}.{field}"
    assert await real_db["billing_settings"].count_documents({}) == 0
    assert await real_db["billing_audit_log"].count_documents({}) == 0


async def test_the_bounds_themselves_are_accepted(owner) -> None:
    for patch in (
        {"referrer_credit_cents": 1, "hold_days": 0, "credit_expiry_days": 30},
        {"referrer_credit_cents": 50_000, "hold_days": 60, "credit_expiry_days": 1_095},
        {"max_rewards_per_referrer_per_year": 1},
        {"max_rewards_per_referrer_per_year": 100},
    ):
        response = await owner.put(ROUTE, json={"referral_program": patch})
        assert response.status_code == 200, response.text
    for bps in (1, 10_000):
        response = await owner.put(ROUTE, json={"sibling_discount": {"percent_bps": bps}})
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("missing", ["percent_bps", "full_price_child", "applies_to"])
async def test_switching_the_sibling_discount_on_needs_every_field(owner, missing: str) -> None:
    patch = {**SIBLING_ON}
    patch.pop(missing)
    response = await owner.put(ROUTE, json={"sibling_discount": patch})
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == f"sibling_discount.{missing}"


@pytest.mark.parametrize(
    "missing",
    ["referrer_credit_cents", "hold_days", "max_rewards_per_referrer_per_year", "trigger"],
)
async def test_switching_referrals_on_needs_every_required_field(
    owner, real_db, missing: str
) -> None:
    patch = {**REFERRAL_FULL, "enabled": True}
    patch.pop(missing)
    response = await owner.put(ROUTE, json={"referral_program": patch})
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == f"referral_program.{missing}"
    assert await real_db["billing_settings"].count_documents({}) == 0


async def test_switching_referrals_on_stamps_effective_from_once(owner, real_db) -> None:
    stamp = await owner.put(
        ROUTE, json={"referral_program": {"effective_from": "2020-01-01T00:00:00Z"}}
    )
    assert stamp.status_code == 422

    # Stored switched off: never stamped.
    saved = await owner.put(ROUTE, json={"referral_program": REFERRAL_FULL})
    assert saved.status_code == 200, saved.text
    stored = (await _stored(real_db))["referral_program"]
    assert stored["enabled"] is False
    assert stored.get("effective_from") is None

    # The new family's credit is optional.
    on = await owner.put(
        ROUTE,
        json={"referral_program": {"enabled": True, "referred_credit_cents": None}},
    )
    assert on.status_code == 200, on.text
    first = (await _stored(real_db))["referral_program"]["effective_from"]
    assert first is not None

    # A later edit while on keeps the stamp; off and on again restamps.
    await owner.put(ROUTE, json={"referral_program": {"hold_days": 3}})
    assert (await _stored(real_db))["referral_program"]["effective_from"] == first
    await owner.put(ROUTE, json={"referral_program": {"enabled": False}})
    await owner.put(ROUTE, json={"referral_program": {"enabled": True}})
    assert (await _stored(real_db))["referral_program"]["effective_from"] >= first


async def test_each_change_leaves_one_audit_row_with_the_whole_block(owner, real_db) -> None:
    await owner.put(ROUTE, json={"sibling_discount": SIBLING_ON, "reason": "spring offer"})
    await owner.put(ROUTE, json={"sibling_discount": SIBLING_ON})  # no change, no row
    await owner.put(ROUTE, json={"referral_program": {"hold_days": 14}})

    rows = [
        row
        async for row in real_db["billing_audit_log"].find(
            {"academy_id": "test-academy"}, sort=[("at", 1)]
        )
    ]
    assert [row["action"] for row in rows] == [
        "sibling_discount_changed",
        "referral_program_changed",
    ]
    sibling_row, referral_row = rows
    assert sibling_row["actor_id"] == "u-owner"
    assert sibling_row["reason"] == "spring offer"
    assert sibling_row["before"] == {
        "enabled": False,
        "percent_bps": None,
        "full_price_child": None,
        "applies_to": None,
    }
    assert sibling_row["after"] == SIBLING_ON
    assert referral_row["before"]["hold_days"] is None
    assert referral_row["after"]["hold_days"] == 14
    assert set(referral_row["after"]) == set(REFERRAL_FULL) | {"enabled", "effective_from"}


async def test_another_settings_save_cannot_put_back_a_stale_block(owner, real_db) -> None:
    repo = MongoBillingSettingsRepository(real_db)
    stale = await repo.get()  # read before the owner switches the offer on
    await owner.put(ROUTE, json={"sibling_discount": SIBLING_ON})
    await repo.upsert(stale.model_copy(update={"ach_discount_percent": 1.0}))

    assert (await _stored(real_db))["sibling_discount"] == SIBLING_ON


async def test_a_non_owner_admin_gets_404_on_the_write_but_can_read(real_db, acad) -> None:
    transport = httpx.ASGITransport(app=_app(real_db, roles=("admin",)))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as admin:
        write = await admin.put(ROUTE, json={"sibling_discount": SIBLING_ON})
        read = await admin.get(ROUTE)
    assert write.status_code == 404
    assert read.status_code == 200
    assert await real_db["billing_settings"].count_documents({}) == 0
    assert await real_db["billing_audit_log"].count_documents({}) == 0


async def test_a_hand_edited_incomplete_block_breaks_no_reader_and_can_be_repaired(
    owner, real_db
) -> None:
    """Only a hand edit can store a block switched on without its values; every
    settings reader must survive it and the owner must be able to fix it."""
    await real_db["billing_settings"].insert_one(
        {"academy_id": "test-academy", "sibling_discount": {"enabled": True, "percent_bps": 1_000}}
    )

    settings = await MongoBillingSettingsRepository(real_db).get()
    assert settings.sibling_discount.enabled is True
    assert settings.sibling_discount.full_price_child is None
    shown = await owner.get(ROUTE)
    assert shown.status_code == 200, shown.text
    assert shown.json()["sibling_discount"]["percent_bps"] == 1_000

    repaired = await owner.put(ROUTE, json={"sibling_discount": SIBLING_ON})
    assert repaired.status_code == 200, repaired.text
    assert (await _stored(real_db))["sibling_discount"] == SIBLING_ON
