"""Unit tests for SessionTypeMoveProrationPolicy (pure domain math)."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.v2.contexts.billing.domain.session_type import SessionType
from backend.v2.contexts.billing.domain.session_type_proration import (
    SessionTypeMoveProrationPolicy,
)

_NOW = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
_PERIOD_START = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
_PERIOD_END = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)  # 31 days


def _session_type(session_type_id: str, price_cents: int) -> SessionType:
    return SessionType(
        session_type_id=session_type_id,
        academy_id="test-academy",
        name=session_type_id,
        price_cents=price_cents,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_mid_period_move_prorates_both_sides() -> None:
    policy = SessionTypeMoveProrationPolicy()
    result = policy.quote(
        from_session_type=_session_type("beginner", 12000),
        to_session_type=_session_type("private", 20000),
        move_date=datetime(2026, 5, 17, 0, 0, tzinfo=UTC),  # 15 days remain
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert result.total_days == 31
    assert result.remaining_days == 15
    # round_half_up(price * 15 / 31)
    assert result.credit_cents == 5806
    assert result.charge_cents == 9677
    assert result.net_cents == 3871
    assert result.proration_ratio == "15/31"
    assert result.from_session_type_id == "beginner"
    assert result.to_session_type_id == "private"


def test_move_at_period_start_charges_full_ratio() -> None:
    policy = SessionTypeMoveProrationPolicy()
    result = policy.quote(
        from_session_type=_session_type("beginner", 12000),
        to_session_type=_session_type("private", 20000),
        move_date=_PERIOD_START,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert result.remaining_days == 31
    assert result.credit_cents == 12000
    assert result.charge_cents == 20000
    assert result.net_cents == 8000


def test_move_at_or_after_period_end_is_zero() -> None:
    policy = SessionTypeMoveProrationPolicy()
    result = policy.quote(
        from_session_type=_session_type("beginner", 12000),
        to_session_type=_session_type("private", 20000),
        move_date=_PERIOD_END,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert result.remaining_days == 0
    assert result.credit_cents == 0
    assert result.charge_cents == 0
    assert result.net_cents == 0


def test_new_enrollment_has_no_credit() -> None:
    policy = SessionTypeMoveProrationPolicy()
    result = policy.quote(
        from_session_type=None,
        to_session_type=_session_type("private", 20000),
        move_date=_PERIOD_START,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
    )
    assert result.credit_cents == 0
    assert result.charge_cents == 20000
    assert result.net_cents == 20000
    assert result.from_session_type_id is None
