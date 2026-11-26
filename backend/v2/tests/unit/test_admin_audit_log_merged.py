"""S39: the owner's Audit log is one trail over every audit collection.

Money and settings changes (late fee, cash payment, payslips, coach rates)
live in their own trails; the page used to read only ``audit_logs``, so an
owner filtering "Owners" saw logins and nothing she had done to money.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition import audit_log as audit_log_module
from backend.v2.composition.audit_log import compose_admin_audit_log
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-s39"


@pytest.fixture
def mongo_db():
    mongomock_motor = pytest.importorskip("mongomock_motor")
    return mongomock_motor.AsyncMongoMockClient()["test_db"]


def _at(minute: int) -> datetime:
    return datetime(2026, 11, 20, 15, minute, tzinfo=UTC)


async def _seed(db: Any) -> None:
    await db["users"].insert_many(
        [
            {"user_id": "u-owner", "display_name": "Olive Owner"},
            {"user_id": "u-coach", "display_name": "Cody Coach"},
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {"academy_id": ACADEMY, "user_id": "u-owner", "roles": ["owner"], "status": "active"},
            {"academy_id": ACADEMY, "user_id": "u-coach", "roles": ["coach"], "status": "active"},
        ]
    )
    await db["audit_logs"].insert_many(
        [
            {
                "audit_id": "a1",
                "academy_id": ACADEMY,
                "actor_id": "u-owner",
                "action": "auth.login",
                "created_at": _at(1),
            },
            {
                "audit_id": "a5",
                "academy_id": ACADEMY,
                "actor_id": "u-coach",
                "action": "student.created",
                "created_at": _at(5),
            },
            {
                "audit_id": "other",
                "academy_id": "other-acad",
                "actor_id": "u-owner",
                "action": "auth.login",
                "created_at": _at(9),
            },
        ]
    )
    await db["billing_audit_log"].insert_many(
        [
            {
                "audit_id": "b2",
                "academy_id": ACADEMY,
                "actor_id": "u-owner",
                "action": "billing_rules_changed",
                "at": _at(2),
            },
            {
                "audit_id": "b4",
                "academy_id": ACADEMY,
                "actor_id": "u-owner",
                "action": "manual_payment_recorded",
                "payment_id": "pay-1",
                "at": _at(4),
            },
            {
                "audit_id": "b6",
                "academy_id": ACADEMY,
                "actor_id": "system",
                "action": "late_fee_applied",
                "invoice_id": "inv-1",
                "at": _at(6),
            },
        ]
    )
    await db["payout_audit_log"].insert_one(
        {
            "audit_id": "p3",
            "academy_id": ACADEMY,
            "actor_id": "u-owner",
            "action": "approved",
            "period_id": "per-1",
            "at": _at(3),
        }
    )
    await db["coach_rate_audit_log"].insert_one(
        {
            "audit_id": "r7",
            "academy_id": ACADEMY,
            "actor_id": "u-owner",
            "action": "rate_created",
            "coach_id": "u-coach",
            "at": _at(7),
        }
    )


@pytest.mark.asyncio
async def test_rows_from_all_four_trails_merge_newest_first(mongo_db) -> None:
    await _seed(mongo_db)
    with tenant_scope(ACADEMY):
        page = await compose_admin_audit_log(mongo_db).list_page()

    assert [row["audit_id"] for row in page["logs"]] == ["r7", "b6", "a5", "b4", "p3", "b2", "a1"]
    assert page["next_cursor"] is None
    by_id = {row["audit_id"]: row for row in page["logs"]}
    assert by_id["b4"]["action_label"] == "Payment recorded by hand"
    assert by_id["b4"]["entity_type"] == "payment"
    assert by_id["b4"]["actor_name"] == "Olive Owner"
    assert by_id["p3"]["action_label"] == "Payslip approved"
    assert by_id["r7"]["action_label"] == "Coach pay rate set"
    assert by_id["a1"]["action_label"] == "Auth login"
    # An unattended job is the platform, not an unnamed admin.
    assert by_id["b6"]["actor_type"] == "system"
    assert by_id["b6"]["action_label"] == "Late fee charged"


@pytest.mark.asyncio
async def test_actor_filter_runs_before_the_limit(mongo_db) -> None:
    await _seed(mongo_db)
    with tenant_scope(ACADEMY):
        page = await compose_admin_audit_log(mongo_db).list_page(actor_type="owner", limit=3)

    # The newest rows overall are a rate change, a system late fee and a coach
    # action; a limit-then-filter read would return one owner row, not three.
    assert [row["audit_id"] for row in page["logs"]] == ["r7", "b4", "p3"]
    assert page["next_cursor"] is not None


@pytest.mark.asyncio
async def test_pages_walk_every_row_once_in_order(mongo_db) -> None:
    await _seed(mongo_db)
    # A tie on the timestamp across two trails must not drop or repeat a row.
    await mongo_db["payout_audit_log"].insert_one(
        {
            "audit_id": "p4",
            "academy_id": ACADEMY,
            "actor_id": "u-owner",
            "action": "marked_paid",
            "period_id": "per-1",
            "at": _at(4),
        }
    )
    log = compose_admin_audit_log(mongo_db)
    seen: list[str] = []
    cursor = None
    with tenant_scope(ACADEMY):
        for _ in range(10):
            page = await log.list_page(limit=2, cursor=cursor)
            seen += [row["audit_id"] for row in page["logs"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break

    assert seen == ["r7", "b6", "a5", "p4", "b4", "p3", "b2", "a1"]


@pytest.mark.asyncio
async def test_a_truncated_trail_never_lets_an_older_row_jump_ahead(mongo_db, monkeypatch) -> None:
    await _seed(mongo_db)
    monkeypatch.setattr(audit_log_module, "_SCAN", 2)
    log = compose_admin_audit_log(mongo_db)
    seen: list[str] = []
    cursor = None
    with tenant_scope(ACADEMY):
        for _ in range(20):
            page = await log.list_page(limit=50, cursor=cursor)
            seen += [row["audit_id"] for row in page["logs"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break

    assert seen == ["r7", "b6", "a5", "b4", "p3", "b2", "a1"]


@pytest.mark.asyncio
async def test_other_academies_rows_never_appear(mongo_db) -> None:
    await _seed(mongo_db)
    with tenant_scope(ACADEMY):
        page = await compose_admin_audit_log(mongo_db).list_page(limit=200)
    assert "other" not in {row["audit_id"] for row in page["logs"]}
