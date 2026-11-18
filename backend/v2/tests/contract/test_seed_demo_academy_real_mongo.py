"""The Demo Academy seed against a real mongod with every migration's validators."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from backend.scripts.seed_demo_academy import (
    DEMO_ACADEMY_ID,
    PERSONAS,
    DemoScopeError,
    require_demo,
    seed,
)

NOW = datetime(2026, 11, 18, 18, 0, tzinfo=UTC)
BLNO = "acad_blno_badminton"


def _fake_login(email: str, password: str, display_name: str) -> str:
    assert password == "demo-pass-123"
    return f"fb_{email.split('@')[0]}"


async def _apply(db: Any) -> dict[str, int]:
    return await seed(db, apply=True, password="demo-pass-123", ensure_login=_fake_login, now=NOW)


async def _counts(db: Any) -> dict[str, int]:
    return {
        name: await db[name].count_documents({})
        for name in sorted(await db.list_collection_names())
        if not name.startswith("system.")
    }


async def test_dry_run_writes_nothing(real_db: Any) -> None:
    def _no_login(*_: str) -> str:
        raise AssertionError("dry run must not touch Firebase")

    plan = await seed(real_db, apply=False, ensure_login=_no_login, now=NOW)

    assert plan["academy_memberships"] == 4
    assert sum((await _counts(real_db)).values()) == 0


async def test_apply_seeds_the_demo_academy(real_db: Any) -> None:
    await _apply(real_db)

    academy = await real_db["academies"].find_one({"academy_id": DEMO_ACADEMY_ID})
    assert academy["slug"] == "demo-academy"
    assert academy["primary_domain"] == "demo-academy.courtmastr.com"
    domain = await real_db["academy_domains"].find_one({"domain": "demo-academy.courtmastr.com"})
    assert (domain["academy_id"], domain["status"]) == (DEMO_ACADEMY_ID, "verified")

    roles = {}
    for persona, (email, _, _) in PERSONAS.items():
        user = await real_db["users"].find_one({"normalized_email": email})
        assert user["firebase_uid"] == f"fb_{email.split('@')[0]}"
        membership = await real_db["academy_memberships"].find_one(
            {"academy_id": DEMO_ACADEMY_ID, "user_id": user["user_id"], "status": "active"}
        )
        roles[persona] = membership["roles"]
    assert roles == {
        "owner": ["owner", "admin"],
        "admin": ["admin"],
        "coach": ["coach"],
        "parent": ["parent"],
    }

    parent = await real_db["users"].find_one({"normalized_email": "demo.parent@example.com"})
    coach = await real_db["users"].find_one({"normalized_email": "demo.coach@example.com"})
    sam = await real_db["students"].find_one({"student_id": "demo_student_sam"})
    assert sam["parent_id"] == parent["user_id"]
    assert await real_db["sessions"].count_documents({"coach_id": coach["user_id"]}) == 2
    assert await real_db["enrollments"].count_documents({"status": "active"}) == 3
    occurrences = real_db["session_occurrences"]
    assert await occurrences.count_documents({"status": "completed"}) >= 7
    assert await occurrences.count_documents({"status": "scheduled"}) >= 7

    statuses = await real_db["attendance"].distinct("status")
    assert set(statuses) == {"present", "late", "absent"}
    starts = {doc["occurrence_id"]: doc["start_at"] async for doc in occurrences.find({})}
    async for row in real_db["attendance"].find({}):
        assert row["marked_at"] == starts[row["occurrence_id"]]
    # Both classes read at their Chicago wall time, across the DST change too.
    for session_id, wall in (("demo_session_wed", (17, 30)), ("demo_session_sat", (9, 0))):
        async for row in real_db["attendance"].find({"session_id": session_id}):
            local = row["marked_at"].replace(tzinfo=UTC).astimezone(ZoneInfo("America/Chicago"))
            assert (local.hour, local.minute) == wall

    # Every invoice paid (no pay button can appear), each with its cash payment.
    invoices = [doc async for doc in real_db["invoices"].find({})]
    assert {doc["period"] for doc in invoices} == {"2026-10", "2026-11"}
    assert len(invoices) == 4
    assert all(doc["parent_id"] == parent["user_id"] for doc in invoices)
    assert all((d["status"], d["balance_due_cents"]) == ("paid", 0) for d in invoices)
    allocated = await real_db["payment_allocations"].distinct("invoice_id")
    assert sorted(allocated) == sorted(doc["invoice_id"] for doc in invoices)
    assert await real_db["ledger_payments"].count_documents({"payment_method": "cash"}) == 4

    # Nothing for the parent profile's completeness banner to ask for.
    assert parent["phone"] and parent["email_confirmed_at"]
    async for child in real_db["students"].find({}):
        for field in (
            "date_of_birth",
            "emergency_contact_name",
            "emergency_contact_phone",
            "medical_notes",
        ):
            assert child[field], field
    # Nothing that could charge: no Stripe customer, card or autopay anywhere.
    for name in ("parent_billing_customers", "parent_payment_methods", "autopay_consents"):
        assert await real_db[name].count_documents({}) == 0
    suppressed = await real_db["email_suppressions"].distinct("email", {"reason": "hard_bounce"})
    assert set(suppressed) == {email for email, _, _ in PERSONAS.values()}


async def test_second_apply_restores_the_seeded_state(real_db: Any) -> None:
    await _apply(real_db)
    seeded = await _counts(real_db)

    # A reviewer drops the coach's access and adds an invoice.
    coach = await real_db["users"].find_one({"normalized_email": "demo.coach@example.com"})
    await real_db["academy_memberships"].delete_one({"user_id": coach["user_id"]})
    await real_db["invoices"].update_one(
        {"invoice_id": "demo_invoice_alex_2026_11"},
        {"$set": {"status": "open", "balance_due_cents": 8000}},
    )
    stray = await real_db["invoices"].find_one(
        {"invoice_id": "demo_invoice_sam_2026_11"}, {"_id": 0}
    )
    await real_db["invoices"].insert_one(
        {**stray, "invoice_id": "stray", "invoice_number": "STRAY-1"}
    )
    await _apply(real_db)

    assert await _counts(real_db) == seeded
    alex = await real_db["invoices"].find_one({"invoice_id": "demo_invoice_alex_2026_11"})
    assert (alex["status"], alex["balance_due_cents"]) == ("paid", 0)


async def test_writes_only_the_demo_academy(real_db: Any) -> None:
    await real_db["academies"].insert_one(
        {"academy_id": BLNO, "slug": "blno-academy", "display_name": "BLNO"}
    )
    await real_db["students"].insert_one(
        {"academy_id": BLNO, "student_id": "blno_kid", "parent_id": "blno_parent"}
    )

    await _apply(real_db)

    for name in await real_db.list_collection_names():
        foreign = await real_db[name].count_documents(
            {"academy_id": {"$exists": True, "$nin": [DEMO_ACADEMY_ID, BLNO]}}
        )
        assert foreign == 0, name
    assert await real_db["students"].count_documents({"academy_id": BLNO}) == 1
    assert await real_db["academies"].count_documents({"academy_id": BLNO, "slug": "blno-academy"})


async def test_refuses_a_demo_slug_owned_by_another_academy(real_db: Any) -> None:
    await real_db["academies"].insert_one(
        {"academy_id": "acad_other", "slug": "demo-academy", "display_name": "Other"}
    )

    with pytest.raises(DemoScopeError):
        await _apply(real_db)

    assert await real_db["users"].count_documents({}) == 0
    assert await real_db["academy_memberships"].count_documents({}) == 0


def test_require_demo_refuses_other_academies() -> None:
    require_demo(DEMO_ACADEMY_ID)
    for other in (BLNO, "acad_other", None):
        with pytest.raises(DemoScopeError):
            require_demo(other)
