from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

identity_membership_indexes = importlib.import_module(
    "backend.v2.migrations.0080_identity_membership_indexes"
)
from backend.scripts import launch_readiness_audit


class _ValidatorAuditDb:
    def __init__(
        self,
        validated: set[str],
        validators: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.validated = validated
        self.validators = validators or {}

    async def command(self, command: dict[str, object]) -> dict[str, object]:
        name = str(command["filter"]["name"])  # type: ignore[index]
        options = (
            {"validator": self.validators.get(name, {"$jsonSchema": {"bsonType": "object"}})}
            if name in self.validated
            else {}
        )
        return {"cursor": {"firstBatch": [{"name": name, "options": options}]}}


@pytest.mark.asyncio
async def test_launch_readiness_audit_fails_missing_ledger_copy_and_indexes(db) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "payment_id": "pay-missing-ledger-copy",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "unapplied_amount_cents": 5_000,
            "ledger_idempotency_key": "payment:missing-ledger-copy",
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )

    result = await launch_readiness_audit.audit_database(
        db, primary_academy_id="acad_blno_badminton"
    )

    assert result["status"] == "fail"
    assert result["ledger_payments"]["missing_from_ledger_payments"] == 1
    failure_checks = {failure["check"] for failure in result["failures"]}
    assert "ledger_payment_storage" in failure_checks
    assert "required_indexes" in failure_checks
    assert "legacy_payment_retirement" in failure_checks
    assert result["legacy_payment_retirement"]["ledger_shaped_payment_rows"] == 1
    assert result["legacy_payment_retirement"]["ledger_shaped_missing_copy"] == 1


@pytest.mark.asyncio
async def test_launch_readiness_audit_passes_required_storage_and_reports_membership_review(
    db,
) -> None:
    await identity_membership_indexes.up(db)
    await _create_launch_specific_indexes(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "payment_id": "pay-ledger",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "unapplied_amount_cents": 5_000,
            "ledger_idempotency_key": "payment:ledger",
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "academy_id": "acad_blno_badminton",
                "user_id": "parent-review",
                "membership_id": "membership-review",
                "roles": ["parent"],
                "status": "active",
            },
            {
                "academy_id": "acad_blno_badminton",
                "user_id": "parent-invited",
                "membership_id": "membership-invited",
                "roles": ["parent"],
                "status": "active",
                "invited_by": "admin-1",
            },
        ]
    )

    result = await launch_readiness_audit.audit_database(
        db, primary_academy_id="acad_blno_badminton"
    )

    assert result["status"] == "pass"
    assert result["required_indexes"]["status"] == "pass"
    assert result["parent_membership_review"]["status"] == "manual_review"
    assert result["parent_membership_review"]["active_parent_memberships_without_inviter"] == 1
    assert result["parent_membership_review"]["samples"][0]["user_id"] == "parent-review"


@pytest.mark.asyncio
async def test_launch_readiness_audit_fails_until_legacy_payments_are_archived(db) -> None:
    await identity_membership_indexes.up(db)
    await _create_launch_specific_indexes(db)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["payments"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "payment_id": "legacy-pay-1",
            "parent_id": "parent-1",
            "amount_cents": 5_000,
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoices"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "invoice_id": "inv-from-legacy-pay-1",
            "backfill_payment_id": "legacy-pay-1",
        }
    )

    result = await launch_readiness_audit.audit_database(
        db, primary_academy_id="acad_blno_badminton"
    )

    assert result["status"] == "fail"
    retirement = result["legacy_payment_retirement"]
    assert retirement["active_legacy_payment_rows"] == 1
    assert retirement["legacy_rows_missing_backfill"] == 0
    assert {failure["check"] for failure in retirement["failures"]} == {
        "payments_collection_not_archived"
    }


def test_launch_readiness_environment_audit_requires_single_academy_flags() -> None:
    result = launch_readiness_audit.audit_environment(
        {
            "APP_TENANCY_MODE": "single_academy",
            "PRIMARY_ACADEMY_ID": "acad_blno_badminton",
            "ENABLE_PLATFORM_ROUTES": "false",
            "ENABLE_OWNER_ROLE": "false",
            "ENABLE_STUDENT_LOGIN": "false",
            "CORS_ORIGINS": "https://academy.courtmastr.com",
        }
    )

    assert result["status"] == "pass"
    assert result["failures"] == []


def test_launch_readiness_environment_audit_fails_open_platform_or_wildcard_cors() -> None:
    result = launch_readiness_audit.audit_environment(
        {
            "APP_TENANCY_MODE": "single_academy",
            "PRIMARY_ACADEMY_ID": "acad_blno_badminton",
            "ENABLE_PLATFORM_ROUTES": "true",
            "ENABLE_OWNER_ROLE": "false",
            "ENABLE_STUDENT_LOGIN": "false",
            "CORS_ORIGINS": "*",
        }
    )

    assert result["status"] == "fail"
    failure_keys = {failure["key"] for failure in result["failures"]}
    assert failure_keys == {"ENABLE_PLATFORM_ROUTES", "CORS_ORIGINS"}


@pytest.mark.asyncio
async def test_collection_validator_audit_reports_missing_validators() -> None:
    result = await launch_readiness_audit.audit_collection_validators(
        _ValidatorAuditDb(validated={"invoices"})
    )

    assert result["status"] == "fail"
    assert "invoices" not in result["missing"]
    assert "invoices" in result["mismatched"]
    assert "ledger_payments" in result["missing"]


@pytest.mark.asyncio
async def test_collection_validator_audit_passes_when_all_required_validators_exist() -> None:
    result = await launch_readiness_audit.audit_collection_validators(
        _ValidatorAuditDb(
            validated=set(launch_readiness_audit.VALIDATORS),
            validators=launch_readiness_audit.VALIDATORS,
        )
    )

    assert result["status"] == "pass"
    assert result["missing"] == []
    assert result["mismatched"] == []


@pytest.mark.asyncio
async def test_billing_consistency_audit_catches_invoice_and_payment_mismatches(db) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["invoices"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "invoice_id": "inv-bad",
            "parent_id": "parent-1",
            "status": "paid",
            "subtotal_cents": 10_000,
            "discount_cents": 0,
            "total_cents": 10_000,
            "balance_due_cents": 4_000,
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["invoice_lines"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "invoice_id": "inv-bad",
            "line_id": "line-bad",
            "description": "Bad line",
            "amount_cents": 4_000,
        }
    )
    await db["ledger_payments"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "payment_id": "pay-bad",
            "parent_id": "parent-1",
            "amount_cents": 10_000,
            "unapplied_amount_cents": 3_000,
            "currency": "usd",
            "status": "succeeded",
            "created_at": now,
            "updated_at": now,
        }
    )
    await db["payment_allocations"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "allocation_id": "alloc-bad",
            "payment_id": "pay-bad",
            "invoice_id": "inv-bad",
            "amount_cents": 5_000,
            "created_at": now,
        }
    )
    await db["account_credit_ledger"].insert_one(
        {
            "academy_id": "acad_blno_badminton",
            "credit_id": "credit-bad",
            "parent_id": "parent-1",
            "amount_cents": 1_000,
            "remaining_amount_cents": 2_000,
            "currency": "usd",
            "status": "APPROVED",
            "created_at": now,
            "updated_at": now,
        }
    )

    result = await launch_readiness_audit.audit_billing_consistency(
        db, primary_academy_id="acad_blno_badminton"
    )

    assert result["status"] == "fail"
    checks = {failure["check"] for failure in result["failures"]}
    assert {
        "invoice_line_total_mismatch",
        "invoice_balance_mismatch",
        "paid_invoice_has_balance",
        "ledger_payment_allocation_mismatch",
        "credit_balance_invalid",
    }.issubset(checks)


@pytest.mark.asyncio
async def test_dead_letter_and_webhook_health_audits_fail_unrecovered_work(db) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["dead_letter_events"].insert_one(
        {
            "event_id": "evt-dead",
            "name": "billing.invoice.failed",
            "reason": "handler_error",
            "created_at": now,
        }
    )
    await db["dead_letter_events"].insert_many(
        [
            {
                "event_id": "evt-resolved",
                "name": "billing.invoice.paid",
                "reason": "handler_error",
                "created_at": now,
                "resolved": True,
            },
            {
                "event_id": "evt-ignored",
                "name": "billing.test.noise",
                "reason": "test_noise",
                "created_at": now,
                "ignored": True,
            },
        ]
    )
    await db["stripe_webhook_events"].insert_many(
        [
            {
                "academy_id": "acad_blno_badminton",
                "event_id": "evt-failed",
                "event_type": "invoice.payment_failed",
                "status": "failed",
                "received_at": now,
                "retry_count": 3,
            },
            {
                "academy_id": "acad_blno_badminton",
                "event_id": "evt-stale",
                "event_type": "invoice.paid",
                "status": "processing",
                "processing_locked_until": datetime(2026, 1, 1, tzinfo=UTC),
                "received_at": now,
                "retry_count": 0,
            },
        ]
    )

    dead = await launch_readiness_audit.audit_dead_letters(db)
    webhooks = await launch_readiness_audit.audit_stripe_webhook_health(
        db, primary_academy_id="acad_blno_badminton"
    )

    assert dead["status"] == "fail"
    assert dead["count"] == 3
    assert dead["unrecovered_count"] == 1
    assert webhooks["status"] == "fail"
    assert webhooks["failed_or_quarantined"] == 1
    assert webhooks["stale_locks"] == 1


@pytest.mark.asyncio
async def test_outbox_health_audit_fails_unrecovered_work(db) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    await db["outbox_events"].insert_many(
        [
            {
                "event_id": "evt-terminal",
                "status": "dead_lettered",
                "created_at": now,
            },
            {
                "event_id": "evt-resolved",
                "status": "dead_lettered",
                "resolved": True,
                "created_at": now,
            },
            {
                "event_id": "evt-stale-lock",
                "status": "processing",
                "locked_until": datetime(2026, 1, 1, tzinfo=UTC),
                "created_at": now,
            },
            {
                "event_id": "evt-retry-due",
                "status": "retry",
                "next_retry_at": datetime(2026, 1, 1, tzinfo=UTC),
                "created_at": now,
            },
            {
                "event_id": "evt-pending-due",
                "status": "pending",
                "next_retry_at": datetime(2026, 1, 1, tzinfo=UTC),
                "created_at": now,
            },
        ]
    )

    result = await launch_readiness_audit.audit_outbox_health(db)

    assert result["status"] == "fail"
    assert result["dead_lettered_unrecovered"] == 1
    assert result["stale_locks"] == 1
    assert result["retries_due"] == 1
    assert result["pending_due"] == 1


async def _create_launch_specific_indexes(db) -> None:
    await db["ledger_payments"].create_index(
        [("academy_id", 1), ("ledger_idempotency_key", 1)],
        unique=True,
        name="academy_ledger_payment_idempotency_unique",
        partialFilterExpression={"ledger_idempotency_key": {"$type": "string"}},
    )
    await db["ledger_payments"].create_index(
        [("academy_id", 1), ("payment_id", 1)],
        unique=True,
        name="academy_ledger_payment_id_unique",
        partialFilterExpression={"payment_id": {"$type": "string"}},
    )
    await db["ledger_payments"].create_index(
        [("academy_id", 1), ("parent_id", 1), ("paid_at", -1)],
        name="academy_ledger_payment_parent_paid_at",
    )
    await db["stripe_webhook_events"].create_index(
        "event_id",
        unique=True,
        name="event_id_unique",
    )
    await db["stripe_webhook_events"].create_index(
        [("academy_id", 1), ("status", 1), ("received_at", -1)],
        name="stripe_event_admin_status",
    )
    await db["support_access_grants"].create_index(
        [("academy_id", 1), ("support_user_id", 1), ("status", 1), ("expires_at", 1)],
        name="support_access_grants_academy_user_status_expires",
    )
    await db["coach_attendance"].create_index(
        [("academy_id", 1), ("occurrence_id", 1), ("coach_id", 1)],
        unique=True,
        name="coach_attendance_occurrence_coach_unique",
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
    )
    await db["academy_settings"].create_index(
        [("settings_id", 1)],
        unique=True,
        name="academy_settings_id_unique",
    )
    await db["invoices"].create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        unique=True,
        name="academy_invoice_unique",
    )
    await db["invoices"].create_index(
        [("academy_id", 1), ("parent_id", 1), ("status", 1), ("period", 1)],
        name="academy_parent_invoice_status_period",
    )
    await db["invoice_lines"].create_index(
        [("academy_id", 1), ("line_id", 1)],
        unique=True,
        name="academy_invoice_line_unique",
    )
    await db["invoice_lines"].create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        name="academy_invoice_lines",
    )
    await db["payment_allocations"].create_index(
        [("academy_id", 1), ("allocation_id", 1)],
        unique=True,
        name="academy_allocation_unique",
    )
    await db["payment_allocations"].create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        unique=True,
        name="academy_allocation_idempotency_unique",
    )
    await db["payment_allocations"].create_index(
        [("academy_id", 1), ("invoice_id", 1)],
        name="academy_invoice_allocations",
    )
    await db["payment_allocations"].create_index(
        [("academy_id", 1), ("payment_id", 1)],
        name="academy_payment_allocations",
    )
    await db["parent_billing_customers"].create_index(
        [("academy_id", 1), ("parent_id", 1)],
        unique=True,
        name="academy_parent_billing_customer_unique",
    )
    await db["parent_billing_customers"].create_index(
        [("academy_id", 1), ("stripe_customer_id", 1)],
        unique=True,
        name="academy_stripe_customer_unique",
    )
    await db["payment_attempts"].create_index(
        [("academy_id", 1), ("idempotency_key", 1)],
        unique=True,
        name="academy_payment_attempt_idempotency_unique",
    )
    await db["payment_attempts"].create_index(
        [("academy_id", 1), ("invoice_id", 1), ("created_at", -1)],
        name="academy_payment_attempt_invoice_history",
    )
    await db["account_credit_ledger"].create_index(
        [("academy_id", 1), ("credit_id", 1)],
        unique=True,
        name="academy_credit_id_unique",
    )
    await db["account_credit_ledger"].create_index(
        [("academy_id", 1), ("parent_id", 1), ("status", 1)],
        name="academy_credit_parent_status",
    )
    await db["account_credit_ledger"].create_index(
        [("academy_id", 1), ("source_type", 1), ("source_id", 1)],
        unique=True,
        name="academy_credit_source_unique",
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
    await db["outbox_events"].create_index("event_id", unique=True, name="event_id_unique")
    await db["outbox_events"].create_index(
        [("status", 1), ("next_retry_at", 1), ("locked_until", 1), ("created_at", 1)],
        name="outbox_worker_claim_queue",
    )
    await db["outbox_events"].create_index(
        [("status", 1), ("attempt_count", 1), ("updated_at", 1)],
        name="outbox_status_attempts",
    )
    await db["outbox_events"].create_index(
        [("locked_until", 1), ("status", 1)],
        name="outbox_stale_locks",
    )
