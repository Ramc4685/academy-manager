from __future__ import annotations

import pytest

from backend.v2.contexts.billing.application.use_cases.tuition_discounts import (
    MongoTuitionDiscountBackfillCandidateQuery,
)


@pytest.mark.asyncio
async def test_lists_below_price_enrollments_without_active_discount_read_only(db, acad) -> None:
    await db["sessions"].insert_many(
        [
            {
                "academy_id": acad,
                "session_id": "sess-full",
                "title": "Junior Badminton",
                "monthly_price_cents": 10_000,
            },
            {
                "academy_id": acad,
                "session_id": "sess-other",
                "title": "Tournament Team",
                "price_cents": 12_000,
            },
            {
                "academy_id": "other-academy",
                "session_id": "sess-full",
                "title": "Other Tenant",
                "monthly_price_cents": 10_000,
            },
        ]
    )
    await db["enrollments"].insert_many(
        [
            {
                "academy_id": acad,
                "enrollment_id": "enr-candidate",
                "student_id": "stu-candidate",
                "session_id": "sess-full",
                "status": "active",
                "amount_cents": 8_000,
                "payment_mode": "monthly",
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-policy",
                "student_id": "stu-policy",
                "session_id": "sess-full",
                "status": "active",
                "amount_cents": 7_000,
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-at-price",
                "student_id": "stu-at-price",
                "session_id": "sess-full",
                "status": "active",
                "amount_cents": 10_000,
            },
            {
                "academy_id": acad,
                "enrollment_id": "enr-deleted",
                "student_id": "stu-deleted",
                "session_id": "sess-other",
                "status": "active",
                "amount_cents": 5_000,
                "is_deleted": True,
            },
            {
                "academy_id": "other-academy",
                "enrollment_id": "enr-other-tenant",
                "student_id": "stu-other-tenant",
                "session_id": "sess-full",
                "status": "active",
                "amount_cents": 5_000,
            },
        ]
    )
    await db["enrollment_discounts"].insert_one(
        {
            "academy_id": acad,
            "discount_id": "disc-policy",
            "enrollment_id": "enr-policy",
            "student_id": "stu-policy",
            "category": "scholarship",
            "kind": "waiver",
            "effective_start": "2026-06-01",
            "status": "active",
        }
    )
    counts_before = {
        name: await db[name].count_documents({})
        for name in ("sessions", "enrollments", "enrollment_discounts")
    }

    result = await MongoTuitionDiscountBackfillCandidateQuery(db).execute()

    assert [row.enrollment_id for row in result.candidates] == ["enr-candidate"]
    candidate = result.candidates[0]
    assert candidate.student_id == "stu-candidate"
    assert candidate.session_id == "sess-full"
    assert candidate.session_title == "Junior Badminton"
    assert candidate.billed_cents == 8_000
    assert candidate.session_price_cents == 10_000
    assert candidate.delta_cents == 2_000
    assert candidate.payment_mode == "monthly"
    counts_after = {
        name: await db[name].count_documents({})
        for name in ("sessions", "enrollments", "enrollment_discounts")
    }
    assert counts_after == counts_before
