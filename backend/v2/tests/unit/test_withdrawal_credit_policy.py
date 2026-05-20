from __future__ import annotations

from datetime import datetime, timezone

from backend.v2.contexts.billing.domain.credits import EarlyWithdrawalCreditPolicy


def test_withdrawal_credit_uses_net_paid_and_original_class_count() -> None:
    result = EarlyWithdrawalCreditPolicy().preview(
        paid_tuition_cents=4000,
        refunded_tuition_cents=2000,
        unused_eligible_classes=3,
        paid_period_eligible_classes=8,
        calculated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
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
        calculated_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        calculated_by="admin-1",
    )

    assert result.credit_amount_cents == 0
    assert result.no_credit_reason == "NO_PAID_PERIOD_ELIGIBLE_CLASSES"
