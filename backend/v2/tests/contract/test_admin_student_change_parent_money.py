"""Change-parent must not strand the child's money on the old parent (#785).

``change_admin_student_parent`` rewrote ``parent_id`` on the student document
and returned a warning string. Everything the child owes or is owed — open
invoices, spendable credit, the live waitlist request, and the per-enrollment
autopay row the dunning worker charges from — kept naming the previous parent,
so the academy went on billing (and could auto-charge) a person who no longer
has the child.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.enrollment.application.use_cases.admin_directory import (
    ChangeAdminStudentParentCommand,
)
from backend.v2.contexts.enrollment.domain.errors import StudentParentChangeBlocked
from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
    MongoStudentRepository,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _command() -> ChangeAdminStudentParentCommand:
    return ChangeAdminStudentParentCommand(
        parent_id="parent-new",
        actor_id="admin-1",
        reason="Custody update",
    )


async def _seed_family(db, academy_id: str) -> None:
    await db["students"].insert_one(
        {
            "academy_id": academy_id,
            "student_id": "st-alice",
            "full_name": "Alice Chen",
            "parent_id": "parent-old",
            "parent_user_id": "parent-old",
        }
    )
    await db["users"].insert_many(
        [
            {
                "academy_id": academy_id,
                "user_id": "parent-old",
                "display_name": "Parent Old",
                "email": "old@example.com",
                "roles": ["parent"],
                "status": "active",
                "is_active": True,
            },
            {
                "academy_id": academy_id,
                "user_id": "parent-new",
                "display_name": "Parent New",
                "email": "new@example.com",
                "roles": ["parent"],
                "status": "active",
                "is_active": True,
            },
        ]
    )


async def _seed_open_money(db, academy_id: str, **invoice_overrides: object) -> None:
    invoice = {
        "academy_id": academy_id,
        "invoice_id": "inv-open",
        "student_id": "st-alice",
        "parent_id": "parent-old",
        "status": "open",
        "balance_due_cents": 12000,
        "total_cents": 12000,
    }
    invoice.update(invoice_overrides)
    await db["invoices"].insert_many(
        [
            invoice,
            {
                "academy_id": academy_id,
                "invoice_id": "inv-paid",
                "student_id": "st-alice",
                "parent_id": "parent-old",
                "status": "paid",
                "balance_due_cents": 0,
                "total_cents": 9000,
            },
        ]
    )
    await db["account_credit_ledger"].insert_many(
        [
            {
                "academy_id": academy_id,
                "credit_id": "credit-live",
                "student_id": "st-alice",
                "parent_id": "parent-old",
                "status": "APPROVED",
                "amount_cents": 4000,
                "remaining_amount_cents": 4000,
            },
            {
                "academy_id": academy_id,
                "credit_id": "credit-spent",
                "student_id": "st-alice",
                "parent_id": "parent-old",
                "status": "APPLIED",
                "amount_cents": 2500,
                "remaining_amount_cents": 0,
            },
        ]
    )
    await db["waitlist"].insert_one(
        {
            "academy_id": academy_id,
            "waitlist_id": "wait-live",
            "student_id": "st-alice",
            "parent_id": "parent-old",
            "status": "waiting",
        }
    )
    await db["student_billing_enrollments"].insert_one(
        {
            "academy_id": academy_id,
            "enrollment_id": "enr-1",
            "student_id": "st-alice",
            "parent_id": "parent-old",
            "session_type_id": "stype-1",
            "autopay_enrollment_status": "disabled",
        }
    )


@pytest.mark.asyncio
async def test_change_parent_rehomes_the_childs_open_money(db, acad) -> None:
    await _seed_family(db, acad)
    await _seed_open_money(db, acad)
    repo = MongoStudentRepository(db)

    result = await repo.change_admin_student_parent("st-alice", _command())

    assert result is not None
    assert result.rehomed_counts == {
        "invoices": 1,
        "credits": 1,
        "waitlist": 1,
        "autopay_enrollments": 1,
    }
    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-open"})
    credit = await db["account_credit_ledger"].find_one(
        {"academy_id": acad, "credit_id": "credit-live"}
    )
    waitlist = await db["waitlist"].find_one({"academy_id": acad, "waitlist_id": "wait-live"})
    billing = await db["student_billing_enrollments"].find_one(
        {"academy_id": acad, "enrollment_id": "enr-1"}
    )
    assert invoice["parent_id"] == "parent-new"
    assert credit["parent_id"] == "parent-new"
    assert waitlist["parent_id"] == "parent-new"
    assert waitlist["parent_user_id"] == "parent-new"
    assert billing["parent_id"] == "parent-new"


@pytest.mark.asyncio
async def test_change_parent_leaves_settled_history_with_the_parent_who_paid(db, acad) -> None:
    await _seed_family(db, acad)
    await _seed_open_money(db, acad)

    await MongoStudentRepository(db).change_admin_student_parent("st-alice", _command())

    paid = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-paid"})
    spent = await db["account_credit_ledger"].find_one(
        {"academy_id": acad, "credit_id": "credit-spent"}
    )
    assert paid["parent_id"] == "parent-old"
    assert spent["parent_id"] == "parent-old"


@pytest.mark.asyncio
async def test_change_parent_refuses_while_the_invoice_is_live_in_stripe(db, acad) -> None:
    await _seed_family(db, acad)
    await _seed_open_money(db, acad, stripe_invoice_id="in_live_123")
    repo = MongoStudentRepository(db)

    with pytest.raises(StudentParentChangeBlocked) as excinfo:
        await repo.change_admin_student_parent("st-alice", _command())

    assert "inv-open" in str(excinfo.value)
    # Nothing may be half-written: the refusal has to leave the family intact.
    student = await db["students"].find_one({"academy_id": acad, "student_id": "st-alice"})
    invoice = await db["invoices"].find_one({"academy_id": acad, "invoice_id": "inv-open"})
    assert student["parent_id"] == "parent-old"
    assert invoice["parent_id"] == "parent-old"


@pytest.mark.asyncio
async def test_change_parent_refuses_while_autopay_is_active_on_the_old_parents_card(
    db, acad
) -> None:
    await _seed_family(db, acad)
    await _seed_open_money(db, acad)
    await db["student_billing_enrollments"].update_one(
        {"academy_id": acad, "enrollment_id": "enr-1"},
        {"$set": {"autopay_enrollment_status": "active"}},
    )
    repo = MongoStudentRepository(db)

    with pytest.raises(StudentParentChangeBlocked) as excinfo:
        await repo.change_admin_student_parent("st-alice", _command())

    assert "enr-1" in str(excinfo.value)
    student = await db["students"].find_one({"academy_id": acad, "student_id": "st-alice"})
    assert student["parent_id"] == "parent-old"


@pytest.mark.asyncio
async def test_change_parent_marks_the_old_guardians_waiver_signature_outdated(db, acad) -> None:
    await _seed_family(db, acad)
    await db["waiver_signatures"].insert_one(
        {
            "academy_id": acad,
            "waiver_signature_id": "ws-1",
            "student_id": "st-alice",
            "parent_user_id": "parent-old",
            "signed_at": NOW,
        }
    )
    await db["waiver_acceptances"].insert_one(
        {
            "academy_id": acad,
            "acceptance_id": "wa-1",
            "student_id": "st-alice",
            "parent_user_id": "parent-old",
            "accepted_at": NOW,
        }
    )

    await MongoStudentRepository(db).change_admin_student_parent("st-alice", _command())

    signature = await db["waiver_signatures"].find_one(
        {"academy_id": acad, "waiver_signature_id": "ws-1"}
    )
    acceptance = await db["waiver_acceptances"].find_one(
        {"academy_id": acad, "acceptance_id": "wa-1"}
    )
    assert signature["outdated_for_parent"] is True
    assert acceptance["outdated_for_parent"] is True


@pytest.mark.asyncio
async def test_change_parent_never_reaches_another_academys_rows(db, acad) -> None:
    await _seed_family(db, acad)
    await _seed_open_money(db, acad)
    # Same student id, same old parent id, different tenant.
    await db["invoices"].insert_one(
        {
            "academy_id": "other-academy",
            "invoice_id": "inv-other",
            "student_id": "st-alice",
            "parent_id": "parent-old",
            "status": "open",
            "balance_due_cents": 5000,
        }
    )
    await db["student_billing_enrollments"].insert_one(
        {
            "academy_id": "other-academy",
            "enrollment_id": "enr-other",
            "student_id": "st-alice",
            "parent_id": "parent-old",
            "session_type_id": "stype-1",
            # Would block the change if the guard leaked across tenants.
            "autopay_enrollment_status": "active",
        }
    )

    result = await MongoStudentRepository(db).change_admin_student_parent("st-alice", _command())

    assert result is not None
    other_invoice = await db["invoices"].find_one(
        {"academy_id": "other-academy", "invoice_id": "inv-other"}
    )
    other_billing = await db["student_billing_enrollments"].find_one(
        {"academy_id": "other-academy", "enrollment_id": "enr-other"}
    )
    assert other_invoice["parent_id"] == "parent-old"
    assert other_billing["parent_id"] == "parent-old"
