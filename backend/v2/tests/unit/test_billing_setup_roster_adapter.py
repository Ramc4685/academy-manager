"""Billing Setup parent roster (composition bridge over the admin student directory).

PR #917: a student document with no parent (``parent_id`` missing or ``""``)
used to yield a phantom parent row keyed on the empty string. The roster is
built by ``composition/billing_setup_roster.py`` (``BillingSetupRosterAdapter``,
wired in ``compose_admin``), not in the billing
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


@pytest.mark.asyncio
async def test_one_row_per_parent_whatever_id_each_child_stores(mongo_db) -> None:
    """Lane A verify #2: children stored under the parent's ``user_id`` and
    under their ``firebase_uid`` are ONE Billing Setup row, so "Invite all not
    invited (N)" counts and invites the family once. Another academy's child
    of the same parent never reaches this academy's roster."""
    await mongo_db["users"].insert_one(
        {
            "academy_id": ACADEMY,
            "user_id": "u-fake-parent",
            "firebase_uid": "fb-fake-parent",
            "display_name": "Fakeparent Aliasfamily",
            "email": "fakeparent@example.test",
            "roles": ["parent"],
        }
    )
    await mongo_db["students"].insert_many(
        [
            _student("stu-a", "Kiddo Useridchild", parent_id="u-fake-parent"),
            _student("stu-b", "Kiddo Firebasechild", parent_id="fb-fake-parent"),
            {
                "student_id": "stu-foreign",
                "academy_id": "acad-other",
                "full_name": "Kiddo Foreign",
                "status": "active",
                "parent_id": "fb-fake-parent",
            },
        ]
    )

    admin = _admin_use_cases(mongo_db)
    roster = admin.list_billing_setup._roster
    with tenant_scope(ACADEMY):
        parents = await roster.list_parents(academy_id=ACADEMY)
        page = await admin.list_billing_setup.execute(
            academy_id=ACADEMY, status_filter="no_account"
        )

    assert [(p.parent_id, p.aliases) for p in parents] == [("u-fake-parent", ("fb-fake-parent",))]
    assert [row.parent_id for row in page.rows] == ["u-fake-parent"]
    assert sorted(s.student_id for s in page.rows[0].students) == ["stu-a", "stu-b"]
    assert page.summary.families_total == 1


@pytest.mark.asyncio
async def test_row_id_is_a_stored_reference_when_no_child_stores_the_canonical_id(
    mongo_db,
) -> None:
    """The invite endpoint finds a parent through the student rows, so the
    grouped row keeps an id some child actually stores."""
    await mongo_db["users"].insert_one(
        {
            "academy_id": ACADEMY,
            "user_id": "u-fake-canon",
            "firebase_uid": "fb-fake-canon",
            "auth_uid": "auth-fake-canon",
            "display_name": "Fakeparent Canon",
            "email": "canon@example.test",
            "roles": ["parent"],
        }
    )
    await mongo_db["students"].insert_many(
        [
            _student("stu-c", "Kiddo Fb", parent_id="fb-fake-canon"),
            _student("stu-d", "Kiddo Auth", parent_id="auth-fake-canon"),
        ]
    )
    admin = _admin_use_cases(mongo_db)
    with tenant_scope(ACADEMY):
        parents = await admin.list_billing_setup._roster.list_parents(academy_id=ACADEMY)
    assert len(parents) == 1
    assert parents[0].parent_id in {"fb-fake-canon", "auth-fake-canon"}
    assert set((parents[0].parent_id, *parents[0].aliases)) == {"fb-fake-canon", "auth-fake-canon"}
