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
from typing import Any, Protocol

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


class WinBackPersonaliser(Protocol):
    """B6: the AI-drafted second paragraph, or ``None`` when the owner has not
    turned the standing approval on. Any error means the template is used."""

    async def paragraph(
        self, *, student_id: str, child_first_name: str, milestone_days: int
    ) -> str | None: ...


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
        personaliser: WinBackPersonaliser | None = None,
    ) -> None:
        self._academies = academies
        self._audiences = audiences
        self._students = students
        self._sender = sender
        #: Attached after construction by ``compose_ai_win_back`` (the AI
        #: composition is built later in main.py than this adapter).
        self.personaliser = personaliser

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
        second = "We would love to have them back whenever you're ready to re-enroll."
        # shortcut: the model is called before ``sender.send`` applies suppression
        # and preference gates, so a suppressed parent still costs one cap slot;
        # move the gates ahead of this call if win-back volume ever crowds out
        # coach drafts.
        if self.personaliser is not None:
            try:
                drafted = await self.personaliser.paragraph(
                    student_id=student_id,
                    child_first_name=student_name.split()[0] if student_name.split() else "",
                    milestone_days=milestone_days,
                )
            except Exception:
                # Disabled, not entitled, cap, provider or validation: the
                # template still goes out. No prompt text in the log.
                logger.warning(
                    "win_back_ai_paragraph_failed",
                    extra={"student_id": student_id, "milestone_days": milestone_days},
                    exc_info=True,
                )
            else:
                if drafted:
                    second = html.escape(drafted)
        body = "".join(
            [
                _para(
                    f"It's been {milestone_days} days since <strong>{safe_name}</strong> "
                    "left the academy."
                ),
                _para(second),
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


class AcademyWinBackSwitch:
    """``WinBackSwitch`` over the academy document (hardcoded-values row 10).

    ``notifications.win_back_enabled`` is read with a default of on: an
    academy that never saved the setting (BLNO today) keeps the outreach it
    always had. Only an explicit ``False`` turns it off. The read is for the
    one academy the job is running, never another tenant's document.

    ``key`` names another switch under ``notifications`` with the same
    default-on reading (the trial nudges use ``trial_nudges_enabled``).
    """

    def __init__(self, academies: Any, *, key: str = "win_back_enabled") -> None:
        self._academies = academies
        self._key = key

    async def is_enabled(self, academy_id: str) -> bool:
        try:
            doc = await self._academies.find_by_id(academy_id)
        except Exception:
            # Skip this tick rather than mail families an owner may have
            # opted out; the next daily tick retries and a due milestone
            # stays due until the next one supersedes it.
            logger.warning(
                "win_back_switch_lookup_failed", extra={"academy_id": academy_id}, exc_info=True
            )
            return False
        notifications = (doc or {}).get("notifications") if isinstance(doc, dict) else None
        if not isinstance(notifications, dict):
            return True
        return notifications.get(self._key, True) is not False


@dataclass
class WinBackComposition:
    send_win_back_notices: SendWinBackNotices
    notifier: WinBackNotificationAdapter


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
    academies = MongoAcademyRepository(db)
    notifier = WinBackNotificationAdapter(
        audiences=MongoAudienceResolver(db=db),
        students=students,
        sender=_build_email_sender(settings, db),
        academies=academies,
    )
    use_case = SendWinBackNotices(
        enrollment_events=MongoEnrollmentEventRepository(db),
        enrollments=MongoEnrollmentRepository(db),
        students=students,
        send_repo=MongoWinBackSendRepository(db),
        balance_lookup=MongoFamilyBalanceLookup(db),
        notifier=notifier,
        switch=AcademyWinBackSwitch(academies),
    )
    return WinBackComposition(send_win_back_notices=use_case, notifier=notifier)
