"""The multi-academy pre-flight reads truthfully and backfills safely.

``backend/scripts/multi_academy_preflight.py`` is the gate the owner runs before
switching production to SaaS mode (docs/runbooks/enable-multi-academy.md). Its
only write is the membership backfill, so that path is pinned against a real
mongod with every migration applied (unique membership index included).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.scripts.multi_academy_preflight import audit, backfill_memberships

A = "acad-pre-a"
B = "acad-pre-b"
NOW = datetime(2026, 9, 28, tzinfo=UTC)


def _member(mid: str, user_id: str, roles: list[str], status: str = "active") -> dict[str, Any]:
    return {
        "membership_id": mid,
        "academy_id": A,
        "user_id": user_id,
        "roles": roles,
        "status": status,
        "created_at": NOW,
    }


async def _seed(db: Any) -> None:
    await db["academies"].insert_many(
        [
            {"academy_id": A, "slug": "alpha", "display_name": "Alpha", "status": "active"},
            {"academy_id": B, "slug": None, "display_name": "Bravo", "status": "active"},
        ]
    )
    users: list[dict[str, Any]] = [
        # Owner with a membership already (created by bootstrap).
        {"user_id": "u-owner", "academy_id": A, "roles": ["owner"]},
        # Registered while single-academy: no membership row.
        {"user_id": "u-parent", "auth_uid": "fb-parent", "academy_id": A, "roles": ["parent"]},
        # Membership stored under the firebase alias: covered.
        {"user_id": "u-alias", "firebase_uid": "fb-alias", "academy_id": A, "roles": ["coach"]},
        # Suspended under the SAME id and under ANOTHER alias: never backfilled.
        {"user_id": "u-susp", "academy_id": A, "roles": ["parent"]},
        {"user_id": "u-susp2", "firebase_uid": "fb-susp2", "academy_id": A, "roles": ["admin"]},
        # Disabled accounts, three ways: ignored.
        {"user_id": "u-gone", "academy_id": A, "roles": ["parent"], "is_active": False},
        {"user_id": "u-gdis", "academy_id": A, "roles": ["parent"], "global_status": "disabled"},
        {"user_id": "u-del", "academy_id": A, "roles": ["parent"], "status": "deleted"},
        # Privileged grant: reported for review, not written by default.
        {"user_id": "u-admin", "academy_id": A, "roles": ["admin", "platform_admin"]},
        # No academy at all.
        {"user_id": "u-orphan", "roles": ["parent"]},
    ]
    await db["users"].insert_many(users)
    await db["academy_memberships"].insert_many(
        [
            _member("m1", "u-owner", ["owner"]),
            _member("m2", "fb-alias", ["coach"]),
            _member("m3", "u-susp", ["parent"], status="suspended"),
            _member("m4", "fb-susp2", ["admin"], status="removed"),
        ]
    )


@pytest.mark.asyncio
async def test_audit_reports_every_blocking_gap(real_db: Any) -> None:
    await _seed(real_db)

    report = await audit(real_db)

    assert report["ready"] is False
    checks = report["checks"]
    assert checks["academies_have_slug"] == [B]
    assert checks["academies_have_owner"] == [B]
    missing = {row["user_id"]: row for row in checks["users_have_membership"]}
    assert sorted(missing) == ["u-admin", "u-parent"]
    # Platform roles never become academy roles.
    assert missing["u-admin"]["roles"] == ["admin"]
    assert missing["u-admin"]["privileged"] is True
    assert missing["u-parent"]["privileged"] is False
    assert sorted(row["user_id"] for row in checks["memberships_not_active"]) == [
        "u-susp",
        "u-susp2",
    ]
    assert checks["users_without_academy"] == ["u-orphan"]


@pytest.mark.asyncio
async def test_backfill_is_a_dry_run_unless_applied(real_db: Any) -> None:
    await _seed(real_db)
    report = await audit(real_db)
    before = await real_db["academy_memberships"].count_documents({})

    result = await backfill_memberships(
        real_db, report["checks"]["users_have_membership"], apply=False
    )

    assert result == {"would_write": 1, "written": 0, "skipped": 1}
    assert await real_db["academy_memberships"].count_documents({}) == before


@pytest.mark.asyncio
async def test_backfill_never_revives_a_suspension_and_holds_privileged_rows(
    real_db: Any,
) -> None:
    await _seed(real_db)
    report = await audit(real_db)

    first = await backfill_memberships(
        real_db, report["checks"]["users_have_membership"], apply=True
    )
    again = await backfill_memberships(
        real_db, report["checks"]["users_have_membership"], apply=True
    )

    assert first["written"] == 1  # u-parent only; u-admin waits for review
    assert again["written"] == 0  # idempotent
    parent = await real_db["academy_memberships"].find_one({"user_id": "u-parent"})
    assert (parent["academy_id"], parent["roles"], parent["status"]) == (A, ["parent"], "active")
    assert await real_db["academy_memberships"].count_documents({"user_id": "u-admin"}) == 0
    # Nothing new appeared next to either non-active row.
    for alias in ("u-susp", "u-susp2", "fb-susp2"):
        rows = await real_db["academy_memberships"].find({"user_id": alias}).to_list(5)
        assert all(r["status"] != "active" for r in rows)

    reviewed = await backfill_memberships(
        real_db,
        (await audit(real_db))["checks"]["users_have_membership"],
        apply=True,
        include_privileged=True,
    )
    assert reviewed["written"] == 1
    admin = await real_db["academy_memberships"].find_one({"user_id": "u-admin"})
    assert admin["roles"] == ["admin"]
