"""Issue #669: price delta for the rest of the period when a student moves sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from backend.v2.contexts.billing.domain.credits import (
    EarlyWithdrawalCreditPolicy,
    class_cancellation_credit_cents,
)
from backend.v2.contexts.billing.domain.proration import (
    BillingPeriod,
    ClassOccurrence,
    PaidPeriodCharge,
    quote_move_proration,
    remaining_share_cents,
    unused_paid_classes,
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


def test_remaining_share_prices_at_the_four_per_meeting_rate() -> None:
    """Tue+Thu, 9 dates: the month sells 8 classes, so the share is 6/8.

    Pricing 6/9 would value a class at a rate no first month was charged at,
    which is what the move delta has to reconcile against.
    """
    occurrences = [_occ("a", d) for d in (1, 3, 8, 10, 15, 17, 22, 24, 29)]
    share, remaining, total = remaining_share_cents(
        monthly_price_cents=7000, period=PERIOD, occurrences=occurrences, effective_at=EFFECTIVE
    )
    assert (remaining, total) == (6, 9)
    assert share == 5250


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
    # 2 eligible dates in the month, so the one class left is worth the
    # four-class rate (1000 / 4), not half the month.
    assert (share, remaining, total) == (250, 1, 2)


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


# ---------------------------------------------------------------------------
# Issue #729: the from-side credits the UNUSED PAID classes, consumed-first,
# the same rule withdrawal and cancellation credits use.
# ---------------------------------------------------------------------------

#: Five Tuesdays in September 2026 — the month lays out 5 dates but the $70
#: monthly rate buys 4 (the 5th class is free).
FIVE_TUESDAYS = (1, 8, 15, 22, 29)
#: Local midnight of the 15th: the 1st and the 8th have been consumed.
AFTER_TWO_CLASSES = datetime(2026, 9, 15, 0, 0, tzinfo=ZoneInfo(TZ))


def test_unused_paid_classes_takes_consumed_out_of_the_paid_block_first() -> None:
    # 5 scheduled, 4 paid, 3 still to come -> 2 consumed, 2 paid classes left.
    assert unused_paid_classes(
        billable_remaining_classes=5, billable_classes_denominator=4, scheduled_unused=3
    ) == (4, 2)
    # Only the free 5th class is left: nothing to give back.
    assert unused_paid_classes(
        billable_remaining_classes=5, billable_classes_denominator=4, scheduled_unused=1
    ) == (4, 0)
    # A four-date month is unaffected by the rule.
    assert unused_paid_classes(
        billable_remaining_classes=4, billable_classes_denominator=4, scheduled_unused=2
    ) == (4, 2)
    # A snapshot written before the denominator existed credits at the rate it
    # charged: everything it counted as remaining was paid for.
    assert unused_paid_classes(
        billable_remaining_classes=3, billable_classes_denominator=None, scheduled_unused=2
    ) == (3, 2)


def test_from_share_credits_unused_paid_classes_in_a_five_class_month() -> None:
    """#729: three dates left but only two of them were paid for."""
    paid, unused = unused_paid_classes(
        billable_remaining_classes=5, billable_classes_denominator=4, scheduled_unused=3
    )
    quote = quote_move_proration(
        period=PERIOD,
        from_session_id="a",
        to_session_id="b",
        from_price_cents=7000,
        to_price_cents=7000,
        from_occurrences=[_occ("a", d) for d in FIVE_TUESDAYS],
        to_occurrences=[_occ("b", d) for d in (2, 9, 16, 23, 30)],
        effective_at=AFTER_TWO_CLASSES,
        from_paid=PaidPeriodCharge(charge_cents=7000, paid_classes=paid, unused_classes=unused),
    )
    # 7000 * 2 / 4, not the old 7000 * 3 / 4.
    assert quote.from_share_cents == 3500
    # The to-side is a fresh forward-looking first-month share and is untouched.
    assert quote.to_share_cents == 5250
    assert quote.from_remaining_classes == 3
    assert quote.policy_version == "move-proration-v4"


def test_move_withdrawal_and_cancellation_return_the_same_cents() -> None:
    """The three credit paths agree for one family in one month (#729)."""
    paid, unused = unused_paid_classes(
        billable_remaining_classes=5, billable_classes_denominator=4, scheduled_unused=3
    )
    quote = quote_move_proration(
        period=PERIOD,
        from_session_id="a",
        to_session_id="b",
        from_price_cents=7000,
        to_price_cents=0,
        from_occurrences=[_occ("a", d) for d in FIVE_TUESDAYS],
        to_occurrences=[_occ("b", d) for d in FIVE_TUESDAYS],
        effective_at=AFTER_TWO_CLASSES,
        from_paid=PaidPeriodCharge(charge_cents=7000, paid_classes=paid, unused_classes=unused),
    )
    withdrawal = EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=7000,
        refunded_tuition_cents=0,
        unused_eligible_classes=unused,
        paid_period_eligible_classes=paid,
        calculated_at=EFFECTIVE,
        calculated_by="test",
    )
    cancellation = (
        class_cancellation_credit_cents(period_charge_cents=7000, billable_classes=paid) * unused
    )
    assert quote.from_share_cents == withdrawal.credit_amount_cents == cancellation == 3500


def test_from_share_falls_back_to_the_forward_looking_share_without_a_charge() -> None:
    """No snapshot for the period (never invoiced) keeps the old behaviour."""
    quote = quote_move_proration(
        period=PERIOD,
        from_session_id="a",
        to_session_id="b",
        from_price_cents=7000,
        to_price_cents=7000,
        from_occurrences=[_occ("a", d) for d in FIVE_TUESDAYS],
        to_occurrences=[_occ("b", d) for d in (2, 9, 16, 23, 30)],
        effective_at=AFTER_TWO_CLASSES,
    )
    assert quote.from_share_cents == 5250
