"""Referral routes on a real ``mongod`` (L9 C2): the parent's card, the admin
list and the email preview, through the real routers and composition."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.composition.referrals import compose_referrals
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.interfaces.parent.router import router as parent_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers

pytestmark = pytest.mark.asyncio

PROGRAM = {
    "enabled": True,
    "referrer_credit_cents": 2_500,
    "referred_credit_cents": 1_000,
    "hold_days": 7,
    "max_rewards_per_referrer_per_year": 10,
    "credit_expiry_days": None,
    "trigger": "first_paid_invoice",
    "effective_from": datetime(2026, 1, 1, tzinfo=UTC),
}


def _client(db: Any, *, user_id: str, roles: tuple[str, ...]) -> httpx.AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    app.include_router(parent_router, prefix="/api/v2")
    claims = AuthClaims(
        user_id=user_id, email=f"{user_id}@example.com", academy_id="test-academy", roles=roles
    )  # type: ignore[arg-type]
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.state.referrals = compose_referrals(db, frontend_url="https://app.courtmastr.test")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.fixture
async def parent(real_db, acad) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(real_db, user_id="u-parent", roles=("parent",)) as client:
        yield client


@pytest.fixture
async def admin(real_db, acad) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(real_db, user_id="u-admin", roles=("admin",)) as client:
        yield client


async def _switch(db: Any, **program: Any) -> None:
    await db["billing_settings"].update_one(
        {"academy_id": "test-academy"},
        {"$set": {"referral_program": {**PROGRAM, **program}}},
        upsert=True,
    )


async def test_parent_card_is_off_until_the_programme_is_on(parent, real_db) -> None:
    await real_db["academies"].insert_one(
        {"academy_id": "test-academy", "slug": "acme", "display_name": "Acme"}
    )
    off = (await parent.get("/api/v2/parent/referral")).json()
    assert off == {
        "enabled": False,
        "referral_code": None,
        "share_url": None,
        "rewards_earned": 0,
        "referrer_credit_cents": None,
        "referred_credit_cents": None,
    }
    assert await real_db["referral_codes"].count_documents({}) == 0

    await _switch(real_db)
    first = (await parent.get("/api/v2/parent/referral")).json()
    again = (await parent.get("/api/v2/parent/referral")).json()
    assert first["enabled"] is True and first["referral_code"]
    assert again["referral_code"] == first["referral_code"]
    assert first["rewards_earned"] == 0 and first["referrer_credit_cents"] == 2_500
    # Built on the server from the academy's slug, never the browser's address.
    assert first["share_url"] == f"https://acme.courtmastr.test/?ref={first['referral_code']}"


async def test_admin_lists_referrals_with_state_and_names(admin, real_db) -> None:
    await real_db["users"].insert_many(
        [
            {"user_id": "u-ref", "display_name": "Riley Ref"},
            {"user_id": "u-new", "display_name": "Nova New"},
        ]
    )
    now = datetime(2026, 12, 1, tzinfo=UTC)
    await real_db["referrals"].insert_one(
        {
            "academy_id": "test-academy",
            "referral_id": "r1",
            "referral_code": "QZ7KX4MP",
            "referrer_parent_id": "u-ref",
            "referred_parent_id": "u-new",
            "source": "contact",
            "source_id": "c1",
            "attributed_at": now,
            "competing_codes": ["AB23CD45"],
            "status": "ineligible",
            "reason": "self_referral",
            "created_at": now,
            "updated_at": now,
        }
    )
    body = (await admin.get("/api/v2/admin/billing/referrals")).json()
    [row] = body["referrals"]
    assert row["referrer_name"] == "Riley Ref" and row["referred_name"] == "Nova New"
    assert (row["status"], row["reason"]) == ("ineligible", "self_referral")
    assert (row["source"], row["competing_codes"]) == ("contact", ["AB23CD45"])
    assert row["attributed_at"].startswith("2026-12-01")


async def test_admin_email_preview_renders_and_sends_nothing(admin, real_db) -> None:
    await _switch(real_db, enabled=False)
    body = (await admin.get("/api/v2/admin/billing/referrals/email-preview")).json()
    assert [e["key"] for e in body["emails"]] == ["referral_reward", "referral_welcome"]
    assert "$25" in body["emails"][0]["html"] and "$10" in body["emails"][1]["html"]


async def test_wrong_persona_is_a_404(parent, admin) -> None:
    assert (await parent.get("/api/v2/admin/billing/referrals")).status_code == 404
    assert (await admin.get("/api/v2/parent/referral")).status_code == 404


async def test_only_the_owner_approves_an_inquiry_referral(admin, real_db) -> None:
    await _switch(real_db)
    now = datetime(2026, 12, 1, tzinfo=UTC)
    await real_db["referrals"].insert_one(
        {
            "academy_id": "test-academy",
            "referral_id": "r-review",
            "referral_code": "QZ7KX4MP",
            "referrer_parent_id": "u-ref",
            "referred_parent_id": "u-new",
            "source": "contact",
            "source_id": "c1",
            "attributed_at": now,
            "status": "needs_review",
            "created_at": now,
            "updated_at": now,
        }
    )
    url = "/api/v2/admin/billing/referrals/r-review/approve"
    assert (await admin.post(url)).status_code == 404  # admin, not owner
    async with _client(real_db, user_id="u-owner", roles=("admin", "owner")) as owner:
        approved = await owner.post(url)
        assert approved.status_code == 200
        assert approved.json()["status"] == "pending"  # no paid invoice yet
        assert (await owner.post(url)).status_code == 409  # no longer awaiting review
    row = await real_db["referrals"].find_one({"referral_id": "r-review"})
    assert row["reviewed_by"] == "u-owner"
