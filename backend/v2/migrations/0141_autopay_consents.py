"""Append-only autopay consent log."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0141_autopay_consents"

COLLECTION = "autopay_consents"
OPT_STRING = ["string", "null"]
OPT_DATE = ["date", "null"]

VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "consent_id",
            "academy_id",
            "parent_id",
            "enrollment_id",
            "setup_intent_id",
            "stripe_payment_method_id",
            "method_type",
            "consent_text_version",
            "source",
            "captured_at",
            "at",
            "created_at",
        ],
        "properties": {
            "consent_id": {"bsonType": "string"},
            "academy_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "enrollment_id": {"bsonType": "string"},
            "setup_intent_id": {"bsonType": "string"},
            "checkout_session_id": {"bsonType": OPT_STRING},
            "stripe_payment_method_id": {"bsonType": "string"},
            "method_type": {"bsonType": "string"},
            "consent_text_version": {"bsonType": "string"},
            "ach_mandate_version": {"bsonType": OPT_STRING},
            "card_disclosure_version": {"bsonType": OPT_STRING},
            "source": {"bsonType": "string"},
            "actor_id": {"bsonType": OPT_STRING},
            "ip": {"bsonType": OPT_STRING},
            "user_agent": {"bsonType": OPT_STRING},
            "captured_at": {"bsonType": "date"},
            "at": {"bsonType": "date"},
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
    await _apply_validator(db, COLLECTION, VALIDATOR)
    consents = db[COLLECTION]
    await consents.create_index("consent_id", unique=True, name="consent_id_unique")
    await consents.create_index(
        [("academy_id", 1), ("parent_id", 1), ("captured_at", 1)],
        name="tenant_parent_consent_history",
    )
    await consents.create_index(
        [("academy_id", 1), ("setup_intent_id", 1)],
        name="tenant_setup_intent_unique",
        unique=True,
        sparse=True,
    )
