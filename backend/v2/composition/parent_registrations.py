"""Wiring for the family's open registrations (S02).

Its own module so ``composition/parent.py`` only gains one line: the use case
reads applications, this adds the class name the card shows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from backend.v2.composition.roster_notifications import format_session_schedule
from backend.v2.contexts.billing.infrastructure.mongo_payment_repo import MongoPaymentRepository
from backend.v2.contexts.enrollment.infrastructure.mongo_session_writer import MongoSessionWriter
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    ListParentRegistrations,
)
from backend.v2.contexts.onboarding.infrastructure.mongo_application_repo import (
    MongoApplicationRepository,
)
from backend.v2.shared.tenancy import current_academy_id
from backend.v2.shared.time.mongo import ensure_utc


def compose_list_parent_registrations(
    db: Any,
) -> Callable[[str], Awaitable[list[dict[str, Any]]]]:
    payments = MongoPaymentRepository(db)

    async def payment_status(payment_id: str) -> str | None:
        payment = await payments.get(payment_id)
        return payment.status if payment else None

    use_case = ListParentRegistrations(
        MongoApplicationRepository(db), payment_status=payment_status
    )
    sessions = MongoSessionWriter(db)
    academies = MongoAcademyRepository(db)

    async def list_parent_registrations(parent_id: str) -> list[dict[str, Any]]:
        rows = await use_case.execute(parent_id)
        if not rows:
            return []
        session_ids = sorted({a.selected_session_id for a, _ in rows if a.selected_session_id})
        by_session = dict(
            zip(
                session_ids,
                await asyncio.gather(*(sessions.get(sid) for sid in session_ids)),
                strict=True,
            )
        )
        academy = await academies.find_by_id(current_academy_id()) or {}
        timezone = str(academy.get("timezone") or "") or None
        out: list[dict[str, Any]] = []
        for app, state in rows:
            session = by_session.get(app.selected_session_id or "")
            out.append(
                {
                    "application_id": app.application_id,
                    "child_first_name": app.child_profile.first_name.strip(),
                    "session_id": app.selected_session_id,
                    "session_title": session.title if session else None,
                    "schedule_label": (
                        format_session_schedule(session, academy_timezone=timezone)
                        if session
                        else None
                    ),
                    "status": app.status,
                    "state": state,
                    # Mongo hands back naive UTC (#706); say so on the wire.
                    "submitted_at": ensure_utc(app.updated_at),
                }
            )
        return out

    return list_parent_registrations
