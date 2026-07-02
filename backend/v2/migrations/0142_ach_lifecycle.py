"""ACH lifecycle and parent payment-method projection indexes/validators.

Slice G keeps legacy parent payment-method scalar fields valid while adding a
primary/fallback projection and an idempotent allocation-reversal audit
collection for ACH returns.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0142_ach_lifecycle"

MONEY = ["int", "long", "double", "decimal"]
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

PARENT_BILLING_CUSTOMERS_VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["academy_id", "parent_id", "created_at"],
        "properties": {
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "stripe_customer_id": {"bsonType": OPT_STRING},
            "default_payment_method_id": {"bsonType": OPT_STRING},
            "payment_method_type": {"bsonType": OPT_STRING},
            "stripe_mandate_id": {"bsonType": OPT_STRING},
            "autopay_setup_intent_id": {"bsonType": OPT_STRING},
            "autopay_setup_checkout_session_id": {"bsonType": OPT_STRING},
            "autopay_setup_completed_at": {"bsonType": OPT_DATE},
            "primary_payment_method_id": {"bsonType": OPT_STRING},
            "primary_payment_method_type": {"bsonType": OPT_STRING},
            "primary_stripe_mandate_id": {"bsonType": OPT_STRING},
            "primary_setup_intent_id": {"bsonType": OPT_STRING},
            "primary_setup_status": {
                "enum": [None, "verification_required", "verification_pending", "active"]
            },
            "fallback_payment_method_id": {"bsonType": OPT_STRING},
            "fallback_payment_method_type": {"bsonType": OPT_STRING},
            "fallback_stripe_mandate_id": {"bsonType": OPT_STRING},
            "fallback_setup_intent_id": {"bsonType": OPT_STRING},
            "fallback_setup_status": {
                "enum": [None, "verification_required", "verification_pending", "active"]
            },
            "autopay_payment_methods": {
                "bsonType": ["array", "null"],
                "items": {
                    "bsonType": "object",
                    "required": [
                        "role",
                        "stripe_payment_method_id",
                        "payment_method_type",
                        "setup_intent_id",
                        "setup_status",
                        "updated_at",
                    ],
                    "properties": {
                        "role": {"enum": ["primary", "fallback"]},
                        "stripe_payment_method_id": {"bsonType": "string"},
                        "payment_method_type": {"bsonType": "string"},
                        "stripe_mandate_id": {"bsonType": OPT_STRING},
                        "setup_intent_id": {"bsonType": "string"},
                        "checkout_session_id": {"bsonType": OPT_STRING},
                        "setup_status": {
                            "enum": [
                                "verification_required",
                                "verification_pending",
                                "active",
                            ]
                        },
                        "updated_at": {"bsonType": "date"},
                    },
                },
            },
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": OPT_DATE},
        },
    }
}

PAYMENT_ALLOCATION_REVERSALS_VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "reversal_id",
            "academy_id",
            "allocation_id",
            "payment_id",
            "invoice_id",
            "amount_cents",
            "reason",
            "idempotency_key",
            "created_at",
        ],
        "properties": {
            "reversal_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "allocation_id": {"bsonType": "string"},
            "payment_id": {"bsonType": "string"},
            "invoice_id": {"bsonType": "string"},
            "amount_cents": {"bsonType": MONEY},
            "reason": {"bsonType": "string"},
            "return_code": {"bsonType": OPT_STRING},
            "idempotency_key": {"bsonType": "string"},
            "created_at": {"bsonType": "date"},
        },
    }
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


async def up(db: AsyncIOMotorDatabase) -> None:
    await _apply_validator(
        db,
        "parent_billing_customers",
        PARENT_BILLING_CUSTOMERS_VALIDATOR,
    )
    await _apply_validator(
        db,
        "payment_allocation_reversals",
        PAYMENT_ALLOCATION_REVERSALS_VALIDATOR,
    )
    await db["payment_allocation_reversals"].create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        unique=True,
        name="uniq_payment_allocation_reversal_idempotency",
    )
    await db["payment_allocation_reversals"].create_index(
        [("academy_id", 1), ("payment_id", 1), ("created_at", -1)],
        name="payment_allocation_reversal_payment_lookup",
    )
