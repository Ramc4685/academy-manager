"""Session-type move proration policy.

Pure domain policy, a sibling of ``FirstMonthProrationPolicy``. When a
student moves between session types mid-period, the unused remainder of the
old type is credited and the new type is charged over the same remainder,
both prorated on a daily basis. ``net_cents`` is ``charge - credit`` and may
be negative (the parent is owed a credit).

Per-session billing types are not daily-prorated; callers should not invoke
this policy for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from backend.v2.contexts.billing.domain.proration import _round_half_up_rational
from backend.v2.contexts.billing.domain.session_type import SessionType

POLICY_VERSION = "session-type-move-proration-v1"


class SessionTypeMoveProrationResult(BaseModel):
    model_config = {"frozen": True}

    credit_cents: int = Field(ge=0)
    charge_cents: int = Field(ge=0)
    net_cents: int
    remaining_days: int = Field(ge=0)
    total_days: int = Field(ge=0)
    proration_ratio: str
    from_session_type_id: str | None
    to_session_type_id: str
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True)
class SessionTypeMoveProrationPolicy:
    def quote(
        self,
        *,
        from_session_type: SessionType | None,
        to_session_type: SessionType,
        move_date: datetime,
        period_start: datetime,
        period_end: datetime,
    ) -> SessionTypeMoveProrationResult:
        total_days = max((period_end - period_start).days, 0)
        # Days of service remaining in the period from the move forward.
        raw_remaining = (period_end - move_date).days
        remaining_days = min(max(raw_remaining, 0), total_days)

        from_price = from_session_type.price_cents if from_session_type is not None else 0
        credit_cents = _prorate(from_price, remaining_days, total_days)
        charge_cents = _prorate(to_session_type.price_cents, remaining_days, total_days)
        ratio = f"{remaining_days}/{total_days}" if total_days else "0/0"
        return SessionTypeMoveProrationResult(
            credit_cents=credit_cents,
            charge_cents=charge_cents,
            net_cents=charge_cents - credit_cents,
            remaining_days=remaining_days,
            total_days=total_days,
            proration_ratio=ratio,
            from_session_type_id=(
                from_session_type.session_type_id if from_session_type is not None else None
            ),
            to_session_type_id=to_session_type.session_type_id,
        )


def _prorate(price_cents: int, remaining_days: int, total_days: int) -> int:
    if total_days <= 0 or remaining_days <= 0 or price_cents <= 0:
        return 0
    return _round_half_up_rational(price_cents * remaining_days, total_days)
