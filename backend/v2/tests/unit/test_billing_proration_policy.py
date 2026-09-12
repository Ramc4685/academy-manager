from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.v2.contexts.billing.domain.proration import (
    BillingPeriod,
    ClassOccurrence,
    FirstMonthProrationPolicy,
    billable_classes_per_period,
    first_month_charge_description,
    quote_move_proration,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    _session_occurrences,
    _tuition_line_description,
)


def test_mid_month_proration_charges_remaining_eligible_classes() -> None:
    period = BillingPeriod.from_label("2026-05", timezone_name="America/Chicago")
    occurrences = [
        ClassOccurrence(
            occurrence_id=f"sess-1:2026-05-{day:02d}:18:00",
            session_id="sess-1",
            start_at=datetime(2026, 5, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, day + 1, 0, 0, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in (1, 5, 8, 12, 15, 19, 22, 26)
    ]

    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=10_000,
        discount_cents=0,
        period=period,
        occurrences=occurrences,
        billing_start_at=datetime(2026, 5, 18, 15, 0, tzinfo=UTC),
        calculated_at=datetime(2026, 5, 16, 15, 0, tzinfo=UTC),
        calculated_by="parent-1",
    )

    # Tue+Fri: the month lays out 8 classes, so one month of tuition buys 8
    # (4 per weekly meeting) at $12.50 each, not 4 at $25.
    assert quote.final_amount_cents == 3_750
    assert quote.total_eligible_classes == 8
    assert quote.billable_remaining_classes == 3
    assert quote.proration_ratio == "3/8"
    assert quote.included_occurrence_ids == [
        "sess-1:2026-05-19:18:00",
        "sess-1:2026-05-22:18:00",
        "sess-1:2026-05-26:18:00",
    ]


def test_backdated_elapsed_classes_are_excluded_with_audit_reason() -> None:
    period = BillingPeriod.from_label("2026-05", timezone_name="America/Chicago")
    occurrences = [
        ClassOccurrence(
            occurrence_id=f"sess-1:2026-05-{day:02d}:18:00",
            session_id="sess-1",
            start_at=datetime(2026, 5, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 5, day + 1, 0, 0, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in (1, 5, 8, 12, 15, 19, 22, 26)
    ]

    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=10_000,
        discount_cents=0,
        period=period,
        occurrences=occurrences,
        billing_start_at=datetime(2026, 5, 5, 15, 0, tzinfo=UTC),
        calculated_at=datetime(2026, 5, 16, 15, 0, tzinfo=UTC),
        calculated_by="admin-1",
    )

    assert quote.final_amount_cents == 3_750
    assert quote.excluded_occurrences["sess-1:2026-05-05:18:00"] == "ELAPSED_BEFORE_ENROLLMENT"
    assert quote.excluded_occurrences["sess-1:2026-05-08:18:00"] == "ELAPSED_BEFORE_ENROLLMENT"
    assert quote.excluded_occurrences["sess-1:2026-05-12:18:00"] == "ELAPSED_BEFORE_ENROLLMENT"


def _september_thursdays(cancelled_day: int | None = None) -> list[ClassOccurrence]:
    rows = []
    for day in (3, 10, 17, 24):
        off = day == cancelled_day
        rows.append(
            ClassOccurrence(
                occurrence_id=f"sess-1:2026-09-{day:02d}:18:00",
                session_id="sess-1",
                start_at=datetime(2026, 9, day, 23, 0, tzinfo=UTC),
                end_at=datetime(2026, 9, day + 1, 0, 0, tzinfo=UTC),
                status="cancelled" if off else "scheduled",
                is_billable=not off,
                timezone="America/Chicago",
            )
        )
    return rows


def test_a_cancelled_date_stays_in_the_denominator_but_never_the_numerator() -> None:
    """Issue #671. September: 4 Thursdays, $120. Sept 3 is called off, then a
    family enrolls on Sept 12 with Sept 17 and Sept 24 left.

    They must pay 120 * 2/4 = $60 — exactly what they would have paid had the
    cancellation never happened. Dropping the cancelled date from
    ``total_eligible_classes`` too would charge them 120 * 2/3 = $80, i.e.
    more per class because of a class they were never going to attend.
    """
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")
    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=12_000,
        discount_cents=0,
        period=period,
        occurrences=_september_thursdays(cancelled_day=3),
        billing_start_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        calculated_at=datetime(2026, 9, 12, 12, 0, tzinfo=UTC),
        calculated_by="parent-1",
    )

    assert quote.total_eligible_classes == 4
    assert quote.billable_remaining_classes == 2
    assert quote.final_amount_cents == 6_000
    assert quote.excluded_occurrences["sess-1:2026-09-03:18:00"] == "CLASS_CANCELLED"


def test_a_future_cancelled_date_is_never_charged_to_a_new_family() -> None:
    """The same quote taken BEFORE the cancelled date would have run: it must
    be excluded from the numerator, not silently billed (#671)."""
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")
    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=12_000,
        discount_cents=0,
        period=period,
        occurrences=_september_thursdays(cancelled_day=17),
        billing_start_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        calculated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        calculated_by="parent-1",
    )

    assert quote.total_eligible_classes == 4
    assert quote.billable_remaining_classes == 3
    assert "sess-1:2026-09-17:18:00" not in quote.included_occurrence_ids
    assert quote.final_amount_cents == 9_000


def _production_weekly_session_doc(**overrides: object) -> dict[str, object]:
    """A session doc shaped exactly like the production ones: a weekly template
    with ``days_of_week`` and wall-clock times, a stale one-off ``start_at``
    left over from the first-ever class, and NO ``start_date``/``end_date``.
    """
    doc: dict[str, object] = {
        "session_id": "sess-1",
        "days_of_week": ["Thu"],
        "start_time": "18:00",
        "end_time": "18:45",
        "timezone": "America/Chicago",
        "start_at": datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
        "end_at": datetime(2026, 9, 3, 23, 45, tzinfo=UTC),
        "status": "active",
    }
    doc.update(overrides)
    return doc


def test_weekly_recurrence_is_synthesised_without_start_and_end_dates() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(), period)

    assert [row.occurrence_id for row in rows] == [
        "sess-1:2026-09-03:18:00",
        "sess-1:2026-09-10:18:00",
        "sess-1:2026-09-17:18:00",
        "sess-1:2026-09-24:18:00",
    ]
    assert [row.start_at for row in rows] == [
        datetime(2026, 9, 3, 23, 0, tzinfo=UTC),
        datetime(2026, 9, 10, 23, 0, tzinfo=UTC),
        datetime(2026, 9, 17, 23, 0, tzinfo=UTC),
        datetime(2026, 9, 24, 23, 0, tzinfo=UTC),
    ]
    assert [row.end_at for row in rows] == [
        datetime(2026, 9, 3, 23, 45, tzinfo=UTC),
        datetime(2026, 9, 10, 23, 45, tzinfo=UTC),
        datetime(2026, 9, 17, 23, 45, tzinfo=UTC),
        datetime(2026, 9, 24, 23, 45, tzinfo=UTC),
    ]
    assert all(row.timezone == "America/Chicago" for row in rows)


def test_dateless_weekly_session_is_prorated_not_quoted_at_zero() -> None:
    """Production incident 2026-09-09: a parent self-registered for a weekly
    Thursday class and the first-month quote came back $0, so checkout skipped
    Stripe entirely. Synthesising only the stale one-off ``start_at`` left a
    single already-elapsed Sept 3 class, i.e. 0/1 remaining.
    """
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")
    occurrences = _session_occurrences(_production_weekly_session_doc(), period)

    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=7_000,
        discount_cents=0,
        period=period,
        occurrences=occurrences,
        billing_start_at=datetime(2026, 9, 9, 22, 0, tzinfo=UTC),
        calculated_at=datetime(2026, 9, 9, 22, 0, tzinfo=UTC),
        calculated_by="parent-1",
    )

    assert quote.total_eligible_classes == 4
    assert quote.billable_remaining_classes == 3
    assert quote.included_occurrence_ids == [
        "sess-1:2026-09-10:18:00",
        "sess-1:2026-09-17:18:00",
        "sess-1:2026-09-24:18:00",
    ]
    assert quote.final_amount_cents == 5_250


def test_start_and_end_dates_still_clamp_the_synthesised_recurrence() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(
        _production_weekly_session_doc(start_date="2026-09-01", end_date="2026-09-15"),
        period,
    )

    assert [row.occurrence_id for row in rows] == [
        "sess-1:2026-09-03:18:00",
        "sess-1:2026-09-10:18:00",
    ]


def test_session_without_days_of_week_keeps_the_single_occurrence_fallback() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(days_of_week=[]), period)

    assert [row.occurrence_id for row in rows] == ["sess-1:2026-09-03:18:00"]
    assert rows[0].start_at == datetime(2026, 9, 3, 23, 0, tzinfo=UTC)


def test_malformed_start_time_falls_back_instead_of_aborting_the_run() -> None:
    """A legacy doc with a non-ISO wall-clock time must not raise out of the
    monthly generation loop and starve every later family of an invoice."""
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(start_time="6:00 PM"), period)

    assert [row.occurrence_id for row in rows] == ["sess-1:2026-09-03:18:00"]


def test_malformed_end_time_falls_back_instead_of_aborting_the_run() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(end_time="quarter to seven"), period)

    assert [row.occurrence_id for row in rows] == ["sess-1:2026-09-03:18:00"]


def test_datetime_shaped_end_date_still_bounds_the_series() -> None:
    """``date.fromisoformat`` rejects `2026-09-15T00:00:00`; the bound is real."""
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(
        _production_weekly_session_doc(end_date="2026-09-15T00:00:00"), period
    )

    assert [row.occurrence_id for row in rows] == [
        "sess-1:2026-09-03:18:00",
        "sess-1:2026-09-10:18:00",
    ]


def test_unparseable_end_date_is_not_treated_as_unbounded() -> None:
    """An end_date we cannot read is an UNKNOWN bound, not 'runs forever' — the
    series must not be priced as a full month of phantom classes."""
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(end_date="09/15/2026"), period)

    assert [row.occurrence_id for row in rows] == ["sess-1:2026-09-03:18:00"]


def test_cancelled_weekly_template_synthesises_no_dates() -> None:
    """Cancel is a soft delete: the catalog synthesis and
    ``_series_occurrence_candidates`` both return nothing for a cancelled
    template, so billing must not invent four billable dates for it."""
    period = BillingPeriod.from_label("2026-10", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(status="cancelled"), period)

    assert rows == []


def test_completed_weekly_template_propagates_its_status() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(status="completed"), period)

    assert {row.status for row in rows} == {"completed"}
    assert all(row.is_billable for row in rows)


def test_short_weekday_label_falls_back_instead_of_quoting_zero() -> None:
    """An admin PATCH storing ``["Th"]`` verbatim used to yield no occurrences
    at all, i.e. the exact $0 free-enrollment incident with no fallback."""
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(days_of_week=["Th"]), period)

    assert [row.occurrence_id for row in rows] == ["sess-1:2026-09-03:18:00"]


def test_integer_weekday_indexes_are_expanded_like_labels() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")

    rows = _session_occurrences(_production_weekly_session_doc(days_of_week=[3]), period)

    assert [row.occurrence_id for row in rows] == [
        "sess-1:2026-09-03:18:00",
        "sess-1:2026-09-10:18:00",
        "sess-1:2026-09-17:18:00",
        "sess-1:2026-09-24:18:00",
    ]


def test_unrecognised_weekday_quote_is_never_zero_for_a_new_family() -> None:
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")
    occurrences = _session_occurrences(
        _production_weekly_session_doc(
            days_of_week=["Th"],
            start_at=datetime(2026, 9, 24, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 9, 24, 23, 45, tzinfo=UTC),
        ),
        period,
    )

    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=7_000,
        discount_cents=0,
        period=period,
        occurrences=occurrences,
        billing_start_at=datetime(2026, 9, 9, 22, 0, tzinfo=UTC),
        calculated_at=datetime(2026, 9, 9, 22, 0, tzinfo=UTC),
        calculated_by="parent-1",
    )

    assert quote.total_eligible_classes == 1
    assert quote.final_amount_cents == 1_750


_OCTOBER_THURSDAYS = (1, 8, 15, 22, 29)


def _october_weekly(total: int) -> list[ClassOccurrence]:
    return [
        ClassOccurrence(
            occurrence_id=f"sess-1:2026-10-{day:02d}:18:00",
            session_id="sess-1",
            start_at=datetime(2026, 10, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 10, day + 1, 0, 0, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in _OCTOBER_THURSDAYS[:total]
    ]


def _joins_with(total: int, remaining: int) -> datetime:
    skipped = total - remaining
    if skipped == 0:
        return datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    return datetime(2026, 10, _OCTOBER_THURSDAYS[skipped - 1] + 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("total", "remaining", "expected_cents", "expected_ratio"),
    [
        (5, 5, 7_000, "4/4"),
        (5, 4, 7_000, "4/4"),
        (5, 3, 5_250, "3/4"),
        (5, 2, 3_500, "2/4"),
        (5, 1, 1_750, "1/4"),
        (4, 3, 5_250, "3/4"),
        (4, 0, 0, "0/4"),
    ],
)
def test_monthly_price_always_buys_four_classes(
    total: int,
    remaining: int,
    expected_cents: int,
    expected_ratio: str,
) -> None:
    """The monthly tuition buys 4 classes, so the per-class rate is price/4 in a
    4-class month and in a 5-class month alike — the 5th class is free."""
    period = BillingPeriod.from_label("2026-10", timezone_name="America/Chicago")
    joined_at = _joins_with(total, remaining)

    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=7_000,
        discount_cents=0,
        period=period,
        occurrences=_october_weekly(total),
        billing_start_at=joined_at,
        calculated_at=joined_at,
        calculated_by="parent-1",
    )

    assert quote.total_eligible_classes == total
    assert quote.billable_remaining_classes == remaining
    assert quote.final_amount_cents == expected_cents
    assert quote.proration_ratio == expected_ratio


def _october_quote(total: int, remaining: int, price_cents: int = 7_000):
    joined_at = _joins_with(total, remaining)
    return FirstMonthProrationPolicy().quote(
        monthly_price_cents=price_cents,
        discount_cents=0,
        period=BillingPeriod.from_label("2026-10", timezone_name="America/Chicago"),
        occurrences=_october_weekly(total),
        billing_start_at=joined_at,
        calculated_at=joined_at,
        calculated_by="parent-1",
    )


def test_prorated_first_month_copy_names_the_four_class_rate() -> None:
    assert first_month_charge_description(3) == (
        "3 of 4 classes — monthly rate covers 4 classes; any additional class in the month is free."
    )
    assert _tuition_line_description("2026-10", _october_quote(5, 3)) == (
        "Monthly tuition 2026-10: 3 of 4 classes — monthly rate covers 4 classes; "
        "any additional class in the month is free."
    )


def test_full_price_copy_names_the_free_fifth_class() -> None:
    assert first_month_charge_description(4) == "Monthly tuition (4 classes; 5th class free)"
    assert first_month_charge_description(5) == "Monthly tuition (4 classes; 5th class free)"
    assert _tuition_line_description("2026-10", _october_quote(5, 5)) == (
        "Monthly tuition 2026-10 (4 classes; 5th class free)"
    )


def test_full_month_line_does_not_claim_the_four_class_rule() -> None:
    """A flat full month was not priced by the first-month rule.

    ``billable_classes=None`` is the full-month, prior-consumed and one-off
    path; stamping "4 classes; 5th class free" there tells a Mon+Wed family
    they bought 4 of the 8 classes that will run, and a one-off family that
    their single date buys 4.
    """
    assert _tuition_line_description("2026-10", None) == "Monthly tuition 2026-10"


# ---------------------------------------------------------------------------
# Multi-day sessions: 4 classes per WEEKLY MEETING.
# ---------------------------------------------------------------------------


def _september_mon_wed() -> list[ClassOccurrence]:
    """September 2026 Mondays + Wednesdays: 8 class dates."""
    days = (2, 7, 9, 14, 16, 21, 23, 28)  # Wed 2, Mon 7, Wed 9, ...
    return [
        ClassOccurrence(
            occurrence_id=f"sess-2:2026-09-{day:02d}:18:00",
            session_id="sess-2",
            start_at=datetime(2026, 9, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 9, day + 1, 0, 0, tzinfo=UTC),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in days
    ]


def test_twice_weekly_session_sells_eight_classes_a_month() -> None:
    assert billable_classes_per_period(_september_mon_wed(), timezone_name="America/Chicago") == 8


def test_twice_weekly_joiner_is_not_charged_a_full_month_for_five_of_eight() -> None:
    """$200 Mon+Wed session, 8 dates, parent joins with 5 left.

    Capping at 4 classes would charge the full $200 for 5 of 8 classes.
    """
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")
    joined_at = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)  # after Sep 2, 7, 9

    quote = FirstMonthProrationPolicy().quote(
        monthly_price_cents=20_000,
        discount_cents=0,
        period=period,
        occurrences=_september_mon_wed(),
        billing_start_at=joined_at,
        calculated_at=joined_at,
        calculated_by="parent-1",
    )

    assert quote.total_eligible_classes == 8
    assert quote.billable_remaining_classes == 5
    assert quote.proration_ratio == "5/8"
    assert quote.final_amount_cents == 12_500


# ---------------------------------------------------------------------------
# Mid-period move (#678) re-prices at the same per-class rate.
# ---------------------------------------------------------------------------


def test_move_reprices_at_the_rate_the_first_month_was_charged_at() -> None:
    """5-class month: $100 session -> $200 session with 3 classes left.

    The family paid 100 * 3/4 = $75. Pricing the move at ``remaining/total``
    would quote the $200 session at 200 * 3/5 = $120 — a per-class rate nobody
    was ever charged — leaving the enrollment $15 short of the $150 that
    session's first month costs.
    """
    period = BillingPeriod.from_label("2026-10", timezone_name="America/Chicago")
    effective_at = _joins_with(5, 3)
    occurrences = _october_weekly(5)

    quote = quote_move_proration(
        period=period,
        from_session_id="sess-a",
        to_session_id="sess-b",
        from_price_cents=10_000,
        to_price_cents=20_000,
        from_occurrences=occurrences,
        to_occurrences=occurrences,
        effective_at=effective_at,
    )

    assert quote.from_remaining_classes == 3
    assert quote.from_share_cents == 7_500
    assert quote.to_share_cents == 15_000
    assert quote.delta_cents == 7_500
