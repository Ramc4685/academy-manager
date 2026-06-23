"""Launch indexes and Mongo validators for billing-critical collections."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0132_launch_indexes_and_validators"

MONEY = ["int", "long", "double", "decimal"]
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]


def _schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "$jsonSchema": {
            "bsonType": "object",
            "required": required,
            "properties": properties,
        }
    }


VALIDATORS: dict[str, dict[str, Any]] = {
    "invoices": _schema(
        [
            "invoice_id",
            "academy_id",
            "parent_id",
            "status",
            "total_cents",
            "balance_due_cents",
            "currency",
            "created_at",
            "updated_at",
        ],
        {
            "invoice_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "student_id": {"bsonType": OPT_STRING},
            "enrollment_id": {"bsonType": OPT_STRING},
            "session_id": {"bsonType": OPT_STRING},
            "period": {"bsonType": OPT_STRING},
            "status": {
                "enum": [
                    "draft",
                    "open",
                    "partially_paid",
                    "paid",
                    "void",
                    "waived",
                    "cancelled",
                    "uncollectible",
                ]
            },
            "subtotal_cents": {"bsonType": MONEY},
            "discount_cents": {"bsonType": MONEY},
            "total_cents": {"bsonType": MONEY},
            "balance_due_cents": {"bsonType": MONEY},
            "currency": {"bsonType": "string"},
            "due_date": {"bsonType": OPT_DATE},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    ),
    "invoice_lines": _schema(
        ["line_id", "academy_id", "invoice_id", "description", "amount_cents"],
        {
            "line_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "invoice_id": {"bsonType": "string"},
            "description": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "quantity": {"bsonType": MONEY},
            "unit_amount_cents": {"bsonType": MONEY},
        },
    ),
    "ledger_payments": _schema(
        [
            "payment_id",
            "academy_id",
            "parent_id",
            "amount_cents",
            "unapplied_amount_cents",
            "currency",
            "status",
            "created_at",
            "updated_at",
        ],
        {
            "payment_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "unapplied_amount_cents": {"bsonType": MONEY},
            "currency": {"bsonType": "string"},
            "status": {
                "enum": ["pending", "succeeded", "failed", "refunded", "partially_refunded"]
            },
            "payment_method": {"bsonType": OPT_STRING},
            "stripe_payment_intent_id": {"bsonType": OPT_STRING},
            "stripe_invoice_id": {"bsonType": OPT_STRING},
            "paid_at": {"bsonType": OPT_DATE},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    ),
    "payment_allocations": _schema(
        ["allocation_id", "academy_id", "payment_id", "invoice_id", "amount_cents", "created_at"],
        {
            "allocation_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "payment_id": {"bsonType": "string"},
            "invoice_id": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "idempotency_key": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
        },
    ),
    "account_credit_ledger": _schema(
        [
            "credit_id",
            "academy_id",
            "parent_id",
            "type",
            "status",
            "amount_cents",
            "remaining_amount_cents",
            "currency",
            "created_at",
            "updated_at",
        ],
        {
            "credit_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "student_id": {"bsonType": OPT_STRING},
            "enrollment_id": {"bsonType": OPT_STRING},
            "invoice_id": {"bsonType": OPT_STRING},
            "type": {"bsonType": "string"},
            "status": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "remaining_amount_cents": {"bsonType": MONEY},
            "currency": {"bsonType": "string"},
            "source_type": {"bsonType": OPT_STRING},
            "source_id": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    ),
    "payment_attempts": _schema(
        [
            "attempt_id",
            "academy_id",
            "invoice_id",
            "parent_id",
            "amount_cents",
            "currency",
            "status",
            "created_at",
        ],
        {
            "attempt_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "invoice_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "currency": {"bsonType": "string"},
            "status": {"bsonType": "string"},
            "stripe_payment_intent_id": {"bsonType": OPT_STRING},
            "stripe_checkout_session_id": {"bsonType": OPT_STRING},
            "failure_code": {"bsonType": OPT_STRING},
            "failure_message": {"bsonType": OPT_STRING},
            "idempotency_key": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "parent_billing_customers": _schema(
        ["academy_id", "parent_id", "created_at"],
        {
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "stripe_customer_id": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": OPT_DATE},
        },
    ),
    "subscriptions": _schema(
        [
            "subscription_id",
            "academy_id",
            "parent_id",
            "status",
            "payment_mode",
            "created_at",
            "updated_at",
        ],
        {
            "subscription_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "student_id": {"bsonType": OPT_STRING},
            "enrollment_id": {"bsonType": OPT_STRING},
            "session_id": {"bsonType": OPT_STRING},
            "status": {"bsonType": "string"},
            "payment_mode": {"bsonType": "string"},
            "processor_refs": {"bsonType": ["object", "null"]},
            "stripe_subscription_id": {"bsonType": OPT_STRING},
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
        },
    ),
    "enrollments": _schema(
        ["academy_id", "enrollment_id", "student_id", "session_id", "status"],
        {
            "academy_id": {"bsonType": "string"},
            "enrollment_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "session_id": {"bsonType": "string"},
            "parent_id": {"bsonType": OPT_STRING},
            "status": {"bsonType": "string"},
        },
    ),
    "students": _schema(
        ["academy_id", "student_id", "parent_id"],
        {
            "academy_id": {"bsonType": "string"},
            "student_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "full_name": {"bsonType": OPT_STRING},
            "status": {"bsonType": OPT_STRING},
        },
    ),
    "users": _schema(
        ["user_id"],
        {
            "user_id": {"bsonType": "string"},
            "email": {"bsonType": OPT_STRING},
            "normalized_email": {"bsonType": OPT_STRING},
            "display_name": {"bsonType": OPT_STRING},
            "global_status": {"bsonType": OPT_STRING},
            "stripe_customer_id": {"bsonType": "null"},
        },
    ),
    "academy_memberships": _schema(
        ["membership_id", "academy_id", "user_id", "roles", "status"],
        {
            "membership_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "user_id": {"bsonType": "string"},
            "roles": {"bsonType": "array", "items": {"bsonType": "string"}},
            "status": {"bsonType": "string"},
        },
    ),
    "stripe_webhook_events": _schema(
        ["event_id", "event_type", "status", "received_at", "retry_count"],
        {
            "event_id": {"bsonType": "string"},
            "event_type": {"bsonType": "string"},
            "academy_id": {"bsonType": OPT_STRING},
            "status": {"bsonType": "string"},
            "raw_payload": {"bsonType": ["object", "string", "null"]},
            "retry_count": {"bsonType": ["int", "long"]},
            "received_at": {"bsonType": "date"},
            "processed_at": {"bsonType": OPT_DATE},
            "next_retry_at": {"bsonType": OPT_DATE},
            "processor_id": {"bsonType": OPT_STRING},
            "processing_locked_until": {"bsonType": OPT_DATE},
        },
    ),
}


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


async def _create_launch_indexes(db: AsyncIOMotorDatabase) -> None:
    await db["coach_attendance"].create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("coach_id", 1)],
        unique=True,
        name="coach_attendance_occurrence_coach_unique",
        partialFilterExpression={
            "occurrence_id": {"$type": "string"},
            "coach_id": {"$type": "string"},
        },
    )
    await db["coach_attendance"].create_index(
        [("academy_id", 1), ("coach_id", 1), ("marked_at", -1)],
        name="coach_attendance_coach_marked_at",
    )
    await db["coach_attendance"].create_index(
        [("academy_id", 1), ("status", 1), ("marked_at", -1)],
        name="coach_attendance_status_marked_at",
    )
    await db["academy_settings"].create_index(
        [("academy_id", 1)],
        unique=True,
        name="academy_settings_academy_unique",
        partialFilterExpression={"academy_id": {"$type": "string"}},
    )
    await db["academy_settings"].create_index(
        [("settings_id", 1)],
        unique=True,
        name="academy_settings_id_unique",
        partialFilterExpression={"settings_id": {"$type": "string"}},
    )
    await db["account_credit_ledger"].create_index(
        [("academy_id", 1), ("credit_id", 1)],
        unique=True,
        name="academy_credit_id_unique",
        partialFilterExpression={"credit_id": {"$type": "string"}},
    )
    await _drop_conflicting_index_for_key(
        db["account_credit_ledger"],
        [("academy_id", 1), ("parent_id", 1), ("status", 1)],
        "academy_credit_parent_status",
    )
    await db["account_credit_ledger"].create_index(
        [("academy_id", 1), ("parent_id", 1), ("status", 1)],
        name="academy_credit_parent_status",
    )
    await _drop_conflicting_index_for_key(
        db["credit_applications"],
        [("academy_id", 1), ("credit_id", 1), ("invoice_id", 1)],
        "academy_credit_application_unique",
    )
    await db["credit_applications"].create_index(
        [("academy_id", 1), ("credit_id", 1), ("invoice_id", 1)],
        unique=True,
        name="academy_credit_application_unique",
    )
    await db["credit_applications"].create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        name="academy_invoice_credit_applications",
    )


async def _drop_conflicting_index_for_key(
    collection: Any, keys: list[tuple[str, int]], desired_name: str
) -> None:
    if not hasattr(collection, "index_information"):
        return
    indexes = await collection.index_information()
    for name, info in indexes.items():
        if name != desired_name and info.get("key") == keys:
            await collection.drop_index(name)


async def up(db: AsyncIOMotorDatabase) -> None:
    await _create_launch_indexes(db)
    for collection_name, validator in VALIDATORS.items():
        await _apply_validator(db, collection_name, validator)
