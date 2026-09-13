"""Audit-log rows must name the actor, not a hardcoded "admin or system" label.

#468: `list_audit_logs` returned a bare `actor_id`, so the admin audit trail
could not say *who* did something. The read path now joins `users` +
`academy_memberships` (both global collections) once per page and hands the
interface a resolved `actor_name` / `actor_role` / `actor_type`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-468"


class _NoopStripe:
    pass


def _admin_use_cases(db: Any):
    return compose_admin(
        db,
        outbox=object(),  # type: ignore[arg-type]
        idempotency_store=object(),  # type: ignore[arg-type]
        stripe=_NoopStripe(),  # type: ignore[arg-type]
    )


@pytest.fixture
def mongo_db(monkeypatch):
    mongomock_motor = pytest.importorskip("mongomock_motor")
    monkeypatch.delenv("V2_DEFAULT_ACADEMY_ID", raising=False)
    monkeypatch.delenv("DEFAULT_ACADEMY_ID", raising=False)
    get_settings.cache_clear()
    try:
        client = mongomock_motor.AsyncMongoMockClient()
        yield client["test_db"]
    finally:
        get_settings.cache_clear()


def _audit(audit_id: str, actor_id: str | None, minute: int) -> dict[str, Any]:
    return {
        "audit_id": audit_id,
        "academy_id": ACADEMY,
        "actor_id": actor_id,
        "action": "student.created",
        "entity_type": "student",
        "entity_id": "stu-1",
        "created_at": datetime(2026, 9, 13, 12, minute, tzinfo=UTC),
    }


async def _seed(db: Any) -> None:
    await db["users"].insert_many(
        [
            {"user_id": "u-coach", "display_name": "Jane Coach"},
            # The membership row is keyed by the provisioned firebase uid while
            # the audit row carries the roster user_id (see identity_aliases).
            {"user_id": "u-owner", "firebase_uid": "fb-owner", "display_name": "Olive Owner"},
            {"user_id": "u-nomember", "display_name": "Nora Nomember"},
        ]
    )
    await db["academy_memberships"].insert_many(
        [
            {
                "membership_id": "m-coach",
                "academy_id": ACADEMY,
                "user_id": "u-coach",
                "roles": ["coach"],
                "status": "active",
            },
            {
                "membership_id": "m-owner",
                "academy_id": ACADEMY,
                "user_id": "fb-owner",
                "roles": ["owner", "admin"],
                "status": "active",
            },
            {
                "membership_id": "m-other-tenant",
                "academy_id": "other-acad",
                "user_id": "u-nomember",
                "roles": ["owner"],
                "status": "active",
            },
        ]
    )
    await db["audit_logs"].insert_many(
        [
            _audit("a-coach", "u-coach", 1),
            _audit("a-owner", "u-owner", 2),
            _audit("a-system", None, 3),
            _audit("a-unknown", "u-nomember", 4),
        ]
    )


@pytest.mark.asyncio
async def test_audit_rows_carry_resolved_actor_identity(mongo_db) -> None:
    await _seed(mongo_db)

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_audit_logs()

    by_id = {row["audit_id"]: row for row in rows}

    coach = by_id["a-coach"]
    assert coach["actor_name"] == "Jane Coach"
    assert coach["actor_role"] == "coach"
    assert coach["actor_type"] == "coach"

    # Highest-privilege role wins when a membership carries several.
    owner = by_id["a-owner"]
    assert owner["actor_name"] == "Olive Owner"
    assert owner["actor_type"] == "owner"
    assert "owner" in str(owner["actor_role"])

    system = by_id["a-system"]
    assert system["actor_type"] == "system"
    assert system["actor_name"] == "System"
    assert system["actor_role"] is None


@pytest.mark.asyncio
async def test_actor_without_membership_in_this_tenant_is_not_given_a_role(mongo_db) -> None:
    await _seed(mongo_db)

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        rows = await admin.list_audit_logs()

    unknown = next(row for row in rows if row["audit_id"] == "a-unknown")
    # The user exists globally, so we can still name them, but their role in
    # ANOTHER academy must never leak into this tenant's audit trail.
    assert unknown["actor_name"] == "Nora Nomember"
    assert unknown["actor_role"] is None
    assert unknown["actor_type"] == "admin"


@pytest.mark.asyncio
async def test_audit_rows_can_be_filtered_by_actor_type(mongo_db) -> None:
    await _seed(mongo_db)

    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        coaches = await admin.list_audit_logs(actor_type="coach")
        system = await admin.list_audit_logs(actor_type="system")

    assert [row["audit_id"] for row in coaches] == ["a-coach"]
    assert [row["audit_id"] for row in system] == ["a-system"]
