"""Migration 0207: BLNO's slug becomes ``blno-academy`` (the host its families use)."""

from __future__ import annotations

import importlib
from typing import Any

from backend.v2.composition.academy_links import academy_frontend_base_url_lookup
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import MongoAcademyRepository
from backend.v2.main import _AcademyLookupAdapter

migration = importlib.import_module("backend.v2.migrations.0207_blno_slug_blno_academy")

BLNO = "acad_blno_badminton"
FRONTEND_URL = "https://academy.courtmastr.com"


async def _academy(db: Any, academy_id: str, slug: str) -> None:
    await db["academies"].insert_one(
        {"academy_id": academy_id, "slug": slug, "display_name": slug, "status": "active"}
    )


async def _slug(db: Any, academy_id: str) -> str | None:
    doc = await db["academies"].find_one({"academy_id": academy_id})
    return doc.get("slug") if doc else None


async def test_blno_links_and_both_hosts_resolve_to_blno_after_the_rename(real_db) -> None:
    await _academy(real_db, BLNO, "blno-badminton")
    await _academy(real_db, "acad_ace", "ace")

    await migration.up(real_db)

    assert await _slug(real_db, BLNO) == "blno-academy"
    assert await _slug(real_db, "acad_ace") == "ace"
    base_url = academy_frontend_base_url_lookup(real_db, frontend_url=FRONTEND_URL)
    assert await base_url(BLNO) == "https://blno-academy.courtmastr.com"

    lookup = _AcademyLookupAdapter(MongoAcademyRepository(real_db))
    assert await lookup.find_by_slug("blno-academy") == BLNO
    assert await lookup.find_by_slug("blno-badminton") is None
    # Links already sent to the old host keep resolving through the verified domain row.
    assert await lookup.find_by_domain("blno-badminton.courtmastr.com") == BLNO
    assert await lookup.find_by_domain("blno-academy.courtmastr.com") == BLNO


async def test_rerun_is_a_no_op(real_db) -> None:
    await _academy(real_db, BLNO, "blno-badminton")
    await migration.up(real_db)
    domains = await real_db["academy_domains"].count_documents({})

    await migration.up(real_db)

    assert await _slug(real_db, BLNO) == "blno-academy"
    assert await real_db["academy_domains"].count_documents({}) == domains == 2


async def test_existing_domain_rows_follow_the_new_slug(real_db) -> None:
    await _academy(real_db, BLNO, "blno-badminton")
    await real_db["academy_domains"].insert_one(
        {
            "domain": "blno-badminton.courtmastr.com",
            "academy_id": BLNO,
            "slug": "blno-badminton",
            "status": "verified",
            "kind": "tenant_subdomain",
        }
    )

    await migration.up(real_db)

    rows = [d async for d in real_db["academy_domains"].find({"academy_id": BLNO})]
    assert {d["slug"] for d in rows} == {"blno-academy"}
    assert {d["domain"] for d in rows} == {
        "blno-academy.courtmastr.com",
        "blno-badminton.courtmastr.com",
    }


async def test_slug_taken_by_another_academy_leaves_blno_alone(real_db) -> None:
    await _academy(real_db, BLNO, "blno-badminton")
    await _academy(real_db, "acad_other", "blno-academy")

    await migration.up(real_db)

    assert await _slug(real_db, BLNO) == "blno-badminton"
    assert await real_db["academy_domains"].count_documents({}) == 0


async def test_local_seed_and_empty_database_are_untouched(real_db) -> None:
    await migration.up(real_db)
    assert await real_db["academies"].count_documents({}) == 0

    await _academy(real_db, "blno", "blno")
    await migration.up(real_db)
    assert await _slug(real_db, "blno") == "blno"
    assert await real_db["academy_domains"].count_documents({}) == 0
