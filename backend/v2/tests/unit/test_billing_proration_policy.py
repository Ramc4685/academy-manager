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
