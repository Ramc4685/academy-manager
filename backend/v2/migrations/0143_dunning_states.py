"""Dunning state projection indexes and validator."""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0143_dunning_states"

COLLECTION = "dunning_states"
OPT_DATE = ["date", "null"]
OPT_STRING = ["string", "null"]

VALIDATOR: dict[str, Any] = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": [
            "academy_id",
            "invoice_id",
            "parent_id",
            "status",
            "attempt_count",
            "created_at",
            "updated_at",
        ],
        "properties": {
            "academy_id": {"bsonType": "string"},
            "invoice_id": {"bsonType": "string"},
            "parent_id": {"bsonType": "string"},
            "enrollment_id": {"bsonType": OPT_STRING},
            "status": {"enum": ["active", "processing", "resolved", "dunned"]},
            "attempt_count": {"bsonType": ["int", "long"]},
            "processing_attempt_no": {"bsonType": ["int", "long", "null"]},
            "processing_worker_id": {"bsonType": OPT_STRING},
            "first_attempt_at": {"bsonType": OPT_DATE},
            "last_attempt_at": {"bsonType": OPT_DATE},
            "next_attempt_at": {"bsonType": OPT_DATE},
            "last_failure_code": {"bsonType": OPT_STRING},
            "notification_attempts": {
                "bsonType": ["array", "null"],
                "items": {"bsonType": ["int", "long"]},
            },
            "last_notification_at": {"bsonType": OPT_DATE},
            "terminal_at": {"bsonType": OPT_DATE},
            "resolved_at": {"bsonType": OPT_DATE},
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
    states = db[COLLECTION]
    await states.create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        unique=True,
        name="uniq_dunning_state_invoice",
    )
    await states.create_index(
        [("academy_id", 1), ("status", 1), ("next_attempt_at", 1)],
        name="dunning_due_worker_scan",
    )
    await states.create_index(
        [("academy_id", 1), ("status", 1), ("updated_at", -1)],
        name="dunning_admin_status_lookup",
    )
