"""Backfill ``student_billing_enrollments`` from legacy ``enrollments``.

2026-07-04 prod incident: the autopay-state projection collection was empty
because nothing populates it for enrollments created by the legacy flow — only
the v2 enroll-in-session-type flow writes it. ``CompleteAutopaySetup`` then
failed with "enrollment not found" and stuck parents on the checkout-status
poll. A one-off manual backfill (52 docs) was applied directly in prod; this
migration is the durable, environment-agnostic version of that backfill.

Mapping (mirrors the manual backfill and the repo-level self-heal in
``MongoStudentBillingEnrollmentRepository._create_projection_from_legacy_enrollment``):

- ``session_type_id``     <- legacy ``session_id``
- ``billing_start_date``  <- legacy ``enrolled_at`` (fallback ``created_at``)
- ``autopay_enrollment_status`` = ``"offered"``
- ``status``              <- legacy status (only ``active``/``paused`` are
  backfilled; cancelled/withdrawn/deleted enrollments must not be offered
  autopay)

Idempotent and insert-only: keyed on (``academy_id``, ``enrollment_id``) with
``$setOnInsert`` upserts, so existing projection docs — including anything the
v2 flow or the manual prod backfill already wrote — are never modified.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

version = "0145_backfill_student_billing_enrollments"

log = logging.getLogger(__name__)

BACKFILLABLE_STATUSES = {"active", "paused"}


async def _resolve_parent_id(
    db: AsyncIOMotorDatabase, *, academy_id: str, legacy: dict
) -> str | None:
    parent_id = legacy.get("parent_id") or legacy.get("parent_user_id")
    if parent_id:
        return str(parent_id)
    student_id = legacy.get("student_id")
    if not student_id:
        return None
    student = await db["students"].find_one(
        {"academy_id": academy_id, "student_id": str(student_id)}
    )
    if student is None:
        return None
    parent_id = student.get("parent_id") or student.get("parent_user_id")
    return str(parent_id) if parent_id else None


async def up(db: AsyncIOMotorDatabase) -> None:
    projections = db["student_billing_enrollments"]
    created = 0
    already_present = 0
    skipped_unbillable = 0
    skipped_unresolvable = 0

    async for legacy in db["enrollments"].find({}):
        enrollment_id = str(legacy.get("enrollment_id") or "")
        academy_id = str(legacy.get("academy_id") or "")
        if not enrollment_id or not academy_id:
            skipped_unresolvable += 1
            continue

        status = str(legacy.get("status") or "active")
        if legacy.get("is_deleted") is True or status not in BACKFILLABLE_STATUSES:
            skipped_unbillable += 1
            continue

        parent_id = await _resolve_parent_id(db, academy_id=academy_id, legacy=legacy)
        student_id = legacy.get("student_id")
        session_id = legacy.get("session_id")
        if not (parent_id and student_id and session_id):
            skipped_unresolvable += 1
            log.warning(
                "0145: skipped enrollment with unresolvable identity "
                "enrollment_id=%s academy_id=%s parent=%s student=%s session=%s",
                enrollment_id,
                academy_id,
                bool(parent_id),
                bool(student_id),
                bool(session_id),
            )
            continue

        now = datetime.now(UTC)
        enrolled_at = legacy.get("enrolled_at") or legacy.get("created_at") or now
        result = await projections.update_one(
            {"academy_id": academy_id, "enrollment_id": enrollment_id},
            {
                "$setOnInsert": {
                    "student_id": str(student_id),
                    "parent_id": parent_id,
                    "session_type_id": str(session_id),
                    "billing_start_date": enrolled_at,
                    "status": status,
                    "autopay_enrollment_status": "offered",
                    "enrolled_at": enrolled_at,
                    "updated_at": now,
                }
            },
            upsert=True,
        )
        if result.upserted_id is not None:
            created += 1
        else:
            already_present += 1

    log.info(
        "0145: backfilled student_billing_enrollments created=%d already_present=%d "
        "skipped_unbillable=%d skipped_unresolvable=%d",
        created,
        already_present,
        skipped_unbillable,
        skipped_unresolvable,
    )
