"""``MoveScheduleReader`` over the ``sessions`` collection (issue #669).

Synthesises a session's period occurrences exactly the way the monthly
generator does — ``_session_occurrences`` plus the ``session_occurrence_overrides``
merge in ``MongoPaymentRepository._occurrences_for_session`` — so a move quote
counts the same classes the invoice was priced on.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.application.use_cases.apply_enrollment_move import (
    MoveSessionSchedule,
)
from backend.v2.contexts.billing.domain.proration import BillingPeriod
from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    session_amount_cents,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import (
    MongoPaymentRepository,
)
from backend.v2.shared.tenancy import current_academy_id


class MongoMoveScheduleReader:
    def __init__(self, db: Any, *, payments: MongoPaymentRepository | None = None) -> None:
        self._db = db
        self._payments = payments or MongoPaymentRepository(db)

    async def load(self, *, session_id: str, period: str) -> MoveSessionSchedule | None:
        doc = await self._db["sessions"].find_one(
            {"academy_id": current_academy_id(), "session_id": session_id}
        )
        if doc is None:
            return None
        timezone_name = str(doc.get("timezone") or "America/Chicago")
        billing_period = BillingPeriod.from_label(period, timezone_name=timezone_name)
        occurrences = await self._payments._occurrences_for_session(doc, billing_period)
        return MoveSessionSchedule(
            session_id=session_id,
            monthly_price_cents=max(session_amount_cents(doc), 0),
            timezone=timezone_name,
            occurrences=occurrences,
        )
