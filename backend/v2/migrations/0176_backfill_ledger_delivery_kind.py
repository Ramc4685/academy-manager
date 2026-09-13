"""Backfill ``invoices.delivery_kind`` for historical sends (issue #692).

``record_delivery`` now stamps which parent-facing message was sent — the
pay-link invoice email or the autopay pre-charge notice — so Month close and
the family timeline can report the split that was true at the time instead of
re-deriving it from the enrollment's *current* autopay status.

Invoices delivered before that change carry no kind. There is no
autopay-status history anywhere in the enrollment context to replay, so this
backfill is explicitly a **best-effort approximation**: it labels a send from
the enrollment's autopay status as it stands today, which is exactly the guess
the readers were making anyway — no worse, and frozen from here on. Where even
that is impossible (no ``enrollment_id``, or the billing-enrollment projection
is missing) the field is left unset and the readers keep treating it as
unknown, per the issue's "leave null and count as unknown".

Only ``delivery_status == "sent"`` invoices that have no kind yet are touched:
nothing was delivered on the other rows, and an invoice sent after this ships
already knows its own kind, so re-running is a no-op.

Production does NOT run migrations on boot (``V2_RUN_MIGRATIONS_ON_BOOT`` is
false there, #629): apply with ``run_pending_migrations`` by hand after deploy.
"""

from __future__ import annotations

from collections import defaultdict

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0176_backfill_ledger_delivery_kind"

_AUTOPAY_ACTIVE = "active"
_NOTICE = "autopay_notice"
_EMAIL = "invoice_email"


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    cursor = db["invoices"].find(
        {
            "delivery_status": "sent",
            "$or": [{"delivery_kind": {"$exists": False}}, {"delivery_kind": None}],
        },
        {"_id": 0, "invoice_id": 1, "academy_id": 1, "enrollment_id": 1},
    )
    pending = [doc async for doc in cursor]
    if not pending:
        return

    # enrollment ids to look up, grouped by tenant: an enrollment id is only
    # meaningful inside its own academy.
    wanted: dict[str, set[str]] = defaultdict(set)
    for doc in pending:
        enrollment_id = doc.get("enrollment_id")
        if enrollment_id:
            wanted[str(doc.get("academy_id") or "")].add(str(enrollment_id))

    autopay: dict[tuple[str, str], str] = {}
    for academy_id, enrollment_ids in wanted.items():
        rows = db["student_billing_enrollments"].find(
            {"academy_id": academy_id, "enrollment_id": {"$in": sorted(enrollment_ids)}},
            {"_id": 0, "enrollment_id": 1, "autopay_enrollment_status": 1},
        )
        async for row in rows:
            key = (academy_id, str(row.get("enrollment_id") or ""))
            autopay[key] = str(row.get("autopay_enrollment_status") or "")

    # (academy_id, kind) -> invoice ids, so every write stays tenant-scoped.
    batches: dict[tuple[str, str], list[str]] = defaultdict(list)
    for doc in pending:
        enrollment_id = doc.get("enrollment_id")
        if not enrollment_id:
            continue  # manual invoice: nothing to infer from, leave unknown
        academy_id = str(doc.get("academy_id") or "")
        key = (academy_id, str(enrollment_id))
        if key not in autopay:
            continue  # no projection row: leave unknown rather than guess
        kind = _NOTICE if autopay[key] == _AUTOPAY_ACTIVE else _EMAIL
        batches[(academy_id, kind)].append(str(doc["invoice_id"]))

    for (academy_id, kind), invoice_ids in batches.items():
        await db["invoices"].update_many(
            {
                "academy_id": academy_id,
                "invoice_id": {"$in": invoice_ids},
                "delivery_status": "sent",
                "$or": [{"delivery_kind": {"$exists": False}}, {"delivery_kind": None}],
            },
            {"$set": {"delivery_kind": kind}},
        )
