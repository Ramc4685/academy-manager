"""Contract tests — migration 0176 delivery_kind backfill (issue #692).

Historical invoices carry no ``delivery_kind``: the field is only stamped at
send time from now on. There is no autopay-status history to replay, so the
backfill is a best-effort approximation from the enrollment's *current*
autopay status — exactly what Month close does today — and anything it cannot
infer is left unset so it reads as unknown rather than as a wrong answer.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

migration_0176 = importlib.import_module("backend.v2.migrations.0176_backfill_ledger_delivery_kind")

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _invoice(invoice_id: str, **kw) -> dict:
    doc = {
        "invoice_id": invoice_id,
        "academy_id": "acad-1",
        "parent_id": "parent-1",
        "enrollment_id": "e-1",
        "period": "2026-09",
        "status": "open",
        "delivery_status": "sent",
        "created_at": NOW,
        "updated_at": NOW,
    }
    doc.update(kw)
    return doc


def _enrollment(enrollment_id: str, autopay: str, academy_id: str = "acad-1") -> dict:
    return {
        "academy_id": academy_id,
        "enrollment_id": enrollment_id,
        "autopay_enrollment_status": autopay,
    }


async def _kinds(db) -> dict[str, str | None]:
    return {d["invoice_id"]: d.get("delivery_kind") async for d in db["invoices"].find({})}


@pytest.mark.asyncio
async def test_backfills_notice_for_autopay_active_and_email_for_the_rest(db) -> None:
    await db["invoices"].insert_many(
        [_invoice("inv-auto"), _invoice("inv-manual", enrollment_id="e-2")]
    )
    await db["student_billing_enrollments"].insert_many(
        [_enrollment("e-1", "active"), _enrollment("e-2", "paused")]
    )

    await migration_0176.up(db)

    kinds = await _kinds(db)
    assert kinds["inv-auto"] == "autopay_notice"
    assert kinds["inv-manual"] == "invoice_email"


@pytest.mark.asyncio
async def test_leaves_unset_what_it_cannot_infer(db) -> None:
    await db["invoices"].insert_many(
        [
            _invoice("inv-no-enrollment", enrollment_id=None),
            _invoice("inv-orphan", enrollment_id="e-gone"),
        ]
    )

    await migration_0176.up(db)

    assert await _kinds(db) == {"inv-no-enrollment": None, "inv-orphan": None}


@pytest.mark.asyncio
async def test_never_touches_an_invoice_that_already_knows_its_kind(db) -> None:
    await db["invoices"].insert_one(_invoice("inv-known", delivery_kind="invoice_email"))
    await db["student_billing_enrollments"].insert_one(_enrollment("e-1", "active"))

    await migration_0176.up(db)

    assert (await _kinds(db))["inv-known"] == "invoice_email"


@pytest.mark.asyncio
async def test_skips_invoices_that_were_never_delivered(db) -> None:
    await db["invoices"].insert_many(
        [
            _invoice("inv-unsent", delivery_status="not_sent"),
            _invoice("inv-failed", delivery_status="delivery_failed"),
        ]
    )
    await db["student_billing_enrollments"].insert_one(_enrollment("e-1", "active"))

    await migration_0176.up(db)

    assert await _kinds(db) == {"inv-unsent": None, "inv-failed": None}


@pytest.mark.asyncio
async def test_enrollment_lookup_is_tenant_scoped(db) -> None:
    """An enrollment id from another academy must never label this one's send."""
    await db["invoices"].insert_one(_invoice("inv-1"))
    await db["student_billing_enrollments"].insert_one(
        _enrollment("e-1", "active", academy_id="acad-2")
    )

    await migration_0176.up(db)

    assert (await _kinds(db))["inv-1"] is None
