from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.proration import (
    BillingPeriod,
    ClassOccurrence,
    FirstMonthProrationPolicy,
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
