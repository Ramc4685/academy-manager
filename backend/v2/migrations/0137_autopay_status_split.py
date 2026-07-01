"""Split autopay_status into autopay_enrollment_status + last_attempt_outcome.

Slice B: `parent_billing_customers.autopay_status` conflated "is the parent
enrolled in autopay?" with "did the last charge attempt work?" — a classic
billing state-machine smell (a bounced charge should not look like the
parent left autopay). This migration:

1. Backfills the split enrollment-lifecycle field: any existing
   `autopay_status: "active"` (or bare `autopay_status` value) becomes
   `autopay_enrollment_status` with the same value, and the legacy field is
   removed.
2. Backfills `last_attempt_outcome` (+ `last_attempt_at`, `last_failure_code`)
   as a projection of each parent's most recent `payment_attempts` row,
   where one exists. `payment_attempts.status` values (`succeeded` |
   `failed` | `requires_action`) map onto the outcome vocabulary
   (`succeeded` | `declined` | `requires_action`).
3. Updates the Mongo validator for `parent_billing_customers` to describe
   the new split fields (follows the 0132/0136 validator pattern).

Idempotent: re-running is a no-op once the legacy field is gone and the
latest attempt has already been projected — `update_many`/`update_one` on a
stable filter, no unconditional increments.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0137_autopay_status_split"

OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

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


PARENT_BILLING_CUSTOMERS_VALIDATOR: dict[str, Any] = _schema(
    ["academy_id", "parent_id", "created_at"],
    {
        "academy_id": {"bsonType": "string"},
        "parent_id": {"bsonType": "string"},
        "stripe_customer_id": {"bsonType": OPT_STRING},
        "default_payment_method_id": {"bsonType": OPT_STRING},
        "payment_method_type": {"bsonType": OPT_STRING},
        "stripe_mandate_id": {"bsonType": OPT_STRING},
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
        "autopay_setup_intent_id": {"bsonType": OPT_STRING},
        "autopay_setup_completed_at": {"bsonType": OPT_DATE},
        "autopay_setup_checkout_session_id": {"bsonType": OPT_STRING},
        "created_at": {"bsonType": "date"},
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


async def up(db: AsyncIOMotorDatabase) -> None:
    customers = db["parent_billing_customers"]

    # 1. Backfill the split enrollment-lifecycle field from the legacy
    #    conflated field, then drop the legacy field.
    legacy_count = await customers.count_documents({"autopay_status": {"$exists": True}})
    if legacy_count:
        cursor = customers.find(
            {"autopay_status": {"$exists": True}},
            {"_id": 1, "autopay_status": 1},
        )
        migrated = 0
        async for doc in cursor:
            legacy_status = doc.get("autopay_status") or "active"
            result = await customers.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {"autopay_enrollment_status": legacy_status},
                    "$unset": {"autopay_status": ""},
                },
            )
            if result.modified_count:
                migrated += 1
        assert migrated <= legacy_count

    # 2. Backfill last_attempt_outcome (+ last_attempt_at, last_failure_code)
    #    from each parent's latest payment_attempts row, where present. Only
    #    touches customer docs that don't already carry a projection, so this
    #    is safe to re-run.
    payment_attempts = db["payment_attempts"]
    async for customer in customers.find(
        {"last_attempt_outcome": {"$exists": False}},
        {"_id": 1, "academy_id": 1, "parent_id": 1},
    ):
        academy_id = customer.get("academy_id")
        parent_id = customer.get("parent_id")
        if not academy_id or not parent_id:
            continue
        latest_attempt = await payment_attempts.find_one(
            {"academy_id": academy_id, "parent_id": parent_id},
            sort=[("created_at", -1)],
        )
        if latest_attempt is None:
            continue
        outcome = _ATTEMPT_STATUS_TO_OUTCOME.get(str(latest_attempt.get("status") or ""))
        if outcome is None:
            continue
        await customers.update_one(
            {"_id": customer["_id"]},
            {
                "$set": {
                    "last_attempt_outcome": outcome,
                    "last_attempt_at": latest_attempt.get("created_at"),
                    "last_failure_code": latest_attempt.get("failure_code"),
                }
            },
        )

    # 3. Update the validator to describe the split fields.
    await _apply_validator(db, "parent_billing_customers", PARENT_BILLING_CUSTOMERS_VALIDATOR)
