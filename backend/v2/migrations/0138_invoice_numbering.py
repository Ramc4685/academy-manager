"""Per-academy invoice numbering (Slice D).

Adds ``invoice_number`` support to the ``invoices`` collection:

- A unique, sparse index on ``(academy_id, invoice_number)`` so a bug that
  accidentally mints/writes a duplicate number is caught at the database
  layer, not just relied upon in application code. Sparse because existing
  invoices predating Slice D have no ``invoice_number`` — they are
  intentionally NOT backfilled (see below), and a sparse index excludes docs
  missing the field entirely so those docs never collide with each other or
  with anything else.
- Extends the ``invoices`` validator (originally defined in migration 0132)
  to declare ``invoice_number`` as an optional string. The field is OPTIONAL,
  not required: backfilling a synthetic invoice_number onto historical
  invoices was explicitly out of scope for this slice (there is no reliable
  way to reconstruct "what the sequence would have been" for invoices created
  before atomic per-academy/month counters existed, and doing so risks
  fabricating numbers that were never actually issued to anyone). Only
  invoices created after this migration via the updated use cases
  (AddInvoiceLine Mode B, HandleWebhookEvent session-type invoice sync) carry
  a minted invoice_number.

Gap policy: gaps in the numeric sequence ARE allowed. A voided or failed
invoice still consumes a counter value that is never reused — this migration
does not attempt to enforce (or even detect) gaplessness. See
LedgerInvoice.invoice_number and format_invoice_number() for the full
rationale.

Idempotent: safe to re-run (collMod/create_index are both no-ops on repeat).
"""

from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import CollectionInvalid, OperationFailure

version = "0138_invoice_numbering"

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


# Full ``invoices`` schema, carried forward from migration 0132 with
# ``invoice_number`` added as an optional string. collMod replaces the
# validator wholesale, so this must restate every previously-declared field —
# it cannot just diff in the new one.
INVOICES_VALIDATOR = _schema(
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
        # Slice D: human-facing invoice number, e.g. "BLNO-202606-001".
        # Optional — not backfilled onto pre-Slice-D invoices (see module docstring).
        "invoice_number": {"bsonType": OPT_STRING},
        "created_at": {"bsonType": "date"},
        "updated_at": {"bsonType": "date"},
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
    invoices = db["invoices"]
    await invoices.create_index(
        [("academy_id", 1), ("invoice_number", 1)],
        unique=True,
        sparse=True,
        name="invoices_academy_invoice_number_unique",
    )

    await _apply_validator(db, "invoices", INVOICES_VALIDATOR)
