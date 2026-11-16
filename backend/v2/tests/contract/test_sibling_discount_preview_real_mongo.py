"""The admin sibling-discount badge matches the invoice it predicts (real ``mongod``).

``GET /admin/families/{parent_id}/sibling-discount`` is a dry read of the
monthly run's own decision. Each case reads it, proves nothing was written,
runs the real generator, and checks every enrollment's badge against the
invoice's discount line; then reads again over the recorded decisions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from backend.v2.composition.family_offers import compose_admin_family_offers
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    SIBLING_DECISIONS_COLLECTION,
)
from backend.v2.interfaces.admin.router import router as admin_router
from backend.v2.shared.auth.claims import AuthClaims, get_auth_claims
from backend.v2.shared.http import register_exception_handlers
from backend.v2.tests.contract.test_sibling_discount_real_mongo import (
    NOW,
    PERIOD,
    _child,
    _enroll,
    _family,
    _lines,
    _manual,
    _offer,
    _repo,
    _session,
)

pytestmark = pytest.mark.asyncio

ROUTE = f"/api/v2/admin/families/parent-1/sibling-discount?period={PERIOD}"


@pytest.fixture
async def admin(real_db: Any, acad: str) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_router, prefix="/api/v2")
    claims = AuthClaims(
        user_id="u-admin", email="a@example.com", academy_id="test-academy", roles=("admin",)
    )
    app.dependency_overrides[get_auth_claims] = lambda: claims
    app.state.admin_family_offers = compose_admin_family_offers(real_db)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client


class _FrozenNow(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return NOW


async def _badges(client: httpx.AsyncClient) -> dict[str, Any]:
    with patch("backend.v2.composition.family_offers.datetime", _FrozenNow):
        response = await client.get(ROUTE)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _by_enrollment(body: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {row["enrollment_id"]: (row["status"], row["reason"]) for row in body["enrollments"]}


async def _invoiced_discount_sources(db: Any, acad: str, *ids: str) -> dict[str, str | None]:
    """Each enrollment's invoice discount line source, or ``None`` when undiscounted."""
    out: dict[str, str | None] = {}
    for eid in ids:
        lines = [line for line in await _lines(db, acad, eid) if line["line_type"] == "discount"]
        out[eid] = lines[0]["source_id"] if lines else None
    return out


async def _generate_and_compare(
    client: httpx.AsyncClient, db: Any, acad: str, expected: dict[str, tuple[str, str]]
) -> None:
    before = await _badges(client)
    assert _by_enrollment(before) == expected
    assert await db[SIBLING_DECISIONS_COLLECTION].count_documents({}) == 0, "the read wrote"

    await _repo(db).generate_monthly_payments(PERIOD)

    sources = await _invoiced_discount_sources(db, acad, *expected)
    for eid, (status, _reason) in expected.items():
        if status == "discounted":
            assert sources[eid] == f"sibling-auto-{PERIOD}", eid
        else:
            assert sources[eid] != f"sibling-auto-{PERIOD}", eid
    # Over the decisions the run just recorded, the badge says the same.
    assert _by_enrollment(await _badges(client)) == expected


async def test_a_multi_child_family_badge_matches_the_invoices(
    admin: httpx.AsyncClient, real_db: Any, acad: str
) -> None:
    """Ava 150 (full price), Ben 80 and Cleo 50 discounted, Ben's second class
    left full under one_class_per_child."""
    await _session(real_db, acad, "sess-top", 15_000)
    await _session(real_db, acad, "sess-lo", 8_000)
    await _session(real_db, acad, "sess-mini", 5_000)
    for sid in ("stu-a", "stu-b", "stu-c"):
        await _child(real_db, acad, sid)
    await _enroll(real_db, acad, "enr-a", "stu-a", "sess-top")
    await _enroll(real_db, acad, "enr-b", "stu-b", "sess-lo")
    await _enroll(real_db, acad, "enr-b2", "stu-b", "sess-mini")
    await _enroll(real_db, acad, "enr-c", "stu-c", "sess-mini")
    await _offer(real_db, applies_to="one_class_per_child")

    await _generate_and_compare(
        admin,
        real_db,
        acad,
        {
            "enr-a": ("full_price", "full_price_child"),
            "enr-b": ("discounted", "sibling_discount"),
            "enr-b2": ("not_eligible", "one_class_per_child"),
            "enr-c": ("discounted", "sibling_discount"),
        },
    )
    body = await _badges(admin)
    assert body["enabled"] is True and body["percent_bps"] == 1_000
    assert {row["percent_bps"] for row in body["enrollments"] if row["status"] == "discounted"} == {
        1_000
    }


async def test_a_larger_manual_discount_shows_and_wins(
    admin: httpx.AsyncClient, real_db: Any, acad: str
) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    await _manual(real_db, percent_bps=2_000)

    await _generate_and_compare(
        admin,
        real_db,
        acad,
        {
            "enr-a": ("full_price", "full_price_child"),
            "enr-b": ("not_eligible", "manual_discount_larger"),
        },
    )
    assert (await _invoiced_discount_sources(real_db, acad, "enr-b")) == {"enr-b": "disc-manual"}


async def test_the_setting_off_reads_off_and_nothing_is_discounted(
    admin: httpx.AsyncClient, real_db: Any, acad: str
) -> None:
    await _family(real_db, acad)

    await _generate_and_compare(
        admin,
        real_db,
        acad,
        {"enr-a": ("off", "setting_off"), "enr-b": ("off", "setting_off")},
    )
    body = await _badges(admin)
    assert body["enabled"] is False and body["percent_bps"] is None
    assert await real_db[SIBLING_DECISIONS_COLLECTION].count_documents({}) == 0


async def test_a_billed_month_reads_its_invoice_not_a_later_manual_discount(
    admin: httpx.AsyncClient, real_db: Any, acad: str
) -> None:
    await _family(real_db, acad)
    await _offer(real_db)
    await _repo(real_db).generate_monthly_payments(PERIOD)

    # The invoice already carries the sibling line; a larger manual discount
    # set afterwards prices next month, not this one.
    await _manual(real_db, percent_bps=2_000)

    assert _by_enrollment(await _badges(admin))["enr-b"] == ("discounted", "sibling_discount")
    assert (await _invoiced_discount_sources(real_db, acad, "enr-b")) == {
        "enr-b": f"sibling-auto-{PERIOD}"
    }
