"""Win-back composition (issue #778): wires ``SendWinBackNotices`` with its
Mongo-backed claim repo, a direct-Mongo "does this family owe money" lookup,
and an email notifier.

Lives outside ``composition/admin.py`` / ``composition/enrollment_holds.py``
for the same wiring-line-budget reason those two modules already give
(``test_composition_is_wiring``).

The balance lookup queries the ``invoices`` collection directly rather than
going through ``billing``'s ``OutstandingBalanceDirectory`` (composed only
inside the billing-setup-registration read model) because wiring that whole
directory here would pull the entire parent/customer roster machinery in for
one boolean; the CHARGEABLE_INVOICE_STATUSES / balance_due_cents>0 predicate
IS ``autopay_eligibility.invoice_is_chargeable`` — the one definition reused,
not re-implemented.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.v2.contexts.billing.application.autopay_eligibility import (
    CHARGEABLE_INVOICE_STATUSES,
)
from backend.v2.contexts.communications.application.ports import EmailSendPort
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience
from backend.v2.contexts.enrollment.application.use_cases.win_back import (
    SendWinBackNotices,
)
from backend.v2.shared.comms.sender_identity import sender_identity_for_current_academy
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)


class MongoFamilyBalanceLookup:
    """Direct-Mongo "does this parent currently owe money" check.

    Deliberately a existence check (``limit(1)``), not a sum — win-back only
    needs to know whether to suppress, never the amount.
    """

    def __init__(self, db: Any) -> None:
        self._db = db

    async def outstanding_cents_for_parent(self, parent_id: str) -> int:
        academy_id = current_academy_id()
        doc = await self._db["invoices"].find_one(
            {
                "academy_id": academy_id,
                "parent_id": parent_id,
                "status": {"$in": list(CHARGEABLE_INVOICE_STATUSES)},
                "balance_due_cents": {"$gt": 0},
            },
            {"balance_due_cents": 1},
        )
        return int(doc["balance_due_cents"]) if doc else 0


def _para(text: str) -> str:
    return f"<p style='margin:0 0 12px'>{text}</p>"


class WinBackNotificationAdapter:
    """Resolves the parent's email and sends the win-back copy through the
    already-gated ``EmailSendPort`` (suppression + preference gates apply
    exactly as they do to every other family-facing send — no new gate
    needed, per the fix plan)."""

    def __init__(
        self,
        *,
        audiences: Any,
        students: Any,
        sender: EmailSendPort,
        academies: Any | None = None,
    ) -> None:
        self._academies = academies
        self._audiences = audiences
        self._students = students
        self._sender = sender

    async def win_back(
        self,
        *,
        student_id: str,
        parent_id: str,
        milestone_days: int,
        dropped_at: datetime,
    ) -> None:
        try:
            resolved = await self._audiences.resolve_selected_audience(
                SelectedRecipientsAudience(user_ids=(parent_id,))
            )
        except Exception:
            logger.exception("win_back_audience_failed", extra={"parent_id": parent_id})
            return
        recipient = resolved[0] if resolved else None
        if recipient is None or not recipient.email:
            return

        students = await self._students.by_ids([student_id])
        student_name = students[0].full_name if students else "Your child"
        safe_name = html.escape(student_name)

        subject = f"We miss having {safe_name} in class"
        body = "".join(
            [
                _para(
                    f"It's been {milestone_days} days since <strong>{safe_name}</strong> "
                    "left the academy."
                ),
                _para("We would love to have them back whenever you're ready to re-enroll."),
                _para("If this no longer applies, you can safely ignore this message."),
            ]
        )
        try:
            identity = await sender_identity_for_current_academy(self._academies)
            await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                category=EmailCategory.CAMPAIGN,
                reply_to=identity.reply_to,
                sender_name=identity.sender_name,
            )
        except Exception:
            logger.exception("win_back_send_failed", extra={"student_id": student_id})


@dataclass
class WinBackComposition:
    send_win_back_notices: SendWinBackNotices


def compose_win_back(db: Any, settings: Any) -> WinBackComposition:
    """Build the win-back use case with every real collaborator — a caller
    need only pass ``db``/``settings``, mirroring
    ``compose_enrollment_holds``/``compose_hold_notifications``."""
    from backend.v2.composition.digests import _build_email_sender
    from backend.v2.composition.win_back_send_repo import MongoWinBackSendRepository
    from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
        MongoAudienceResolver,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_event_repo import (
        MongoEnrollmentEventRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_enrollment_repo import (
        MongoEnrollmentRepository,
    )
    from backend.v2.contexts.enrollment.infrastructure.mongo_student_repo import (
        MongoStudentRepository,
    )
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )

    students = MongoStudentRepository(db)
    notifier = WinBackNotificationAdapter(
        audiences=MongoAudienceResolver(db=db),
        students=students,
        sender=_build_email_sender(settings, db),
        academies=MongoAcademyRepository(db),
    )
    use_case = SendWinBackNotices(
        enrollment_events=MongoEnrollmentEventRepository(db),
        enrollments=MongoEnrollmentRepository(db),
        students=students,
        send_repo=MongoWinBackSendRepository(db),
        balance_lookup=MongoFamilyBalanceLookup(db),
        notifier=notifier,
    )
    return WinBackComposition(send_win_back_notices=use_case)
