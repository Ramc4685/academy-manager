"""Billing Setup parent roster (composition bridge over the admin student directory).

PR #917: a student document with no parent (``parent_id`` missing or ``""``)
used to yield a phantom parent row keyed on the empty string. The roster is
built in ``compose_admin`` (``_BillingSetupRosterAdapter``), not in the billing
use case, so the guard has to be pinned against the real composition wiring
over a real (mock) student collection — ``test_billing_setup_registration.py``
only ever sees a fake roster.
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.v2.composition.admin import compose_admin
from backend.v2.shared.config.settings import get_settings
from backend.v2.shared.tenancy.context import tenant_scope

ACADEMY = "acad-roster"


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


def _student(student_id: str, full_name: str, **extra: Any) -> dict[str, Any]:
    return {
        "student_id": student_id,
        "academy_id": ACADEMY,
        "full_name": full_name,
        "status": "active",
        **extra,
    }


@pytest.mark.asyncio
async def test_list_parents_skips_students_with_no_parent(mongo_db) -> None:
    await mongo_db["users"].insert_one(
        {
            "academy_id": ACADEMY,
            "user_id": "parent-1",
            "display_name": "Parent One",
            "email": "parent1@example.com",
            "roles": ["parent"],
        }
    )
    await mongo_db["students"].insert_many(
        [
            _student("stu-1", "Child One", parent_id="parent-1"),
            # Two siblings under the same parent must still collapse to one row.
            _student("stu-2", "Child Two", parent_id="parent-1"),
            # Malformed rows: empty and missing parent ids. Neither may become
            # a parent row — before #917 both collapsed onto a "" key.
            _student("stu-3", "Orphan Empty", parent_id=""),
            _student("stu-4", "Orphan Missing"),
        ]
    )

    admin = _admin_use_cases(mongo_db)
    # The roster port is wired privately into ListBillingSetup; reach through
    # rather than run the whole page assembly (customers, autopay, balances).
    roster = admin.list_billing_setup._roster

    with tenant_scope(ACADEMY):
        parents = await roster.list_parents(academy_id=ACADEMY)

    assert [(p.parent_id, p.parent_name, p.parent_email) for p in parents] == [
        ("parent-1", "Parent One", "parent1@example.com")
    ]
    assert all(p.parent_id for p in parents)


@pytest.mark.asyncio
async def test_list_parents_is_empty_when_no_student_has_a_parent(mongo_db) -> None:
    await mongo_db["students"].insert_many(
        [
            _student("stu-3", "Orphan Empty", parent_id=""),
            _student("stu-4", "Orphan Missing"),
        ]
    )

    admin = _admin_use_cases(mongo_db)
    roster = admin.list_billing_setup._roster

    with tenant_scope(ACADEMY):
        parents = await roster.list_parents(academy_id=ACADEMY)

    assert parents == []
