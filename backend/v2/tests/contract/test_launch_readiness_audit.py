from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from backend.scripts import launch_readiness_audit

identity_membership_indexes = importlib.import_module(
    "backend.v2.migrations.0080_identity_membership_indexes"
)


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
