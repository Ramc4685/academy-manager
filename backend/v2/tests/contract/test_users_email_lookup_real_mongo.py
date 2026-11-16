"""identity_auth:8 and :0 on a real mongod: exact email lookup and backfills."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository

pytestmark = pytest.mark.asyncio

_0228 = importlib.import_module("backend.v2.migrations.0228_users_backfill_normalized_email")
_0229 = importlib.import_module("backend.v2.migrations.0229_users_backfill_last_login_at")


async def test_get_by_email_uses_the_normalized_email_index(real_db: Any) -> None:
    await real_db["users"].insert_one(
        {
            "user_id": "u1",
            "email": "Pat@Example.com",
            "normalized_email": "pat@example.com",
            "display_name": "Pat",
        }
    )

    user = await MongoUserRepository(real_db).get_by_email("PAT@example.COM")

    assert user is not None and user.user_id == "u1"
    plan = await real_db["users"].find({"normalized_email": "pat@example.com"}).explain()
    assert "IXSCAN" in str(plan["queryPlanner"]["winningPlan"])


async def test_a_legacy_row_is_found_by_regex_and_backfilled(real_db: Any) -> None:
    await real_db["users"].insert_one(
        {"user_id": "u2", "email": "Old@Example.com", "display_name": "Old"}
    )

    user = await MongoUserRepository(real_db).get_by_email("old@example.com")

    assert user is not None and user.user_id == "u2"
    row = await real_db["users"].find_one({"user_id": "u2"})
    assert row["normalized_email"] == "old@example.com"


async def test_0228_backfills_and_skips_case_duplicates_and_deleted_rows(real_db: Any) -> None:
    await real_db["users"].insert_many(
        [
            {"user_id": "a", "email": " Dup@Example.com", "display_name": "A"},
            {"user_id": "b", "email": "dup@example.COM", "display_name": "B"},
            {"user_id": "c", "email": "Solo@Example.com", "display_name": "C"},
            {"user_id": "d", "email": "gone@example.com", "status": "deleted", "display_name": "D"},
        ]
    )

    await _0228.up(real_db)
    await _0228.up(real_db)  # idempotent

    rows = {r["user_id"]: r async for r in real_db["users"].find({})}
    assert rows["c"]["normalized_email"] == "solo@example.com"
    owners = [k for k in ("a", "b") if rows[k].get("normalized_email") == "dup@example.com"]
    assert len(owners) == 1  # one keeps it, the duplicate is skipped, no crash
    assert "normalized_email" not in rows["d"]


async def test_0229_copies_the_latest_sign_in_onto_users(real_db: Any) -> None:
    early = datetime(2026, 10, 1, tzinfo=UTC)
    late = datetime(2026, 11, 1, tzinfo=UTC)
    already = datetime(2026, 11, 10, tzinfo=UTC)
    await real_db["users"].insert_many(
        [
            {"user_id": "p1", "email": "p1@example.com", "display_name": "P1"},
            {
                "user_id": "roster-2",
                "auth_uid": "fb-2",
                "email": "p2@example.com",
                "display_name": "P2",
            },
            {
                "user_id": "p3",
                "email": "p3@example.com",
                "display_name": "P3",
                "last_login_at": already,
            },
            {"user_id": "p4", "email": "p4@example.com", "display_name": "P4"},
        ]
    )
    await real_db["audit_logs"].insert_many(
        [
            {"action": "user_logged_in", "actor_id": "p1", "created_at": early},
            {"action": "user_logged_in", "actor_id": "p1", "created_at": late},
            {"action": "user_logged_in", "actor_id": "fb-2", "created_at": early},
            {"action": "user_logged_in", "actor_id": "p3", "created_at": early},
            {"action": "invoice_sent", "actor_id": "p4", "created_at": late},
        ]
    )

    await _0229.up(real_db)

    rows = {r["user_id"]: r async for r in real_db["users"].find({})}

    def _naive(value: datetime) -> datetime:
        return value.replace(tzinfo=None)

    assert rows["p1"]["last_login_at"] == _naive(late)
    assert rows["roster-2"]["last_login_at"] == _naive(early)
    assert rows["p3"]["last_login_at"] == _naive(already)
    assert "last_login_at" not in rows["p4"]
