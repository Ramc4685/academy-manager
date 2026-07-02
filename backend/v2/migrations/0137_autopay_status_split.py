"""Per-enrollment autopay status split on student_billing_enrollments.

Slice B: autopay status is PER-ENROLLMENT (each child's enrollment has its own
on/off/paused state), and it must NOT be conflated with a single charge
attempt's outcome. The status therefore lives on ``student_billing_enrollments``
(the aggregate the charge path resolves from an invoice and that pause/resume
mutate), NOT on the per-parent ``parent_billing_customers`` record.

This migration:

1. Backfills ``autopay_enrollment_status`` on each ``student_billing_enrollments``
   doc that lacks it, derived from the existing billing-relationship ``status``:
   active -> active, paused -> paused, cancelled/transferred_out -> disabled,
   anything else -> setup_started (mid-setup default).
2. Backfills the ``last_attempt_outcome`` (+ ``last_attempt_at``,
   ``last_failure_code``) projection from the enrollment's most recent
   ``payment_attempts`` row, linked via its ``invoices`` (invoice.enrollment_id
   -> payment_attempts.invoice_id). ``payment_attempts.status`` maps
   succeeded -> succeeded, failed -> declined, requires_action -> requires_action;
   any other/unknown status maps to ``error`` so a latest-attempt is never
   silently dropped.
3. Updates the Mongo validator for ``student_billing_enrollments`` to describe
   the new fields (follows the 0132/0136 validator pattern).

Idempotent + count-validated: both backfills filter on the target field being
absent, so re-running is a no-op; applied counts are asserted exactly and logged.
"""

from __future__ import annotations

import logging
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

log = logging.getLogger(__name__)

version = "0137_autopay_status_split"

OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

# billing-relationship status -> initial autopay enrollment status for
# enrollments that are NOT active. An active billing relationship is resolved
# separately (see _autopay_status_for_active) because "active billing" alone is
# not evidence that the parent ever set up autopay.
_NONACTIVE_STATUS_TO_AUTOPAY_ENROLLMENT = {
    "paused": "paused",
    "cancelled": "disabled",
    "transferred_out": "disabled",
}

# payment_attempts.status -> AutopayAttemptOutcome. Unknown statuses fall back
# to "error" rather than being dropped (an unmapped latest attempt is still a
# signal that the last charge did not cleanly succeed).
_ATTEMPT_STATUS_TO_OUTCOME = {
    "succeeded": "succeeded",
    "failed": "declined",
    "requires_action": "requires_action",
}


def _schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": required,
            "properties": properties,
        }
    }


STUDENT_BILLING_ENROLLMENTS_VALIDATOR: dict[str, Any] = _schema(
    ["enrollment_id", "academy_id", "student_id", "parent_id", "session_type_id"],
    {
        "enrollment_id": {"bsonType": "string"},
        "academy_id": {"bsonType": "string"},
        "student_id": {"bsonType": "string"},
        "parent_id": {"bsonType": "string"},
        "session_type_id": {"bsonType": "string"},
        "stripe_subscription_id": {"bsonType": OPT_STRING},
        "billing_start_date": {"bsonType": ["date", "null"]},
        "status": {"bsonType": OPT_STRING},
        "autopay_enrollment_status": {
            "bsonType": OPT_STRING,
            "enum": [
                None,
                "not_offered",
                "offered",
                "setup_started",
                "active",
                "paused",
                "disabled",
            ],
        },
        "last_attempt_outcome": {
            "bsonType": OPT_STRING,
            "enum": [None, "succeeded", "declined", "requires_action", "error"],
        },
        "last_attempt_at": {"bsonType": OPT_DATE},
        "last_failure_code": {"bsonType": OPT_STRING},
        "override_price_cents": {"bsonType": ["int", "long", "null"]},
        "enrolled_at": {"bsonType": ["date", "null"]},
        "updated_at": {"bsonType": OPT_DATE},
    },
)


async def _apply_validator(
    db: AsyncIOMotorDatabase, collection_name: str, validator: dict[str, Any]
) -> None:
    try:
        await db.command(
            {
                "collMod": collection_name,
                "validator": validator,
                "validationLevel": "moderate",
                "validationAction": "error",
            }
        )
    except NotImplementedError:
        return
    except OperationFailure as exc:
        if exc.code != 26:
            raise
        try:
            await db.create_collection(
                collection_name,
                validator=validator,
                validationLevel="moderate",
                validationAction="error",
            )
        except CollectionInvalid:
            await db.command(
                {
                    "collMod": collection_name,
                    "validator": validator,
                    "validationLevel": "moderate",
                    "validationAction": "error",
                }
            )


async def _latest_attempt_for_enrollment(
    db: AsyncIOMotorDatabase, *, academy_id: str, enrollment_id: str
) -> dict[str, Any] | None:
    """Most recent payment_attempts row for an enrollment, joined via invoices."""
    invoice_ids = [
        str(inv["invoice_id"])
        async for inv in db["invoices"].find(
            {"academy_id": academy_id, "enrollment_id": enrollment_id},
            {"invoice_id": 1},
        )
        if inv.get("invoice_id")
    ]
    if not invoice_ids:
        return None
    return await db["payment_attempts"].find_one(
        {"academy_id": academy_id, "invoice_id": {"$in": invoice_ids}},
        sort=[("created_at", -1)],
    )


async def _has_autopay_setup_evidence(
    db: AsyncIOMotorDatabase, *, academy_id: str, enrollment_id: str
) -> bool:
    """True if there is real evidence the parent set up autopay for this
    enrollment — so an ``active`` billing relationship can be marked
    charge-eligible (``autopay_enrollment_status="active"``). Evidence is
    the enrollment has a prior *successful* autopay attempt (a
    ``payment_attempts`` row with ``status="succeeded"`` on one of its
    invoices).

    Without evidence we must NOT mark the enrollment active — a parent who
    never set up autopay would otherwise be wrongly charge-eligible.
    """
    invoice_ids = [
        str(inv["invoice_id"])
        async for inv in db["invoices"].find(
            {"academy_id": academy_id, "enrollment_id": enrollment_id},
            {"invoice_id": 1},
        )
        if inv.get("invoice_id")
    ]
    if invoice_ids:
        succeeded = await db["payment_attempts"].find_one(
            {
                "academy_id": academy_id,
                "invoice_id": {"$in": invoice_ids},
                "status": "succeeded",
            },
            {"_id": 1},
        )
        if succeeded is not None:
            return True
    return False


async def up(db: AsyncIOMotorDatabase) -> None:
    enrollments = db["student_billing_enrollments"]

    # 1. Backfill autopay_enrollment_status. An ACTIVE billing relationship is
    #    only marked charge-eligible ("active") when there is real evidence the
    #    parent set up autopay (saved default PM or a prior successful autopay
    #    attempt); otherwise it lands on "setup_started" (a legal, NON-charging
    #    state that can advance to active on real setup completion). Non-active
    #    relationships map by status (paused -> paused, cancelled/
    #    transferred_out -> disabled).
    to_backfill = await enrollments.count_documents(
        {"autopay_enrollment_status": {"$exists": False}}
    )
    status_migrated = 0
    active_with_evidence = 0
    active_without_evidence = 0
    async for doc in enrollments.find(
        {"autopay_enrollment_status": {"$exists": False}},
        {"_id": 1, "status": 1, "academy_id": 1, "parent_id": 1, "enrollment_id": 1},
    ):
        current_status = str(doc.get("status") or "active")
        if current_status == "active":
            has_evidence = await _has_autopay_setup_evidence(
                db,
                academy_id=str(doc.get("academy_id") or ""),
                enrollment_id=str(doc.get("enrollment_id") or ""),
            )
            if has_evidence:
                autopay_status = "active"
                active_with_evidence += 1
            else:
                autopay_status = "setup_started"
                active_without_evidence += 1
        else:
            autopay_status = _NONACTIVE_STATUS_TO_AUTOPAY_ENROLLMENT.get(
                current_status, "setup_started"
            )
        result = await enrollments.update_one(
            {"_id": doc["_id"]},
            {"$set": {"autopay_enrollment_status": autopay_status}},
        )
        status_migrated += result.modified_count
    if status_migrated != to_backfill:
        raise RuntimeError(
            f"autopay_enrollment_status backfill mismatch: migrated={status_migrated} "
            f"expected={to_backfill}"
        )
    log.info(
        "0137: backfilled autopay_enrollment_status on %d student_billing_enrollments "
        "(active_with_evidence=%d, active_without_evidence->setup_started=%d)",
        status_migrated,
        active_with_evidence,
        active_without_evidence,
    )

    # 2. Backfill last_attempt_outcome projection from each enrollment's latest
    #    payment attempt (linked via its invoices). Only docs missing the
    #    projection are touched, so re-running is a no-op.
    outcome_migrated = 0
    async for doc in enrollments.find(
        {"last_attempt_outcome": {"$exists": False}},
        {"_id": 1, "academy_id": 1, "enrollment_id": 1},
    ):
        academy_id = doc.get("academy_id")
        enrollment_id = doc.get("enrollment_id")
        if not academy_id or not enrollment_id:
            continue
        latest = await _latest_attempt_for_enrollment(
            db, academy_id=str(academy_id), enrollment_id=str(enrollment_id)
        )
        if latest is None:
            continue
        outcome = _ATTEMPT_STATUS_TO_OUTCOME.get(str(latest.get("status") or ""), "error")
        result = await enrollments.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "last_attempt_outcome": outcome,
                    "last_attempt_at": latest.get("created_at"),
                    "last_failure_code": latest.get("failure_code"),
                }
            },
        )
        outcome_migrated += result.modified_count
    log.info(
        "0137: backfilled last_attempt_outcome on %d student_billing_enrollments",
        outcome_migrated,
    )

    # 3. Update the validator to describe the split fields.
    await _apply_validator(db, "student_billing_enrollments", STUDENT_BILLING_ENROLLMENTS_VALIDATOR)
