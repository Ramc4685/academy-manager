"""Issue #669: price delta for the rest of the period when a student moves sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.domain.proration import (
    BillingPeriod,
    ClassOccurrence,
    quote_move_proration,
    remaining_share_cents,
)

TZ = "America/Chicago"
PERIOD = BillingPeriod.from_label("2026-09", timezone_name=TZ)


def _occ(session_id: str, day: int, *, status: str = "scheduled", billable: bool = True):
    start = datetime(2026, 9, day, 18, 0, tzinfo=ZoneInfo(TZ))
    return ClassOccurrence(
        occurrence_id=f"{session_id}:2026-09-{day:02d}:18:00",
        session_id=session_id,
        start_at=start.astimezone(UTC),
        end_at=start.astimezone(UTC),
        status=status,  # type: ignore[arg-type]
        is_billable=billable,
        timezone=TZ,
    )


EFFECTIVE = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)


def test_remaining_share_counts_classes_from_effective_date() -> None:
    occurrences = [_occ("a", d) for d in (5, 12, 19, 26)]
    share, remaining, total = remaining_share_cents(
        monthly_price_cents=8000, period=PERIOD, occurrences=occurrences, effective_at=EFFECTIVE
    )
    assert (share, remaining, total) == (6000, 3, 4)


def test_remaining_share_rounds_half_up_on_final_cent() -> None:
    # 7000 * 6 / 9 = 4666.66… → 4667
    occurrences = [_occ("a", d) for d in (1, 3, 8, 10, 15, 17, 22, 24, 29)]
    share, remaining, total = remaining_share_cents(
        monthly_price_cents=7000, period=PERIOD, occurrences=occurrences, effective_at=EFFECTIVE
    )
    assert (remaining, total) == (6, 9)
    assert share == 4667


def test_remaining_share_ignores_cancelled_holiday_and_non_billable_classes() -> None:
    occurrences = [
        _occ("a", 5),
        _occ("a", 12, status="canceled"),
        _occ("a", 19, status="holiday"),
        _occ("a", 26, billable=False),
        _occ("a", 28),
    ]
    share, remaining, total = remaining_share_cents(
        monthly_price_cents=1000, period=PERIOD, occurrences=occurrences, effective_at=EFFECTIVE
    )
    assert (share, remaining, total) == (500, 1, 2)


def test_remaining_share_is_zero_for_empty_schedule_or_elapsed_classes() -> None:
    assert remaining_share_cents(
        monthly_price_cents=1000, period=PERIOD, occurrences=[], effective_at=EFFECTIVE
    ) == (0, 0, 0)
    elapsed = [_occ("a", 1), _occ("a", 3)]
    assert remaining_share_cents(
        monthly_price_cents=1000, period=PERIOD, occurrences=elapsed, effective_at=EFFECTIVE
    ) == (0, 0, 2)


def test_quote_delta_is_new_share_minus_old_share() -> None:
    quote = quote_move_proration(
        period=PERIOD,
        from_session_id="a",
        to_session_id="b",
        from_price_cents=8000,
        to_price_cents=12000,
        from_occurrences=[_occ("a", d) for d in (5, 12, 19, 26)],
        to_occurrences=[_occ("b", d) for d in (6, 13, 20, 27)],
        effective_at=EFFECTIVE,
    )
    assert quote.from_share_cents == 6000
    assert quote.to_share_cents == 9000
    assert quote.delta_cents == 3000
    assert (quote.from_remaining_classes, quote.from_total_classes) == (3, 4)
    assert (quote.to_remaining_classes, quote.to_total_classes) == (3, 4)


def test_quote_negative_delta_when_moving_to_cheaper_session() -> None:
    quote = quote_move_proration(
        period=PERIOD,
        from_session_id="a",
        to_session_id="b",
        from_price_cents=12000,
        to_price_cents=8000,
        from_occurrences=[_occ("a", d) for d in (5, 12, 19, 26)],
        to_occurrences=[_occ("b", d) for d in (6, 13, 20, 27)],
        effective_at=EFFECTIVE,
    )
    assert quote.delta_cents == -3000


def test_quote_zero_delta_for_same_price_and_shape() -> None:
    quote = quote_move_proration(
        period=PERIOD,
        from_session_id="a",
        to_session_id="b",
        from_price_cents=8000,
        to_price_cents=8000,
        from_occurrences=[_occ("a", d) for d in (5, 12, 19, 26)],
        to_occurrences=[_occ("b", d) for d in (6, 13, 20, 27)],
        effective_at=EFFECTIVE,
    )
    assert quote.delta_cents == 0
