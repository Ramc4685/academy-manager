"""Dashboard read (S34): enrollments with no invoice for the month yet.

Kept out of ``composition/admin.py`` (at its line budget); wired in main.py.
"""

from __future__ import annotations

from typing import Any

from backend.v2.contexts.billing.infrastructure.mongo_monthly_billing import (
    MongoMonthlyBillingGenerator,
)
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository


class UnbilledStudentsReader:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def count(self, period: str) -> int:
        generator = MongoMonthlyBillingGenerator(MongoPaymentRepository(self._db))
        return await generator.count_unbilled_enrollments(period)


def compose_unbilled_students(db: Any) -> UnbilledStudentsReader:
    return UnbilledStudentsReader(db)
