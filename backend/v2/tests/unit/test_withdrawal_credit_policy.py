from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.v2.contexts.billing.application.use_cases.withdrawal_credit import (
    _preview_from_snapshot,
)
from backend.v2.contexts.billing.domain.credits import EarlyWithdrawalCreditPolicy
from backend.v2.contexts.billing.domain.models import Payment
from backend.v2.contexts.billing.domain.proration import (
    BillingPeriod,
    ClassOccurrence,
    FirstMonthProrationPolicy,
)
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    _build_monthly_tuition_snapshot,
)


def test_withdrawal_credit_uses_net_paid_and_original_class_count() -> None:
    result = EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=4000,
        refunded_tuition_cents=2000,
        unused_eligible_classes=3,
        paid_period_eligible_classes=8,
        calculated_at=datetime(2026, 5, 20, tzinfo=UTC),
        calculated_by="admin-1",
    )

    assert result.credit_amount_cents == 750
    assert result.formula == "max(4000 - 2000, 0) * 3 / 8"
    assert result.no_credit_reason is None


def test_withdrawal_credit_zero_guard_when_paid_period_has_no_classes() -> None:
    result = EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=4000,
        refunded_tuition_cents=0,
        unused_eligible_classes=3,
        paid_period_eligible_classes=0,
        calculated_at=datetime(2026, 5, 20, tzinfo=UTC),
        calculated_by="admin-1",
    )

    assert result.credit_amount_cents == 0
    assert result.no_credit_reason == "NO_PAID_PERIOD_ELIGIBLE_CLASSES"


# ---------------------------------------------------------------------------
# Withdrawal refunds at the rate the month was charged at (#730).
# ---------------------------------------------------------------------------

#: Five Wednesdays in September 2026, 18:00 America/Chicago.
_SEPTEMBER_WEDNESDAYS = (2, 9, 16, 23, 30)


def _september_weekly() -> list[ClassOccurrence]:
    return [
        ClassOccurrence(
            occurrence_id=f"sess-1:2026-09-{day:02d}:18:00",
            session_id="sess-1",
            start_at=datetime(2026, 9, day, 23, 0, tzinfo=UTC),
            end_at=datetime(2026, 9, day, 23, 0, tzinfo=UTC) + timedelta(hours=1),
            status="scheduled",
            is_billable=True,
            timezone="America/Chicago",
        )
        for day in _SEPTEMBER_WEDNESDAYS
    ]


def _payment(amount_cents: int) -> Payment:
    return Payment(
        payment_id="pay-1",
        academy_id="acad",
        parent_id="par-1",
        enrollment_id="enr-1",
        amount_cents=amount_cents,
        status="succeeded",
        created_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
    )


def test_withdrawal_refunds_a_continuing_family_at_the_four_class_rate() -> None:
    """Two $70 payers, two classes attended, one refund (#730).

    The continuing family used to be refunded ``70 * 3/5 = $42`` because their
    flat month was recorded as buying all five dates, while the family beside
    them got ``70 * 2/4 = $35``.
    """
    period = BillingPeriod.from_label("2026-09", timezone_name="America/Chicago")
    occurrences = _september_weekly()
    joined_at = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    withdrawal = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

    continuing = _build_monthly_tuition_snapshot(
        occurrences=occurrences,
        billing_period=period,
        monthly_price_cents=7_000,
        discount_cents=0,
        now=joined_at,
    )
    first_month = FirstMonthProrationPolicy().quote(
        monthly_price_cents=7_000,
        discount_cents=0,
        period=period,
        occurrences=occurrences,
        billing_start_at=joined_at,
        calculated_at=joined_at,
        calculated_by="parent-1",
    )
    assert continuing.final_amount_cents == first_month.final_amount_cents == 7_000

    previews = [
        _preview_from_snapshot(
            payment=_payment(7_000),
            snapshot=snapshot,
            withdrawal_date=withdrawal,
            calculated_at=withdrawal,
            calculated_by="admin-1",
        )
        for snapshot in (continuing, first_month)
    ]

    assert previews[0].credit_amount_cents == previews[1].credit_amount_cents == 3_500
    assert previews[0].paid_period_eligible_classes == 4
    assert previews[0].unused_eligible_classes == 2
