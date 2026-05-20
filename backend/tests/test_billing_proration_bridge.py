from __future__ import annotations

from datetime import datetime, timezone

from services.billing_proration import prorated_first_month_quote


def test_legacy_proration_bridge_uses_same_class_count_policy() -> None:
    session = {
        "_id": "sess-prorate",
        "monthly_price": 100.0,
        "start_date": "2026-05-01",
        "end_date": "2026-05-29",
        "days_of_week": ["Mon", "Fri"],
        "start_time": "18:00",
        "end_time": "19:00",
    }
    enrollment = {
        "_id": "enroll-1",
        "session_id": "sess-prorate",
        "created_at": datetime(2026, 5, 18, 15, 0, tzinfo=timezone.utc).isoformat(),
    }

    quote = prorated_first_month_quote(
        session=session,
        enrollment=enrollment,
        period="2026-05",
        calculated_at=datetime(2026, 5, 18, 22, 0, tzinfo=timezone.utc),
        calculated_by="SYSTEM",
    )

    assert quote is not None
    assert quote.final_amount_cents == 3333
    assert quote.total_eligible_classes == 9
    assert quote.billable_remaining_classes == 3
    assert quote.excluded_occurrences["sess-prorate:2026-05-18:18:00"] == "SAME_DAY_CUTOFF"
