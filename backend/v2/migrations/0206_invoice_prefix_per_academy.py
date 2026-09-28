"""Per-academy invoice prefix: BLNO keeps "BLNO" explicitly (Settings overhaul P1 PR 2).

``BillingSettings.invoice_number_prefix`` used to default to "BLNO" in code,
and the tenant settings save persisted that default into every academy's
``billing_settings`` document, so a second academy would have issued
BLNO-numbered invoices. The code default is now ``None`` (no number is minted
without a prefix) and only the platform writes the field. This migration:

1. Writes ``invoice_number_prefix: "BLNO"`` for BLNO explicitly, so BLNO's
   invoice numbers stay byte-identical (``BLNO-2026-09-0042``) without any
   code falling back to "BLNO". BLNO is ``acad_blno_badminton`` in production
   and ``blno`` in the local seed (``backend/scripts/seed_local.py``).
2. Gives every other academy (each ``academies`` row and each
   ``billing_settings`` row) a prefix of its own: a valid prefix it already
   holds is kept, unless it is "BLNO" (the old persisted default) or already
   taken; otherwise one is derived from the academy slug, as a new academy
   gets at creation (``domain.invoice_prefix``).
3. Creates ``billing_settings_invoice_number_prefix_unique``: a partial unique
   index on the prefix. It is global on purpose, unlike the tenant-scoped id
   indexes of #849: two academies must never issue the same invoice numbers.
   ``$gt: ""`` rather than ``$type`` keeps it planner-usable for the platform
   route's equality lookup (see 0190).

Writes are ordered other academies first, BLNO last, so the step that frees
"BLNO" always precedes the step that claims it. Idempotent: a re-run finds
every academy already holding its prefix and changes nothing. An empty
database is left empty.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.v2.contexts.billing.domain.invoice_prefix import (
    derive_invoice_prefix,
    is_valid_invoice_prefix,
)

version = "0206_invoice_prefix_per_academy"

BLNO_PREFIX = "BLNO"
#: Production id first, then the local seed's.
BLNO_ACADEMY_IDS = ("acad_blno_badminton", "blno")
INDEX_NAME = "billing_settings_invoice_number_prefix_unique"


def plan_prefixes(slugs: dict[str, str | None], current: dict[str, str | None]) -> dict[str, str]:
    """The prefix every academy should hold. Pure; ``up`` applies it."""
    academy_ids = sorted(set(slugs) | set(current))
    blno_id = next((i for i in BLNO_ACADEMY_IDS if i in academy_ids), None)
    planned: dict[str, str] = {blno_id: BLNO_PREFIX} if blno_id else {}
    taken = set(planned.values())
    for academy_id in academy_ids:
        prefix = current.get(academy_id)
        if academy_id in planned or not is_valid_invoice_prefix(prefix):
            continue
        if prefix != BLNO_PREFIX and prefix not in taken:
            planned[academy_id] = str(prefix)
            taken.add(str(prefix))
    for academy_id in academy_ids:
        if academy_id in planned:
            continue
        prefix = derive_invoice_prefix(
            slugs.get(academy_id) or academy_id, taken=taken | {BLNO_PREFIX}
        )
        planned[academy_id] = prefix
        taken.add(prefix)
    return planned


async def up(db: AsyncIOMotorDatabase[Any]) -> None:
    slugs: dict[str, str | None] = {}
    async for doc in db["academies"].find({}, {"academy_id": 1, "slug": 1}):
        if doc.get("academy_id"):
            slugs[str(doc["academy_id"])] = doc.get("slug")
    current: dict[str, str | None] = {}
    async for doc in db["billing_settings"].find({}, {"academy_id": 1, "invoice_number_prefix": 1}):
        if doc.get("academy_id"):
            current[str(doc["academy_id"])] = doc.get("invoice_number_prefix")

    planned = plan_prefixes(slugs, current)
    for academy_id in sorted(planned, key=lambda i: planned[i] == BLNO_PREFIX):
        prefix = planned[academy_id]
        if current.get(academy_id) == prefix:
            continue
        await db["billing_settings"].update_one(
            {"academy_id": academy_id},
            {"$set": {"invoice_number_prefix": prefix}},
            upsert=True,
        )

    await db["billing_settings"].create_index(
        [("invoice_number_prefix", 1)],
        name=INDEX_NAME,
        unique=True,
        partialFilterExpression={"invoice_number_prefix": {"$gt": ""}},
    )
