"""S59: a coach reads only their own classes taught and released payslips."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.v2.composition.coach_pay import compose_coach_pay
from backend.v2.contexts.finance.application.use_cases.coach_pay_summary import (
    InvalidPayMonth,
    allowed_month,
)

ACADEMY = "test-academy"
NOW = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)


def _occ(occ_id: str, day: int, **extra: Any) -> dict[str, Any]:
    return {
        "occurrence_id": occ_id,
        "academy_id": ACADEMY,
        "session_id": "ses_tue",
        "start_at": datetime(2026, 11, day, 23, 30, tzinfo=UTC),
        "end_at": datetime(2026, 11, day + 1, 0, 30, tzinfo=UTC),
        "status": "scheduled",
        **extra,
    }


def _period(coach: str, status: str, start: datetime, end: datetime, **extra: Any) -> dict:
    return {
        "payout_period_id": f"pp_{coach}_{status}_{start:%m}",
        "academy_id": ACADEMY,
        "coach_id": coach,
        "status": status,
        "period_start": start,
        "period_end": end,
        "total_minor": 12345,
        "currency": "USD",
        "approved_at": datetime(2026, 11, 2, 15, tzinfo=UTC),
        "lines": [{"rate_id": "rate_secret", "percent_bps": 4000, "amount_minor": 999}],
        **extra,
    }


async def _seed(db: Any) -> None:
    await db["academies"].insert_one(
        {"academy_id": ACADEMY, "name": "Demo Academy", "timezone": "America/Chicago"}
    )
    await db["sessions"].insert_one(
        {"session_id": "ses_tue", "academy_id": ACADEMY, "title": "Tuesday Intermediate"}
    )
    await db["session_occurrences"].insert_many(
        [
            _occ("o_lead", 3, scheduled_coach_id="casey"),
            _occ("o_cover", 10, scheduled_coach_id="demo", substitute_coach_id="casey"),
            _occ("o_asst", 17, scheduled_coach_id="demo", assistant_coach_ids=["casey"]),
            _occ("o_cancel", 4, scheduled_coach_id="casey", status="cancelled"),
            _occ("o_future", 28, scheduled_coach_id="casey"),
            _occ("o_other", 5, scheduled_coach_id="demo"),
            # Another academy's class with the same coach id never counts.
            {**_occ("o_elsewhere", 6, scheduled_coach_id="casey"), "academy_id": "other"},
        ]
    )
    oct_start = datetime(2026, 10, 1, 5, tzinfo=UTC)
    nov_start = datetime(2026, 11, 1, 5, tzinfo=UTC)
    dec_start = datetime(2026, 12, 1, 6, tzinfo=UTC)
    await db["payout_periods"].insert_many(
        [
            _period("casey", "draft", nov_start, dec_start),
            _period(
                "casey",
                "paid",
                oct_start,
                nov_start,
                paid_at=datetime(2026, 11, 5, 15, tzinfo=UTC),
                paid_method="bank_transfer",
                paid_amount_minor=12000,
            ),
            _period("demo", "approved", nov_start, dec_start, total_minor=77777),
            {
                **_period("casey", "approved", nov_start, dec_start),
                "academy_id": "other",
                "payout_period_id": "pp_elsewhere",
            },
        ]
    )


def _use_case(db: Any):
    return compose_coach_pay(db, clock=lambda: NOW)


@pytest.mark.asyncio
async def test_coach_sees_only_their_held_classes_with_role(db: Any, acad: str) -> None:
    await _seed(db)
    summary = await _use_case(db).execute(academy_id=ACADEMY, coach_id="casey", month=None)

    assert summary.month == "2026-11" and summary.month_label == "November 2026"
    assert [(c.occurrence_id, c.role) for c in summary.classes] == [
        ("o_asst", "assistant"),
        ("o_cover", "cover"),
        ("o_lead", "lead"),
    ]
    assert summary.classes_taught == 3 and summary.minutes_taught == 180
    assert {c.class_name for c in summary.classes} == {"Tuesday Intermediate"}


@pytest.mark.asyncio
async def test_a_draft_is_never_returned_and_another_coach_payslip_never_leaks(
    db: Any, acad: str
) -> None:
    await _seed(db)
    summary = await _use_case(db).execute(academy_id=ACADEMY, coach_id="casey", month="2026-11")
    # Casey's November period is a draft; Demo's approved one and the other
    # academy's approved one must not stand in for it.
    assert summary.payslip is None


@pytest.mark.asyncio
async def test_paid_payslip_shows_paid_fields_and_nothing_about_rates(db: Any, acad: str) -> None:
    await _seed(db)
    summary = await _use_case(db).execute(academy_id=ACADEMY, coach_id="casey", month="2026-10")

    slip = summary.payslip
    assert slip is not None and slip.status == "paid"
    assert (slip.period_start, slip.period_end) == (date(2026, 10, 1), date(2026, 10, 31))
    assert slip.total_cents == 12345 and slip.paid_amount_cents == 12000
    assert slip.paid_on == date(2026, 11, 5) and slip.paid_method_label == "bank transfer"
    assert slip.currency == "usd"
    dumped = str(summary.model_dump())
    for secret in ("rate_secret", "percent_bps", "amount_minor", "lines", "revenue"):
        assert secret not in dumped


@pytest.mark.asyncio
async def test_approved_payslip_hides_paid_fields(db: Any, acad: str) -> None:
    await _seed(db)
    summary = await _use_case(db).execute(academy_id=ACADEMY, coach_id="demo", month="2026-11")
    slip = summary.payslip
    assert slip is not None and slip.status == "approved" and slip.total_cents == 77777
    assert slip.paid_on is None and slip.paid_amount_cents is None
    assert slip.paid_method_label is None


def test_month_range_is_the_last_two_years() -> None:
    today = date(2026, 11, 26)
    assert allowed_month(None, today=today) == "2026-11"
    assert allowed_month("2024-12", today=today) == "2024-12"
    for bad in ("2024-11", "2026-12", "2026-13", "2026-00", "26-11"):
        with pytest.raises(InvalidPayMonth):
            allowed_month(bad, today=today)


@pytest.mark.asyncio
async def test_a_neighbouring_period_that_only_grazes_the_month_is_not_its_payslip(
    db: Any, acad: str
) -> None:
    """Periods stored on UTC month bounds overlap the academy's month by a few
    hours on each side; October must show October's payslip, not November's."""
    await _seed(db)
    await db["payout_periods"].delete_many({"coach_id": "casey"})
    await db["payout_periods"].insert_many(
        [
            _period(
                "casey",
                "approved",
                datetime(2026, 10, 1, tzinfo=UTC),
                datetime(2026, 11, 1, tzinfo=UTC),
                total_minor=1000,
            ),
            _period(
                "casey",
                "approved",
                datetime(2026, 11, 1, tzinfo=UTC),
                datetime(2026, 12, 1, tzinfo=UTC),
                total_minor=2000,
                payout_period_id="pp_nov_utc",
            ),
        ]
    )
    use_case = _use_case(db)
    october = await use_case.execute(academy_id=ACADEMY, coach_id="casey", month="2026-10")
    november = await use_case.execute(academy_id=ACADEMY, coach_id="casey", month="2026-11")
    assert october.payslip is not None and october.payslip.total_cents == 1000
    assert november.payslip is not None and november.payslip.total_cents == 2000


@pytest.mark.asyncio
async def test_a_grazing_neighbour_alone_is_not_the_months_payslip(db: Any, acad: str) -> None:
    """October's own period is still a draft; November's approved slip on UTC
    bounds grazes October by hours and must not stand in for it."""
    await _seed(db)
    await db["payout_periods"].delete_many({"coach_id": "casey"})
    await db["payout_periods"].insert_many(
        [
            _period(
                "casey",
                "draft",
                datetime(2026, 10, 1, tzinfo=UTC),
                datetime(2026, 11, 1, tzinfo=UTC),
                total_minor=1000,
            ),
            _period(
                "casey",
                "approved",
                datetime(2026, 11, 1, tzinfo=UTC),
                datetime(2026, 12, 1, tzinfo=UTC),
                total_minor=2000,
                payout_period_id="pp_nov_utc",
            ),
        ]
    )
    use_case = _use_case(db)
    october = await use_case.execute(academy_id=ACADEMY, coach_id="casey", month="2026-10")
    november = await use_case.execute(academy_id=ACADEMY, coach_id="casey", month="2026-11")
    assert october.payslip is None
    assert november.payslip is not None and november.payslip.total_cents == 2000
