"""BLNO's slug becomes ``blno-academy`` to match the address its families use.

Families reach BLNO at ``blno-academy.courtmastr.com``, but the academy row
holds ``slug: "blno-badminton"``. Every generated link (invoice emails, the
add-card and Stripe return links) is built from the slug, so they pointed at
``blno-badminton.courtmastr.com``, and after the multi-academy switch the
tenant resolver would only have found BLNO on that host.

This migration, for the production BLNO row only (``acad_blno_badminton``):

1. Renames the slug ``blno-badminton`` -> ``blno-academy``. Skipped (and
   logged) if another academy already holds ``blno-academy``; the unique
   ``academies_slug_unique`` index would refuse it anyway.
2. Keeps ``blno-badminton.courtmastr.com`` working for links already sent: a
   verified ``academy_domains`` row maps it to BLNO, so the resolver's
   custom-domain step (and the Stripe redirect allowlist) still find BLNO.
3. Records ``blno-academy.courtmastr.com`` as BLNO's verified subdomain and
   points BLNO's existing ``academy_domains`` rows at the new slug.

Idempotent: a re-run finds the slug already renamed and the domain rows in
place. Academies other than BLNO, the local seed (slug ``blno``) and an empty
database are untouched.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0207_blno_slug_blno_academy"

log = logging.getLogger(__name__)

BLNO_ACADEMY_ID = "acad_blno_badminton"
OLD_SLUG = "blno-badminton"
NEW_SLUG = "blno-academy"
PLATFORM_DOMAIN = "courtmastr.com"
OLD_HOST = f"{OLD_SLUG}.{PLATFORM_DOMAIN}"
NEW_HOST = f"{NEW_SLUG}.{PLATFORM_DOMAIN}"


async def _upsert_domain(db: AsyncIOMotorDatabase[Any], domain: str, kind: str) -> None:
    await db["academy_domains"].update_one(
        {"domain": domain},
        {
            "$set": {
                "academy_id": BLNO_ACADEMY_ID,
                "slug": NEW_SLUG,
                "status": "verified",
                "kind": kind,
            },
            "$setOnInsert": {"created_at": datetime.now(UTC)},
        },
        upsert=True,
    )


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    blno = await db["academies"].find_one({"academy_id": BLNO_ACADEMY_ID}, {"slug": 1})
    if blno is None:
        return
    slug = blno.get("slug")
    if slug not in (OLD_SLUG, NEW_SLUG):
        log.warning("0207: BLNO slug is %r, not %r; leaving it alone", slug, OLD_SLUG)
        return
    if slug == OLD_SLUG:
        holder = await db["academies"].find_one(
            {"slug": NEW_SLUG, "academy_id": {"$ne": BLNO_ACADEMY_ID}}, {"academy_id": 1}
        )
        if holder is not None:
            log.error(
                "0207: slug %r already belongs to %s; BLNO keeps %r",
                NEW_SLUG,
                holder.get("academy_id"),
                OLD_SLUG,
            )
            return
        await db["academies"].update_one(
            {"academy_id": BLNO_ACADEMY_ID, "slug": OLD_SLUG}, {"$set": {"slug": NEW_SLUG}}
        )
        log.info("0207: BLNO slug %r -> %r", OLD_SLUG, NEW_SLUG)
    await db["academy_domains"].update_many(
        {"academy_id": BLNO_ACADEMY_ID}, {"$set": {"slug": NEW_SLUG}}
    )
    await _upsert_domain(db, NEW_HOST, "tenant_subdomain")
    await _upsert_domain(db, OLD_HOST, "legacy_subdomain")
