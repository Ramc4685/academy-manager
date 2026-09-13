"""The manual "Bill this month" path must price a month like the generator (#724).

``MongoEnrollmentBillingTargetReader`` used to quote the flat session price, so a
hand-billed first month charged the family full tuition where the monthly run (and
the checkout quote) would prorate, apply the #721 four-classes-per-meeting rule, and
stamp a ``billing_calculation_snapshots`` row that later withdrawal/cancellation
credits are measured against.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from backend.v2.contexts.billing.domain.tuition_discount import TuitionDiscount
from backend.v2.contexts.billing.infrastructure.mongo_enrollment_billing_target import (
    MongoEnrollmentBillingTargetReader,
)
from backend.v2.contexts.billing.infrastructure.mongo_tuition_discount_repo import (
    MongoTuitionDiscountRepository,
)

#: Mon+Fri through May 2026 → 9 dates, so the month sells 8 classes (4 per weekly
#: meeting) at $12.50 and the 9th is free. The same session the generator's own
#: proration contract test uses, so both paths can be compared number for number.
_RUN_AT = datetime(2026, 5, 18, 22, 0, tzinfo=UTC)


async def _seed(db, acad: str, *, billing_start: datetime, status: str = "active") -> None:
    await db["sessions"].insert_one(
        {
            "academy_id": acad,
            "session_id": "sess-prorate",
            "name": "Junior Badminton",
            "title": "Junior Badminton",
            "coach_id": "coach-1",
            "location": "Court 1",
            "start_date": "2026-05-01",
            "end_date": "2026-05-29",
            "days_of_week": ["Mon", "Fri"],
            "start_time": "18:00",
            "end_time": "19:00",
            "monthly_price_cents": 10_000,
            "capacity": 8,
            "status": "active",
        }
    )
    await db["students"].insert_one(
        {
            "academy_id": acad,
            "student_id": "student-1",
            "parent_id": "parent-1",
            "full_name": "A Student",
        }
    )
    await db["enrollments"].insert_one(
        {
            "academy_id": acad,
            "enrollment_id": "enroll-1",
            "session_id": "sess-prorate",
            "student_id": "student-1",
            "parent_id": "parent-1",
            "status": status,
            "billing_type": "standard",
            "billing_start_at": billing_start,
            "created_at": billing_start,
        }
    )


def _reader(db):
    return MongoEnrollmentBillingTargetReader(db, clock=lambda: _RUN_AT)


@pytest.mark.asyncio
async def test_first_month_is_prorated_and_stamps_a_consumed_snapshot(db, acad) -> None:
    await _seed(db, acad, billing_start=datetime(2026, 5, 18, 15, 0, tzinfo=UTC))

    target = await _reader(db).load("enroll-1", "2026-05")

    assert target is not None
    # 3 of the month's 8 billable classes remain → 10_000 * 3/8, not the flat price.
    assert target.monthly_price_cents == 3_750
    assert target.monthly_discount_cents == 0
    assert target.tuition_description is not None
    assert "3 of 8 classes" in target.tuition_description

    snapshot = await db["billing_calculation_snapshots"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-1"}
    )
    assert snapshot is not None
    assert snapshot["calculation_type"] == "FIRST_MONTH_PRORATION"
    assert snapshot["status"] == "CONSUMED"
    assert snapshot["billing_period_label"] == "2026-05"
    assert snapshot["billable_remaining_classes"] == 3


@pytest.mark.asyncio
async def test_first_month_proration_is_net_of_an_active_discount(db, acad) -> None:
    await _seed(db, acad, billing_start=datetime(2026, 5, 18, 15, 0, tzinfo=UTC))
    await MongoTuitionDiscountRepository(db).set_active(
        TuitionDiscount(
            discount_id="disc-1",
            enrollment_id="enroll-1",
            student_id="student-1",
            category="sibling",
            kind="percent",
            percent_bps=2_000,
            effective_start=date(2026, 1, 1),
        ),
        set_by="admin-1",
    )

    target = await _reader(db).load("enroll-1", "2026-05")

    assert target is not None
    # Gross is the undiscounted proration; net (10_000 - 20% = 8_000, prorated 3/8)
    # is 3_000, so the discount line carries the difference — the generator's math.
    assert target.monthly_price_cents == 3_750
    assert target.monthly_discount_cents == 750
    assert target.discount_description == "Sibling discount"
    assert target.discount_id == "disc-1"


@pytest.mark.asyncio
async def test_a_continuing_month_still_bills_the_flat_price_with_the_class_rule(db, acad) -> None:
    await _seed(db, acad, billing_start=datetime(2026, 4, 1, 15, 0, tzinfo=UTC))

    target = await _reader(db).load("enroll-1", "2026-05")

    assert target is not None
    assert target.monthly_price_cents == 10_000
    assert target.tuition_description == "Monthly tuition 2026-05 (8 classes; extra classes free)"

    snapshot = await db["billing_calculation_snapshots"].find_one(
        {"academy_id": acad, "enrollment_id": "enroll-1"}
    )
    assert snapshot is not None
    assert snapshot["calculation_type"] == "MONTHLY_TUITION"


@pytest.mark.asyncio
async def test_a_month_already_prorated_at_checkout_is_not_billed_again(db, acad) -> None:
    await _seed(db, acad, billing_start=datetime(2026, 5, 18, 15, 0, tzinfo=UTC))
    first = await _reader(db).load("enroll-1", "2026-05")
    assert first is not None and first.monthly_price_cents == 3_750

    second = await _reader(db).load("enroll-1", "2026-05")

    # The CONSUMED snapshot from the first resolution is the generator's
    # "already charged" signal, so a second hand-bill has nothing left to charge
    # and BillEnrollmentPeriod refuses it rather than double-charging.
    assert second is not None
    assert second.monthly_price_cents == 0
    assert (
        await db["billing_calculation_snapshots"].count_documents(
            {"academy_id": acad, "enrollment_id": "enroll-1"}
        )
        == 1
    )


@pytest.mark.asyncio
async def test_a_non_active_enrollment_is_not_priced_and_burns_no_snapshot(db, acad) -> None:
    await _seed(db, acad, billing_start=datetime(2026, 5, 18, 15, 0, tzinfo=UTC), status="paused")

    target = await _reader(db).load("enroll-1", "2026-05")

    # The use case rejects a paused enrollment; resolving it anyway would stamp a
    # CONSUMED first-month snapshot the monthly run would then read as "already
    # charged" and bill $0 against.
    assert target is not None
    assert target.status == "paused"
    assert await db["billing_calculation_snapshots"].count_documents({"academy_id": acad}) == 0
