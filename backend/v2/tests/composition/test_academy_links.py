"""Per-academy frontend base URL for outbound return links (row 9).

Add-card and Stripe Connect return URLs used to point at the deployment's
platform host. They now use the academy's own subdomain, built from the
academy record's ``slug`` (never from the request), and fail safe to the
configured ``frontend_url``.
"""

from __future__ import annotations

import pytest
from backend.v2.composition.academy_links import academy_frontend_base_url_lookup

PLATFORM = "https://academy.courtmastr.com"


@pytest.fixture
def db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["test_db"]


@pytest.mark.asyncio
async def test_blno_slug_yields_the_blno_host(db) -> None:
    await db["academies"].insert_many(
        [
            {"academy_id": "acad_blno_badminton", "slug": "blno-academy"},
            {"academy_id": "acad-other", "slug": "other-club"},
        ]
    )
    base_url = academy_frontend_base_url_lookup(db, frontend_url=PLATFORM)

    assert await base_url("acad_blno_badminton") == "https://blno-academy.courtmastr.com"
    # Tenant isolation: each academy gets its own host, never another's.
    assert await base_url("acad-other") == "https://other-club.courtmastr.com"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "doc",
    [
        None,  # unknown academy
        {"academy_id": "acad-1"},  # no slug
        {"academy_id": "acad-1", "slug": ""},
        {"academy_id": "acad-1", "slug": "evil.example.com/x"},  # not a DNS label
        {"academy_id": "acad-1", "slug": "UPPER_case"},
    ],
)
async def test_missing_or_unsafe_slug_falls_back_to_frontend_url(db, doc) -> None:
    if doc is not None:
        await db["academies"].insert_one(doc)
    base_url = academy_frontend_base_url_lookup(db, frontend_url=PLATFORM + "/")

    assert await base_url("acad-1") == PLATFORM


@pytest.mark.asyncio
async def test_lookup_failure_falls_back_to_frontend_url() -> None:
    class _Broken:
        def __getitem__(self, _name):
            raise RuntimeError("mongo down")

    base_url = academy_frontend_base_url_lookup(_Broken(), frontend_url=PLATFORM)
    assert await base_url("acad_blno_badminton") == PLATFORM


@pytest.mark.asyncio
async def test_unset_frontend_url_uses_the_given_default(db) -> None:
    await db["academies"].insert_one({"academy_id": "acad-1", "slug": "club"})
    base_url = academy_frontend_base_url_lookup(
        db, frontend_url=None, default="https://app.example.com"
    )
    assert await base_url("acad-1") == "https://club.example.com"
    assert await base_url("missing") == "https://app.example.com"
