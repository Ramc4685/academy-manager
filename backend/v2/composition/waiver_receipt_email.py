"""Waiver signing receipt email (waiver signing upgrade, Phase 1).

One email per signing act, to the signer, listing each waiver and child signed
with the audit details and a link to the printable signed copy. It is the
adapter behind ``AcceptParentWaiver``'s ``WaiverSignedNotifier`` port and lives
in ``composition/`` because it needs onboarding, communications and identity.

Best-effort: the signatures are durable before this runs, and a send failure is
logged, never raised.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from backend.v2.composition.email_adapters import _branded_shell
from backend.v2.composition.registration_decision_email import AcademyLookup
from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.domain.email_category import EmailCategory
from backend.v2.contexts.onboarding.application.use_cases.parent_student_waivers import (
    ParentSignedWaiverCopy,
)
from backend.v2.shared.comms.sender_identity import sender_identity_for_current_academy
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)


class SignedCopyReader(Protocol):
    async def signed_copy(self, waiver_signature_id: str) -> ParentSignedWaiverCopy | None: ...


def _row(label: str, value: str | None) -> str:
    return (
        '<tr><td style="padding:2px 12px 2px 0;color:#555;white-space:nowrap;">'
        f'{html.escape(label)}</td><td style="padding:2px 0;word-break:break-all;">'
        f"{html.escape(value or 'Not recorded')}</td></tr>"
    )


def render_waiver_receipt_email(
    *, academy_name: str, copies: list[ParentSignedWaiverCopy], base_url: str
) -> tuple[str, str]:
    first = copies[0]
    titles = sorted({c.title or "Waiver" for c in copies})
    subject = f"Signed: {', '.join(titles)}"
    signed_at = first.signed_at.strftime("%Y-%m-%d %H:%M UTC") if first.signed_at else None
    items = []
    for copy in copies:
        link = f"{base_url}/parent/waivers/signatures/{copy.waiver_signature_id}"
        version = f" (version {copy.version})" if copy.version else ""
        items.append(
            '<li style="margin:0 0 12px;">'
            f"<strong>{html.escape(copy.title or 'Waiver')}</strong>{html.escape(version)}"
            f" for {html.escape(copy.student_name or 'your child')}<br>"
            f'<a href="{html.escape(link, quote=True)}">View or print the signed copy</a>'
            '<table style="margin-top:4px;font-size:12px;border-collapse:collapse;">'
            f"{_row('Signature ID', copy.waiver_signature_id)}"
            f"{_row('SHA-256', copy.content_hash)}"
            "</table></li>"
        )
    inner = (
        '<p style="margin:0 0 14px;line-height:1.5;">'
        f"Thank you. This is your record of the waivers you signed with "
        f"{html.escape(academy_name)}.</p>"
        f'<ul style="padding-left:18px;margin:0 0 14px;">{"".join(items)}</ul>'
        '<table style="font-size:13px;border-collapse:collapse;margin:0 0 14px;">'
        f"{_row('Signed by', first.signer_name)}"
        f"{_row('Email', first.signer_email)}"
        f"{_row('Signed at', signed_at)}"
        f"{_row('IP address', first.ip_address)}"
        "</table>"
        '<p style="margin:0;line-height:1.5;color:#555;font-size:12px;">'
        f"{html.escape(first.consent_text or '')}</p>"
    )
    return subject, _branded_shell(academy_name=academy_name, inner_html=inner)


class WaiverReceiptEmailAdapter:
    def __init__(
        self,
        *,
        copies: SignedCopyReader,
        academies: AcademyLookup,
        sender: EmailSendPort,
        base_url_for: Callable[[str], Awaitable[str]],
    ) -> None:
        self._copies = copies
        self._academies = academies
        self._sender = sender
        self._base_url_for = base_url_for

    async def waivers_signed(
        self, *, parent_user_id: str, signer_email: str, waiver_signature_ids: list[str]
    ) -> None:
        email = (signer_email or "").strip()
        if not email:
            logger.warning("waiver.receipt_no_recipient", extra={"parent_id": parent_user_id})
            return
        copies = [
            copy
            for sid in waiver_signature_ids
            if (copy := await self._copies.signed_copy(sid)) is not None
        ]
        if not copies:
            return
        academy_id = current_academy_id()
        doc = await self._academies.find_by_id(academy_id) or {}
        academy_name = str(doc.get("display_name") or doc.get("name") or "") or "Your academy"
        subject, body = render_waiver_receipt_email(
            academy_name=academy_name,
            copies=copies,
            base_url=await self._base_url_for(academy_id),
        )
        identity = await sender_identity_for_current_academy(self._academies)
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_user_id, email=email, display_name=copies[0].signer_name
            ),
            subject=subject,
            body=body,
            # TRANSACTIONAL: the record of a legal act the parent just took.
            category=EmailCategory.TRANSACTIONAL,
            reply_to=identity.reply_to,
            sender_name=identity.sender_name,
        )
        if not outcome.ok and not outcome.suppressed:
            logger.warning(
                "waiver.receipt_email_failed",
                extra={"parent_id": parent_user_id, "reason": outcome.failed_reason},
            )


def compose_waiver_receipt_notifier(db: Any, settings: Any) -> WaiverReceiptEmailAdapter:
    from backend.v2.composition.academy_links import academy_frontend_base_url_lookup
    from backend.v2.composition.digests import _build_email_sender
    from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
        MongoAcademyRepository,
    )
    from backend.v2.contexts.onboarding.infrastructure.mongo_parent_waiver_repo import (
        MongoParentWaiverRepository,
    )

    return WaiverReceiptEmailAdapter(
        copies=MongoParentWaiverRepository(db),
        academies=MongoAcademyRepository(db),
        sender=_build_email_sender(settings, db),
        base_url_for=academy_frontend_base_url_lookup(
            db, frontend_url=settings.frontend_url, default="https://app.example.com"
        ),
    )
