"""Contract tests — migration 0137 per-enrollment autopay status backfill."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

migration_0137 = importlib.import_module("backend.v2.migrations.0137_autopay_status_split")


def _enrollment(enrollment_id: str, *, status: str = "active", academy_id: str = "acad-1") -> dict:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "enrollment_id": enrollment_id,
        "academy_id": academy_id,
        "student_id": "student-1",
        "parent_id": "parent-1",
        "session_type_id": "st-1",
        "status": status,
        "billing_start_date": now,
        "enrolled_at": now,
        "updated_at": now,
    }


@pytest.mark.asyncio
async def test_backfills_nonactive_status_by_relationship(db) -> None:
    await db["student_billing_enrollments"].insert_many(
        [
            _enrollment("e-paused", status="paused"),
            _enrollment("e-cancelled", status="cancelled"),
            _enrollment("e-transferred", status="transferred_out"),
        ]
    )

    await migration_0137.up(db)

    by_id = {d["enrollment_id"]: d async for d in db["student_billing_enrollments"].find({})}
    assert by_id["e-paused"]["autopay_enrollment_status"] == "paused"
    assert by_id["e-cancelled"]["autopay_enrollment_status"] == "disabled"
    assert by_id["e-transferred"]["autopay_enrollment_status"] == "disabled"


@pytest.mark.asyncio
async def test_active_relationship_without_setup_evidence_is_not_marked_active(db) -> None:
    """P3: an active billing relationship with no autopay-setup evidence (no
    saved PM, no successful attempt) must NOT be marked charge-eligible."""
    await db["student_billing_enrollments"].insert_one(
        _enrollment("e-active-no-setup", status="active")
    )

    await migration_0137.up(db)

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-active-no-setup"})
    assert doc["autopay_enrollment_status"] == "setup_started"
    assert doc["autopay_enrollment_status"] != "active"


@pytest.mark.asyncio
async def test_parent_saved_pm_does_not_mark_sibling_enrollment_active(db) -> None:
    """A parent-level default PM is not per-enrollment autopay authorization."""
    await db["student_billing_enrollments"].insert_many(
        [
            _enrollment("e-authorized", status="active"),
            _enrollment("e-sibling-no-setup", status="active"),
        ]
    )
    await db["parent_billing_customers"].insert_one(
        {
            "academy_id": "acad-1",
            "parent_id": "parent-1",
            "default_payment_method_id": "pm_saved_123",
        }
    )
    await db["invoices"].insert_one(
        {"academy_id": "acad-1", "invoice_id": "inv-paid", "enrollment_id": "e-authorized"}
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-paid",
            "status": "succeeded",
            "failure_code": None,
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)

    authorized = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-authorized"})
    sibling = await db["student_billing_enrollments"].find_one(
        {"enrollment_id": "e-sibling-no-setup"}
    )
    assert authorized["autopay_enrollment_status"] == "active"
    assert sibling["autopay_enrollment_status"] == "setup_started"


@pytest.mark.asyncio
async def test_active_relationship_with_prior_successful_attempt_is_marked_active(db) -> None:
    """P3: setup evidence via a prior successful autopay attempt → active."""
    await db["student_billing_enrollments"].insert_one(
        _enrollment("e-active-paid", status="active")
    )
    await db["invoices"].insert_one(
        {"academy_id": "acad-1", "invoice_id": "inv-paid", "enrollment_id": "e-active-paid"}
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-paid",
            "status": "succeeded",
            "failure_code": None,
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e-active-paid"})
    assert doc["autopay_enrollment_status"] == "active"


@pytest.mark.asyncio
async def test_backfills_last_attempt_outcome_from_latest_attempt_via_invoices(db) -> None:
    await db["student_billing_enrollments"].insert_one(_enrollment("e1"))
    await db["invoices"].insert_one(
        {"academy_id": "acad-1", "invoice_id": "inv-1", "enrollment_id": "e1"}
    )
    await db["payment_attempts"].insert_many(
        [
            {
                "academy_id": "acad-1",
                "invoice_id": "inv-1",
                "status": "failed",
                "failure_code": "card_declined",
                "created_at": datetime(2026, 6, 1, tzinfo=UTC),
            },
            {
                "academy_id": "acad-1",
                "invoice_id": "inv-1",
                "status": "succeeded",
                "failure_code": None,
                "created_at": datetime(2026, 6, 15, tzinfo=UTC),
            },
        ]
    )

    await migration_0137.up(db)

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e1"})
    # Latest attempt (2026-06-15, succeeded) wins over the earlier decline.
    assert doc["last_attempt_outcome"] == "succeeded"
    assert doc["last_failure_code"] is None
    assert doc["autopay_enrollment_status"] == "active"


@pytest.mark.asyncio
async def test_unknown_attempt_status_maps_to_error_not_dropped(db) -> None:
    await db["student_billing_enrollments"].insert_one(_enrollment("e1"))
    await db["invoices"].insert_one(
        {"academy_id": "acad-1", "invoice_id": "inv-1", "enrollment_id": "e1"}
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-1",
            "status": "some_future_status",
            "failure_code": None,
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e1"})
    assert doc["last_attempt_outcome"] == "error"


@pytest.mark.asyncio
async def test_enrollment_without_attempts_gets_no_outcome_projection(db) -> None:
    await db["student_billing_enrollments"].insert_one(_enrollment("e1"))

    await migration_0137.up(db)

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e1"})
    # Active relationship but no setup evidence → not charge-eligible.
    assert doc["autopay_enrollment_status"] == "setup_started"
    assert "last_attempt_outcome" not in doc


@pytest.mark.asyncio
async def test_migration_is_idempotent(db) -> None:
    await db["student_billing_enrollments"].insert_one(_enrollment("e1"))
    await db["invoices"].insert_one(
        {"academy_id": "acad-1", "invoice_id": "inv-1", "enrollment_id": "e1"}
    )
    await db["payment_attempts"].insert_one(
        {
            "academy_id": "acad-1",
            "invoice_id": "inv-1",
            "status": "succeeded",
            "failure_code": None,
            "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        }
    )

    await migration_0137.up(db)
    await migration_0137.up(db)  # re-run must be a no-op, not an error

    doc = await db["student_billing_enrollments"].find_one({"enrollment_id": "e1"})
    assert doc["autopay_enrollment_status"] == "active"
    assert doc["last_attempt_outcome"] == "succeeded"
    assert await db["student_billing_enrollments"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_doc_with_existing_autopay_status_is_left_untouched(db) -> None:
    doc = _enrollment("e1", status="active")
    doc["autopay_enrollment_status"] = "paused"
    await db["student_billing_enrollments"].insert_one(doc)

    await migration_0137.up(db)

    stored = await db["student_billing_enrollments"].find_one({"enrollment_id": "e1"})
    assert stored["autopay_enrollment_status"] == "paused"
