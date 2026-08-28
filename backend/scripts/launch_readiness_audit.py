"""Read-only launch audit for single-academy production hardening.

This script produces JSON evidence for the remaining launch gates that can be
checked from configuration and MongoDB. It does not mutate data. Use it against
staging/prod-like databases before applying the ledger payment migration and
again after the migration has run.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.backfill_p4_legacy_payments import is_legacy_payment
from backend.scripts.ledger_payments_storage_audit import (
    audit as audit_ledger_payments,
)

_P0_VALIDATORS = importlib.import_module(
    "backend.v2.migrations.0132_launch_indexes_and_validators"
).VALIDATORS
_P1_P2_VALIDATORS = importlib.import_module(
    "backend.v2.migrations.0133_broader_validators_and_outbox_retry_lock"
).VALIDATORS
# Later migrations legitimately extend some 0132/0133 validators via collMod;
# the audit must expect the LATEST applied validator per collection or a fully
# migrated database is reported as "mismatched".
_INVOICES_VALIDATOR = importlib.import_module(
    "backend.v2.migrations.0138_invoice_numbering"
).INVOICES_VALIDATOR
_LEDGER_PAYMENTS_VALIDATOR = importlib.import_module(
    "backend.v2.migrations.0140_ledger_payment_metadata"
).VALIDATOR
_PARENT_BILLING_CUSTOMERS_VALIDATOR = importlib.import_module(
    "backend.v2.migrations.0144_parent_payment_method_display"
)._validator()
VALIDATORS = {
    **_P0_VALIDATORS,
    **_P1_P2_VALIDATORS,
    "invoices": _INVOICES_VALIDATOR,
    "ledger_payments": _LEDGER_PAYMENTS_VALIDATOR,
    "parent_billing_customers": _PARENT_BILLING_CUSTOMERS_VALIDATOR,
}

EXPECTED_LAUNCH_FLAGS = {
    "APP_TENANCY_MODE": "single_academy",
    "ENABLE_PLATFORM_ROUTES": "false",
    "ENABLE_OWNER_ROLE": "false",
    "ENABLE_STUDENT_LOGIN": "false",
}

REQUIRED_INDEXES = {
    "academy_memberships": {
        "membership_academy_user_unique",
        "membership_user_status",
        "membership_academy_roles_status",
    },
    "ledger_payments": {
        "academy_ledger_payment_idempotency_unique",
        "academy_ledger_payment_id_unique",
        "academy_ledger_payment_parent_paid_at",
    },
    "stripe_webhook_events": {
        "event_id_unique",
        "stripe_event_admin_status",
    },
    "support_access_grants": {
        "support_access_grants_academy_user_status_expires",
    },
    "coach_attendance": {
        "coach_attendance_occurrence_coach_unique",
        "coach_attendance_coach_marked_at",
        "coach_attendance_status_marked_at",
    },
    "academy_settings": {
        "academy_settings_academy_unique",
        "academy_settings_id_unique",
    },
    "invoices": {
        "academy_invoice_unique",
        "academy_parent_invoice_status_period",
    },
    "invoice_lines": {
        "academy_invoice_line_unique",
        "academy_invoice_lines",
    },
    "payment_allocations": {
        "academy_allocation_unique",
        "academy_allocation_idempotency_unique",
        "academy_invoice_allocations",
        "academy_payment_allocations",
    },
    "parent_billing_customers": {
        "academy_parent_billing_customer_unique",
        "academy_stripe_customer_unique",
    },
    "payment_attempts": {
        "academy_payment_attempt_idempotency_unique",
        "academy_payment_attempt_invoice_history",
    },
    "account_credit_ledger": {
        "academy_credit_id_unique",
        "academy_credit_parent_status",
        "academy_credit_source_unique",
    },
    "credit_applications": {
        "academy_credit_application_unique",
        "academy_invoice_credit_applications",
    },
    "outbox_events": {
        "event_id_unique",
        "outbox_worker_claim_queue",
        "outbox_status_attempts",
        "outbox_stale_locks",
    },
}

RETIRED_INDEXES = {
    "payments": {
        "academy_payment_ledger_idempotency_unique",
        "academy_payment_id_unique",
        "academy_stripe_invoice_unique",
    },
    "users": {"stripe_customer_unique"},
}


def audit_environment(env: Mapping[str, str | None]) -> dict[str, Any]:
    failures: list[dict[str, str | None]] = []
    observed: dict[str, str | None] = {}

    for key, expected in EXPECTED_LAUNCH_FLAGS.items():
        value = _normalized(env.get(key))
        observed[key] = value
        if value != expected:
            failures.append({"key": key, "expected": expected, "actual": value})

    primary_academy_id = _clean(env.get("PRIMARY_ACADEMY_ID"))
    observed["PRIMARY_ACADEMY_ID"] = primary_academy_id
    if not primary_academy_id:
        failures.append(
            {"key": "PRIMARY_ACADEMY_ID", "expected": "non-empty", "actual": primary_academy_id}
        )

    cors_origins = _clean(env.get("CORS_ORIGINS") or env.get("V2_CORS_ORIGINS"))
    observed["CORS_ORIGINS"] = cors_origins
    if not cors_origins or "*" in {origin.strip() for origin in cors_origins.split(",")}:
        failures.append(
            {
                "key": "CORS_ORIGINS",
                "expected": "explicit non-wildcard origin list",
                "actual": cors_origins,
            }
        )

    return {
        "status": "pass" if not failures else "fail",
        "observed": observed,
        "failures": failures,
    }


async def audit_database(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    ledger = await audit_ledger_payments(db)
    indexes = await audit_required_indexes(db)
    memberships = await audit_parent_memberships(db, primary_academy_id=primary_academy_id)
    legacy_payment_retirement = await audit_legacy_payment_retirement(
        db, primary_academy_id=primary_academy_id
    )
    validators = await audit_collection_validators(db)
    billing_consistency = await audit_billing_consistency(db, primary_academy_id=primary_academy_id)
    dead_letters = await audit_dead_letters(db)
    webhook_health = await audit_stripe_webhook_health(db, primary_academy_id=primary_academy_id)
    outbox_health = await audit_outbox_health(db)

    failures: list[dict[str, Any]] = []
    if ledger["missing_from_ledger_payments"] != 0:
        failures.append(
            {
                "check": "ledger_payment_storage",
                "message": "ledger-shaped payments are still missing from ledger_payments",
                "missing": ledger["missing_from_ledger_payments"],
            }
        )
    if indexes["missing"]:
        failures.append(
            {
                "check": "required_indexes",
                "message": "required launch indexes are missing",
                "missing": indexes["missing"],
            }
        )
    if legacy_payment_retirement["status"] == "fail":
        failures.append(
            {
                "check": "legacy_payment_retirement",
                "message": "legacy payments/users Stripe ownership cleanup is incomplete",
                "details": legacy_payment_retirement["failures"],
            }
        )
    if validators["status"] == "fail":
        failures.append(
            {
                "check": "collection_validators",
                "message": "required Mongo validators are missing or mismatched",
                "missing": validators["missing"],
                "mismatched": validators["mismatched"],
            }
        )
    if billing_consistency["status"] == "fail":
        failures.append(
            {
                "check": "billing_consistency",
                "message": "invoice/payment/allocation/credit ledger consistency failed",
                "details": billing_consistency["failures"],
            }
        )
    if dead_letters["status"] == "fail":
        failures.append(
            {
                "check": "dead_letters",
                "message": "dead-letter events must be resolved or classified before launch",
                "count": dead_letters["unrecovered_count"],
            }
        )
    if webhook_health["status"] == "fail":
        failures.append(
            {
                "check": "stripe_webhook_health",
                "message": "Stripe webhook queue has unrecovered failures or stale locks",
                "details": webhook_health["failures"],
            }
        )
    if outbox_health["status"] == "fail":
        failures.append(
            {
                "check": "outbox_health",
                "message": "Outbox queue has unrecovered terminal rows, due retries, or stale locks",
                "details": outbox_health["failures"],
            }
        )

    return {
        "status": "pass" if not failures else "fail",
        "primary_academy_id": primary_academy_id,
        "ledger_payments": ledger,
        "required_indexes": indexes,
        "collection_validators": validators,
        "billing_consistency": billing_consistency,
        "dead_letters": dead_letters,
        "stripe_webhook_health": webhook_health,
        "outbox_health": outbox_health,
        "parent_membership_review": memberships,
        "legacy_payment_retirement": legacy_payment_retirement,
        "failures": failures,
    }


async def audit_required_indexes(db: Any) -> dict[str, Any]:
    observed: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}

    for collection_name, required in REQUIRED_INDEXES.items():
        indexes = await db[collection_name].index_information()
        names = sorted(str(name) for name in indexes)
        observed[collection_name] = names
        missing_names = sorted(required.difference(names))
        if missing_names:
            missing[collection_name] = missing_names

    return {
        "status": "pass" if not missing else "fail",
        "observed": observed,
        "missing": missing,
    }


async def audit_collection_validators(db: Any) -> dict[str, Any]:
    observed: dict[str, bool] = {}
    missing: list[str] = []
    mismatched: list[str] = []
    unsupported = False

    for collection_name, expected_validator in sorted(VALIDATORS.items()):
        try:
            result = await db.command({"listCollections": 1, "filter": {"name": collection_name}})
        except NotImplementedError:
            unsupported = True
            observed[collection_name] = False
            continue
        batch = result.get("cursor", {}).get("firstBatch", [])
        options = batch[0].get("options", {}) if batch else {}
        has_validator = bool(options.get("validator"))
        observed[collection_name] = has_validator
        if not has_validator:
            missing.append(collection_name)
            continue
        if options.get("validator") != expected_validator:
            mismatched.append(collection_name)

    if unsupported:
        return {
            "status": "unsupported",
            "observed": observed,
            "missing": [],
            "mismatched": [],
            "note": "Mongo collection validator inspection is unsupported by this test database.",
        }
    return {
        "status": "pass" if not missing and not mismatched else "fail",
        "observed": observed,
        "missing": missing,
        "mismatched": mismatched,
    }


async def audit_parent_memberships(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    query = {
        "academy_id": primary_academy_id,
        "roles": "parent",
        "status": "active",
        "$or": [
            {"invited_by": {"$exists": False}},
            {"invited_by": None},
            {"invited_by": ""},
        ],
    }
    count = await db["academy_memberships"].count_documents(query)
    samples: list[dict[str, Any]] = []
    async for doc in (
        db["academy_memberships"]
        .find(
            query,
            {
                "_id": 0,
                "membership_id": 1,
                "academy_id": 1,
                "user_id": 1,
                "roles": 1,
                "status": 1,
                "invited_by": 1,
                "accepted_at": 1,
            },
        )
        .limit(20)
    ):
        samples.append(doc)

    return {
        "status": "manual_review" if count else "pass",
        "active_parent_memberships_without_inviter": count,
        "sample_limit": 20,
        "samples": samples,
        "note": (
            "Rows here are not automatically unsafe; they lack durable inviter/admin "
            "provenance and should be reviewed before launch."
        ),
    }


async def audit_billing_consistency(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    invoice_count = 0
    payment_count = 0
    credit_count = 0

    async for invoice in db["invoices"].find({"academy_id": primary_academy_id}):
        invoice_count += 1
        invoice_id = str(invoice.get("invoice_id") or "")
        total = int(invoice.get("total_cents") or 0)
        subtotal = int(invoice.get("subtotal_cents") or total)
        discount = int(invoice.get("discount_cents") or 0)
        balance = int(invoice.get("balance_due_cents") or 0)
        line_sum = await _sum_collection_amount(
            db,
            "invoice_lines",
            {"academy_id": primary_academy_id, "invoice_id": invoice_id},
        )
        allocation_sum = await _sum_collection_amount(
            db,
            "payment_allocations",
            {"academy_id": primary_academy_id, "invoice_id": invoice_id},
        )
        credit_sum = await _sum_collection_amount(
            db,
            "credit_applications",
            {"academy_id": primary_academy_id, "invoice_id": invoice_id},
        )
        if line_sum and line_sum != subtotal:
            _append_failure(
                failures,
                {
                    "check": "invoice_line_total_mismatch",
                    "invoice_id": invoice_id,
                    "line_sum": line_sum,
                    "subtotal_cents": subtotal,
                },
            )
        if total != max(subtotal - discount, 0):
            _append_failure(
                failures,
                {
                    "check": "invoice_total_mismatch",
                    "invoice_id": invoice_id,
                    "subtotal_cents": subtotal,
                    "discount_cents": discount,
                    "total_cents": total,
                },
            )
        expected_balance = max(total - allocation_sum - credit_sum, 0)
        if str(invoice.get("status") or "") not in {"void", "waived", "cancelled"}:
            if balance != expected_balance:
                _append_failure(
                    failures,
                    {
                        "check": "invoice_balance_mismatch",
                        "invoice_id": invoice_id,
                        "total_cents": total,
                        "allocated_cents": allocation_sum,
                        "credit_applied_cents": credit_sum,
                        "balance_due_cents": balance,
                        "expected_balance_due_cents": expected_balance,
                    },
                )
            if str(invoice.get("status") or "") == "paid" and balance != 0:
                _append_failure(
                    failures,
                    {
                        "check": "paid_invoice_has_balance",
                        "invoice_id": invoice_id,
                        "balance_due_cents": balance,
                    },
                )

    async for payment in db["ledger_payments"].find({"academy_id": primary_academy_id}):
        payment_count += 1
        if str(payment.get("status") or "") not in {"succeeded", "partially_refunded", "refunded"}:
            continue
        payment_id = str(payment.get("payment_id") or "")
        amount = int(payment.get("amount_cents") or 0)
        unapplied = int(payment.get("unapplied_amount_cents") or 0)
        allocation_ids: list[str] = []
        allocated = 0
        async for allocation in db["payment_allocations"].find(
            {"academy_id": primary_academy_id, "payment_id": payment_id},
            {"allocation_id": 1, "amount_cents": 1},
        ):
            allocated += int(allocation.get("amount_cents") or 0)
            if allocation.get("allocation_id"):
                allocation_ids.append(str(allocation["allocation_id"]))
        overpayment_credit = 0
        if allocation_ids:
            overpayment_credit = await _sum_collection_amount(
                db,
                "account_credit_ledger",
                {
                    "academy_id": primary_academy_id,
                    "source_type": "OVERPAYMENT",
                    "source_id": {"$in": allocation_ids},
                },
            )
        if allocated + overpayment_credit + unapplied != amount:
            _append_failure(
                failures,
                {
                    "check": "ledger_payment_allocation_mismatch",
                    "payment_id": payment_id,
                    "amount_cents": amount,
                    "allocated_cents": allocated,
                    "overpayment_credit_cents": overpayment_credit,
                    "unapplied_amount_cents": unapplied,
                },
            )

    # (credit_id, invoice_id) pairs the audit projection knows about, so the
    # source-of-truth pass below can spot drift in either direction (#233).
    audit_pairs: set[tuple[str, str]] = set()
    async for row in db["credit_applications"].find({"academy_id": primary_academy_id}):
        audit_pairs.add((str(row.get("credit_id") or ""), str(row.get("invoice_id") or "")))

    seen_pairs: set[tuple[str, str]] = set()
    async for credit in db["account_credit_ledger"].find({"academy_id": primary_academy_id}):
        credit_count += 1
        amount = int(credit.get("amount_cents") or 0)
        remaining = int(credit.get("remaining_amount_cents") or 0)
        if amount < 0 or remaining < 0 or remaining > amount:
            _append_failure(
                failures,
                {
                    "check": "credit_balance_invalid",
                    "credit_id": str(credit.get("credit_id") or credit.get("_id") or ""),
                    "amount_cents": amount,
                    "remaining_amount_cents": remaining,
                },
            )
        if credit.get("type") == "CREDIT_APPLIED":
            continue
        credit_id = str(credit.get("credit_id") or credit.get("_id") or "")
        embedded: dict[str, int] = {}
        for entry in credit.get("applications") or []:
            if not isinstance(entry, dict):
                continue
            entry_invoice = str(entry.get("invoice_id") or "")
            embedded[entry_invoice] = embedded.get(entry_invoice, 0) + int(
                entry.get("amount_cents") or 0
            )
        for applied_invoice_id in credit.get("applied_invoice_ids") or []:
            applied_invoice_id = str(applied_invoice_id)
            seen_pairs.add((credit_id, applied_invoice_id))
            if applied_invoice_id in embedded:
                continue
            # The credit was spent on this invoice but no source records how
            # much, so the invoice cannot be repriced net after a crash.
            if (credit_id, applied_invoice_id) not in audit_pairs:
                _append_failure(
                    failures,
                    {
                        "check": "credit_application_amount_unrecoverable",
                        "credit_id": credit_id,
                        "invoice_id": applied_invoice_id,
                    },
                )
            else:
                _append_failure(
                    failures,
                    {
                        "check": "credit_application_missing_source_record",
                        "credit_id": credit_id,
                        "invoice_id": applied_invoice_id,
                    },
                )

    for credit_id, applied_invoice_id in sorted(audit_pairs - seen_pairs):
        _append_failure(
            failures,
            {
                "check": "credit_application_orphan_audit_row",
                "credit_id": credit_id,
                "invoice_id": applied_invoice_id,
            },
        )

    return {
        "status": "pass" if not failures else "fail",
        "invoice_count": invoice_count,
        "ledger_payment_count": payment_count,
        "credit_entry_count": credit_count,
        "failure_count": len(failures),
        "failures": failures,
    }


async def audit_dead_letters(db: Any) -> dict[str, Any]:
    unrecovered_filter = {
        "resolved": {"$ne": True},
        "ignored": {"$ne": True},
    }
    total_count = await db["dead_letter_events"].count_documents({})
    unrecovered_count = await db["dead_letter_events"].count_documents(unrecovered_filter)
    samples: list[dict[str, Any]] = []
    async for doc in (
        db["dead_letter_events"]
        .find(
            unrecovered_filter,
            {"_id": 0, "event_id": 1, "name": 1, "reason": 1, "created_at": 1},
        )
        .sort([("created_at", -1)])
        .limit(20)
    ):
        samples.append(doc)
    return {
        "status": "pass" if unrecovered_count == 0 else "fail",
        "count": total_count,
        "unrecovered_count": unrecovered_count,
        "sample_limit": 20,
        "samples": samples,
    }


async def audit_stripe_webhook_health(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    failures: list[dict[str, Any]] = []
    failed_count = await db["stripe_webhook_events"].count_documents(
        {
            "academy_id": primary_academy_id,
            "status": {"$in": ["failed", "quarantined"]},
        }
    )
    stale_lock_count = await db["stripe_webhook_events"].count_documents(
        {
            "academy_id": primary_academy_id,
            "status": {"$in": ["processing", "locked"]},
            "processing_locked_until": {"$lt": now},
        }
    )
    retry_due_count = await db["stripe_webhook_events"].count_documents(
        {
            "academy_id": primary_academy_id,
            "status": {"$in": ["retry", "pending_retry"]},
            "next_retry_at": {"$lte": now},
        }
    )
    if failed_count:
        failures.append({"check": "failed_or_quarantined_webhooks", "count": failed_count})
    if stale_lock_count:
        failures.append({"check": "stale_webhook_locks", "count": stale_lock_count})
    if retry_due_count:
        failures.append({"check": "webhook_retries_due", "count": retry_due_count})
    return {
        "status": "pass" if not failures else "fail",
        "failed_or_quarantined": failed_count,
        "stale_locks": stale_lock_count,
        "retries_due": retry_due_count,
        "failures": failures,
    }


async def audit_outbox_health(db: Any) -> dict[str, Any]:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    failures: list[dict[str, Any]] = []
    unrecovered_dead_lettered = await db["outbox_events"].count_documents(
        {
            "status": "dead_lettered",
            "resolved": {"$ne": True},
            "ignored": {"$ne": True},
        }
    )
    stale_lock_count = await db["outbox_events"].count_documents(
        {
            "status": "processing",
            "locked_until": {"$lt": now},
        }
    )
    retry_due_count = await db["outbox_events"].count_documents(
        {
            "status": "retry",
            "next_retry_at": {"$lte": now},
        }
    )
    pending_due_count = await db["outbox_events"].count_documents(
        {
            "status": "pending",
            "next_retry_at": {"$lte": now},
        }
    )
    if unrecovered_dead_lettered:
        failures.append(
            {"check": "outbox_dead_lettered_unrecovered", "count": unrecovered_dead_lettered}
        )
    if stale_lock_count:
        failures.append({"check": "outbox_stale_locks", "count": stale_lock_count})
    if retry_due_count:
        failures.append({"check": "outbox_retries_due", "count": retry_due_count})
    if pending_due_count:
        failures.append({"check": "outbox_pending_due", "count": pending_due_count})
    return {
        "status": "pass" if not failures else "fail",
        "dead_lettered_unrecovered": unrecovered_dead_lettered,
        "stale_locks": stale_lock_count,
        "retries_due": retry_due_count,
        "pending_due": pending_due_count,
        "failures": failures,
    }


async def _sum_collection_amount(db: Any, collection_name: str, query: dict[str, Any]) -> int:
    total = 0
    async for doc in db[collection_name].find(query, {"amount_cents": 1}):
        total += int(doc.get("amount_cents") or 0)
    return total


def _append_failure(failures: list[dict[str, Any]], failure: dict[str, Any]) -> None:
    if len(failures) < 50:
        failures.append(failure)


async def audit_legacy_payment_retirement(db: Any, *, primary_academy_id: str) -> dict[str, Any]:
    active_legacy_payment_rows = 0
    legacy_rows_missing_backfill = 0
    ledger_shaped_payment_rows = 0
    ledger_shaped_missing_copy = 0

    async for doc in db["payments"].find({"academy_id": primary_academy_id}):
        payment_id = str(doc.get("payment_id") or doc.get("_id") or "")
        if is_legacy_payment(doc):
            if doc.get("is_deleted") is True:
                continue
            active_legacy_payment_rows += 1
            invoice = await db["invoices"].find_one(
                {
                    "academy_id": primary_academy_id,
                    "$or": [
                        {"invoice_id": f"inv-from-{payment_id}"},
                        {"backfill_payment_id": payment_id},
                    ],
                },
                {"_id": 1},
            )
            if invoice is None:
                legacy_rows_missing_backfill += 1
        else:
            ledger_shaped_payment_rows += 1
            copied = await db["ledger_payments"].find_one(
                {"academy_id": primary_academy_id, "payment_id": payment_id},
                {"_id": 1},
            )
            if copied is None:
                ledger_shaped_missing_copy += 1

    users_with_stripe_customer = await db["users"].count_documents(
        {
            "academy_id": primary_academy_id,
            "stripe_customer_id": {"$type": "string"},
        }
    )
    stale_indexes: dict[str, list[str]] = {}
    for collection_name, retired_names in RETIRED_INDEXES.items():
        indexes = await db[collection_name].index_information()
        present = sorted(name for name in retired_names if name in indexes)
        if present:
            stale_indexes[collection_name] = present

    failures: list[dict[str, Any]] = []
    if active_legacy_payment_rows:
        failures.append(
            {
                "check": "payments_collection_not_archived",
                "count": active_legacy_payment_rows,
                "message": "active legacy payment rows remain in payments",
            }
        )
    if legacy_rows_missing_backfill:
        failures.append(
            {
                "check": "legacy_payments_not_backfilled",
                "count": legacy_rows_missing_backfill,
            }
        )
    if ledger_shaped_payment_rows:
        failures.append(
            {
                "check": "ledger_shaped_rows_still_in_payments",
                "count": ledger_shaped_payment_rows,
            }
        )
    if ledger_shaped_missing_copy:
        failures.append(
            {
                "check": "ledger_shaped_rows_missing_ledger_copy",
                "count": ledger_shaped_missing_copy,
            }
        )
    if users_with_stripe_customer:
        failures.append(
            {
                "check": "users_still_own_stripe_customer_id",
                "count": users_with_stripe_customer,
            }
        )
    if stale_indexes:
        failures.append({"check": "retired_indexes_present", "indexes": stale_indexes})

    return {
        "status": "pass" if not failures else "fail",
        "active_legacy_payment_rows": active_legacy_payment_rows,
        "legacy_rows_missing_backfill": legacy_rows_missing_backfill,
        "ledger_shaped_payment_rows": ledger_shaped_payment_rows,
        "ledger_shaped_missing_copy": ledger_shaped_missing_copy,
        "users_with_stripe_customer_id": users_with_stripe_customer,
        "retired_indexes_present": stale_indexes,
        "failures": failures,
    }


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalized(value: str | None) -> str | None:
    cleaned = _clean(value)
    return cleaned.lower() if cleaned is not None else None


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mongo-url", default=os.environ.get("MONGO_URL") or os.environ.get("V2_MONGO_URL")
    )
    parser.add_argument(
        "--db-name", default=os.environ.get("DB_NAME") or os.environ.get("V2_MONGO_DB")
    )
    parser.add_argument(
        "--primary-academy-id",
        default=os.environ.get("PRIMARY_ACADEMY_ID") or os.environ.get("V2_PRIMARY_ACADEMY_ID"),
    )
    parser.add_argument(
        "--env-only",
        action="store_true",
        help="Only check launch environment flags; do not connect to MongoDB.",
    )
    args = parser.parse_args()

    env_audit = audit_environment(os.environ)
    result: dict[str, Any] = {
        "status": env_audit["status"],
        "environment": env_audit,
    }

    primary_academy_id = _clean(args.primary_academy_id)
    if not args.env_only:
        if not args.mongo_url or not args.db_name:
            parser.error("--mongo-url/--db-name or MONGO_URL/DB_NAME is required")
        if not primary_academy_id:
            parser.error("--primary-academy-id or PRIMARY_ACADEMY_ID is required")

        client = AsyncIOMotorClient(args.mongo_url)
        try:
            db = client[args.db_name]
            database_audit = await audit_database(db, primary_academy_id=primary_academy_id)
            result["database"] = database_audit
            if env_audit["status"] == "fail" or database_audit["status"] == "fail":
                result["status"] = "fail"
            else:
                result["status"] = "pass"
        finally:
            client.close()

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
