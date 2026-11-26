"""S59: wire the coach-scoped hours and pay read (``GET /coach/profile/pay``).

Kept out of ``composition/coach.py`` so the coach root stays one line per
concern. The academy clock decides "this month".
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from backend.v2.contexts.finance.application.use_cases.coach_pay_summary import (
    GetCoachPaySummary,
)
from backend.v2.contexts.finance.infrastructure.mongo_coach_pay_reader import (
    MongoCoachPayReader,
)
from backend.v2.shared.reporting_definitions import month_window, report_zone


def compose_coach_pay(db: Any, *, clock: Any = None) -> GetCoachPaySummary:
    now = clock or (lambda: datetime.now(UTC))

    def today(zone: str | None) -> date:
        return now().astimezone(report_zone(zone)).date()

    return GetCoachPaySummary(
        reader=MongoCoachPayReader(db, clock=now), month_window=month_window, today=today
    )
