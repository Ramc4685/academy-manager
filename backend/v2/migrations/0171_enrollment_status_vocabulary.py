"""Enrollment status vocabulary migration (issue #699).

Renames two of the three departures vocabulary terms at rest:

    enrollments.status:            "withdrawn" -> "dropped"
    enrollments.status:            "cancelled" -> "deleted"
    enrollment_events.event_type:  "withdrawn" -> "dropped"
    enrollment_events.event_type:  "cancelled" -> "deleted"

Ground truth checked before writing this (departures design contract §5.4
assumed a $jsonSchema enum needed widening first, mirroring the #657/#658
failure mode; that assumption does not hold here and is corrected below):

* ``enrollments.status`` has never been enum-constrained. Migration 0132
  ("launch_indexes_and_validators") defines it as an unconstrained
  ``{"bsonType": "string"}``, and no later migration narrows it.
* ``enrollment_events.event_type`` is likewise an unconstrained
  ``{"bsonType": "string"}`` in migration 0133, and the in-code Literal
  (``EnrollmentLifecycleEventType``) already lists BOTH "withdrawn"/"cancelled"
  and "dropped"/"deleted" side by side (added ahead of time in #697).

So there is no dormant validator for this migration to widen, and no
collMod is required for either field. Two collections that a broader
reading of "the four departures collections" might suggest touching are
DELIBERATELY left alone, because their similarly-named statuses are a
different vocabulary, not the one #696-#699 renames:

* ``scheduled_enrollment_actions.status`` (``ScheduledActionStatus`` —
  pending/succeeded/blocked_capacity/failed/cancelled) describes whether a
  *scheduled action itself* ran, not the enrollment's attendance state. Its
  "cancelled" means "this resume/cancel job was retired", never "the
  enrollment ended". Renaming it would conflate two unrelated concepts.
* ``student_billing_enrollments.status`` (``StudentBillingEnrollmentStatus`` —
  active/paused/cancelled/transferred_out) is the *billing* relationship in
  ``contexts/billing/``, explicitly out of scope for this slice (see the
  design contract §5.2/§5.4 MUST-NOT-TOUCH lists). Its "cancelled" and
  "paused" values are billing-context vocabulary, not enrollment-context.

Also deliberately NOT renamed: ``enrollment_events.event_type == "removed"``.
"removed" is the audit label ``CancelEnrollment`` writes when an admin uses
the legacy DELETE /admin/enrollments/{id} route (see
``interfaces/admin/sessions_routes.py::cancel_enrollment``); the row's
``status`` still becomes "cancelled"/"deleted" like any other cancel — the
enrollment is NOT hard-deleted from the collection. A genuine hard delete
(the new ``delete_if_status`` CAS added by #697) already writes
``event_type="deleted"``. Renaming "removed" to "deleted" would collide two
distinct historical facts ("this row was soft-cancelled via Remove" vs.
"this row was physically deleted") into one value, making them
un-distinguishable in the audit trail. See the design contract §5.4's
"paused -> held" ESCALATE for the same category of reasoning applied here.

Ordering (not negotiable, per the design contract §5.4 and the #657/#658
lesson applied with the arrow reversed): the application code in this same
commit already reads BOTH spellings everywhere (domain/models.py
canonical_status(), widened SEATLESS, widened PAST_ENROLLMENT_STATUSES /
_TERMINAL_STATUSES) and writes ONLY the new spelling. This migration's data
rewrite is therefore safe to run at any time after that code is deployed —
old rows are read exactly like new ones — but MUST NOT be applied before
the dual-reading code ships, or a rewritten row would be misread by
still-running old code that does not know "dropped"/"deleted" yet.

Does NOT run on boot in production (``V2_RUN_MIGRATIONS_ON_BOOT`` is false,
per #629); apply it by hand, deliberately, only after the dual-reading
deploy above has been running in production for at least one full release
cycle — the same "apply after soak" caution as 0165-0169. There is no
collMod here, so there is nothing to verify against a schema; what must be
verified is only that the reading code is live everywhere (all app
instances redeployed) before this runs.

Idempotent (filters on the OLD value only, so a second run touches zero
documents) and count-logged, following the 0137 pattern.
"""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger(__name__)

version = "0171_enrollment_status_vocabulary"

#: enrollments.status rename map. Order matters for logging only.
_STATUS_RENAMES: dict[str, str] = {
    "withdrawn": "dropped",
    "cancelled": "deleted",
}

#: enrollment_events.event_type rename map. Deliberately identical to
#: _STATUS_RENAMES — see module docstring for why "removed" is excluded.
_EVENT_TYPE_RENAMES: dict[str, str] = {
    "withdrawn": "dropped",
    "cancelled": "deleted",
}


async def up(db: AsyncIOMotorDatabase) -> None:  # type: ignore[type-arg]
    enrollments = db["enrollments"]
    for old, new in _STATUS_RENAMES.items():
        result = await enrollments.update_many({"status": old}, {"$set": {"status": new}})
        log.info(
            "0171: renamed enrollments.status %r -> %r on %d document(s)",
            old,
            new,
            result.modified_count,
        )

    events = db["enrollment_events"]
    for old, new in _EVENT_TYPE_RENAMES.items():
        result = await events.update_many(
            {"event_type": old}, {"$set": {"event_type": new}}
        )
        log.info(
            "0171: renamed enrollment_events.event_type %r -> %r on %d document(s)",
            old,
            new,
            result.modified_count,
        )
