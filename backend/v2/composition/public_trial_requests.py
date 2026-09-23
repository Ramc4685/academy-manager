"""Composition for the anonymous public trial request (public tenant page, Lane B4).

Wiring for ``POST /api/v2/public/trial-requests`` plus the one adapter it
needs that spans contexts: the academy notification email. Zero lines in
``composition/admin.py`` (at its line budget). Attached at
``app.state.public_trial_requests`` by ``main.py`` and read by
``interfaces/public/trial_request_routes.py``.

The notification lives here, not in a context, for the same reason
``registration_decision_email.py`` does: it needs CRM (the contact),
identity (the academy's name and colour) and communications (owner
recipients, the gated send port) at once, and no bounded context may import
another.

**It never runs on the response path.** The route hands it to FastAPI's
``BackgroundTasks`` for every accepted submission, new, repeated or honeypot
alike, and the adapter itself decides whether anything is sent (only for a
newly created contact). The HTTP response is therefore the same bytes and the
same work whether or not the inquiry was already on file, and a mail outage
can never fail or slow a submission.
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from typing import Any, Final, Protocol

from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.communications.domain.models import AcademyAudience, AudienceRole
from backend.v2.contexts.communications.infrastructure.mongo_audience_resolver import (
    MongoAudienceResolver,
)
from backend.v2.contexts.crm.application.use_cases.create_contact import CreateContact
from backend.v2.contexts.crm.application.use_cases.submit_website_inquiry import (
    SubmitWebsiteInquiry,
)
from backend.v2.contexts.crm.domain.models import CrmContact
from backend.v2.contexts.crm.infrastructure.mongo_crm_contact_repo import (
    MongoCrmContactRepository,
)
from backend.v2.contexts.enrollment.application.use_cases.public_class_choice import (
    ResolvePublicClassChoice,
)
from backend.v2.contexts.enrollment.infrastructure.mongo_session_repo import (
    MongoSessionRepository,
)
from backend.v2.contexts.identity.application.public_academy_profile import (
    GetPublicAcademyProfile,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.shared.comms.email_theme import EmailBrand, shell
from backend.v2.shared.tenancy.context import tenant_scope

logger = logging.getLogger(__name__)

#: Who hears about a website lead: the academy's owners (roadmap decision:
#: owner, billing, front desk; the owner runs the pipeline until the CRM
#: screens ship). An academy with no owner address falls back to its public
#: contact email (brief section 5, "a lead must still reach a human").
_RECIPIENT_ROLE: Final[AudienceRole] = "owner"


class AcademyLookup(Protocol):
    async def find_by_id(self, academy_id: str) -> dict[str, Any] | None: ...


def _row(label: str, value: str | None) -> str:
    shown = html.escape(value) if value else '<span style="color:#64748b;">Not given</span>'
    return (
        '<tr><td style="padding:6px 12px 6px 0;color:#64748b;vertical-align:top;'
        f'white-space:nowrap;">{html.escape(label)}</td>'
        f'<td style="padding:6px 0;vertical-align:top;">{shown}</td></tr>'
    )


def render_trial_request_alert(
    *,
    brand: EmailBrand,
    contact: CrmContact,
    class_title: str | None,
) -> tuple[str, str]:
    """Subject and themed HTML body for the academy's new-lead email.

    Every value is caller-supplied text from an anonymous form, so each one is
    HTML-escaped and none is ever placed in a link or an attribute.
    """
    is_trial = contact.pipeline_status == "trial"
    kind = "trial request" if is_trial else "inquiry"
    subject = f"New {kind} from {contact.name}"
    message_html = (
        '<p style="margin:16px 0 4px;font-weight:600;">Their message</p>'
        '<p style="margin:0;white-space:pre-wrap;">'
        f"{html.escape(contact.message)}</p>"
        if contact.message
        else ""
    )
    marketing = "Yes" if contact.consent.marketing else "No"
    inner = "".join(
        [
            f'<h2 style="margin:0 0 12px;">{html.escape(subject)}</h2>',
            '<p style="margin:0 0 14px;">',
            (
                "Someone asked for a free trial on your public page."
                if is_trial
                else "Someone asked to hear from you on your public page."
            ),
            " Reply to this email to answer them directly.</p>",
            '<table role="presentation" style="border-collapse:collapse;font-size:14px;">',
            _row("Name", contact.name),
            _row("Email", contact.email),
            _row("Phone", contact.phone_digits),
            _row("Player's age", contact.child_age),
            _row("Class", class_title or ("Not sure yet" if is_trial else None)),
            _row("News and offers", marketing),
            "</table>",
            message_html,
            '<p style="margin:18px 0 0;font-size:13px;color:#64748b;">'
            "They agreed to be contacted about this request. Nothing is booked or "
            "charged until you confirm a date with them.</p>",
        ]
    )
    return subject, shell(brand=brand, inner_html=inner)


class TrialRequestOwnerEmail:
    """Emails the academy's owners about a NEW website contact, once."""

    def __init__(
        self,
        *,
        academies: AcademyLookup,
        audiences: AudienceResolver,
        sender: EmailSendPort,
    ) -> None:
        self._academies = academies
        self._audiences = audiences
        self._sender = sender

    async def notify(
        self,
        *,
        academy_id: str,
        contact: CrmContact | None,
        created: bool,
        class_title: str | None,
    ) -> None:
        """Background task body. Never raises; a no-op unless ``created``.

        Called for every accepted submission so the response path is uniform;
        a repeat (``created=False``) or a honeypot hit (``contact=None``) ends
        here without a read or a send.
        """
        if contact is None or not created:
            return
        try:
            with tenant_scope(academy_id):
                await self._send_all(contact, class_title)
        except Exception:
            logger.exception(
                "public.trial_request_alert_failed",
                extra={"contact_id": contact.contact_id},
            )

    async def _send_all(self, contact: CrmContact, class_title: str | None) -> None:
        doc = await self._academies.find_by_id(contact.academy_id) or {}
        brand = EmailBrand(
            academy_name=str(doc.get("display_name") or doc.get("name") or "") or "Your academy",
            brand_color=doc.get("brand_color"),
            logo_url=doc.get("logo_url"),
        )
        subject, body = render_trial_request_alert(
            brand=brand, contact=contact, class_title=class_title
        )
        for recipient in await self._recipients(doc):
            outcome = await self._sender.send(
                recipient=recipient,
                subject=subject,
                body=body,
                reply_to=contact.email,
                # TRANSACTIONAL: the record of a request someone made to this
                # academy; it must reach a human and carries no unsubscribe.
                category=EmailCategory.TRANSACTIONAL,
            )
            if not outcome.ok and not outcome.suppressed:
                logger.warning(
                    "public.trial_request_alert_send_failed",
                    extra={"contact_id": contact.contact_id, "reason": outcome.failed_reason},
                )

    async def _recipients(self, academy_doc: dict[str, Any]) -> list[ResolvedRecipient]:
        found = await self._audiences.resolve_academy_audience(
            AcademyAudience(role=_RECIPIENT_ROLE)
        )
        seen: set[str] = set()
        unique: list[ResolvedRecipient] = []
        for recipient in found:
            email = (recipient.email or "").strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            unique.append(recipient)
        if unique:
            return unique
        fallback = str(academy_doc.get("contact_email") or "").strip()
        if not fallback:
            logger.warning("public.trial_request_alert_no_recipient")
            return []
        return [
            ResolvedRecipient(
                user_id=f"academy-contact:{academy_doc.get('academy_id') or ''}",
                email=fallback,
                display_name=None,
            )
        ]


@dataclass(frozen=True)
class PublicTrialRequests:
    get_academy_profile: GetPublicAcademyProfile
    resolve_class_choice: ResolvePublicClassChoice
    submit_inquiry: SubmitWebsiteInquiry
    notifier: TrialRequestOwnerEmail


def compose_public_trial_requests(db: Any, settings: Any) -> PublicTrialRequests:
    """``_build_email_sender`` is the one construction site that hands dev and
    CI the stub port and production the gated Resend one."""
    from backend.v2.composition.digests import _build_email_sender

    academies = MongoAcademyRepository(db)
    return PublicTrialRequests(
        get_academy_profile=GetPublicAcademyProfile(academies),
        resolve_class_choice=ResolvePublicClassChoice(MongoSessionRepository(db)),
        submit_inquiry=SubmitWebsiteInquiry(CreateContact(MongoCrmContactRepository(db))),
        notifier=TrialRequestOwnerEmail(
            academies=academies,
            audiences=MongoAudienceResolver(db=db),
            sender=_build_email_sender(settings, db),
        ),
    )
