"""Allow audited metadata on ledger payments.

Slice E persists the cash-discount disclosure version charged against the
autopay PaymentIntent on the app-owned ``LedgerPayment``. Existing documents
remain valid because ``metadata`` is optional.
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0140_ledger_payment_metadata"

COLLECTION = "ledger_payments"

MONEY = ["int", "long", "double", "decimal"]
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
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
        "properties": {
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
            "metadata": {
                "bsonType": ["object", "null"],
                "additionalProperties": {"bsonType": "string"},
            },
            "created_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
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
    await _apply_validator(db, COLLECTION, VALIDATOR)
