"""Transactional email adapters bridging other contexts onto communications.

Extracted from ``admin.py`` (audit item MT1) so the admin composition root is
wiring only. Each adapter maps another context's narrow outbound-email port
(identity's ``InviteEmailPort``, billing's invoice/dunning and
add-card-reminder ports) onto communications' ``EmailSendPort``, and owns the
subject and HTML body for that message.

They live in ``composition`` rather than inside a context because they import
two contexts at once, which contexts themselves may not do (see
``tests/structural/test_layering.py::test_no_cross_context_imports``).
Every user-supplied value interpolated into an HTML body goes through
``html.escape``.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable
from datetime import date

from pydantic import BaseModel

from backend.v2.contexts.billing.application.ports import (
    InviteEmailOutcome as AddCardReminderEmailOutcome,
)
from backend.v2.contexts.billing.domain.ledger import format_charge_date, format_tuition_month
from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.infrastructure.stub_send_port import (
    StubEmailSendPort,
)
from backend.v2.contexts.identity.application.use_cases.send_login_invite import (
    InviteEmailOutcome,
)
from backend.v2.contexts.identity.infrastructure.mongo_academy_repo import (
    MongoAcademyRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_membership_repo import (
    MongoMembershipRepository,
)
from backend.v2.contexts.identity.infrastructure.mongo_user_repo import MongoUserRepository
from backend.v2.shared.comms.email_theme import (
    COBALT,
    FONT_STACK,
    INK,
    MUTED,
    EmailBrand,
    button,
    format_money,
    shell,
)
from backend.v2.shared.tenancy import current_academy_id

log = logging.getLogger(__name__)

# Re-exported for existing callers (roster_notifications, session_announcements,
# enrollment_welcome_email). New code should import ``email_theme`` directly.
_BRAND_HEADING = INK
_BRAND_ACCENT = COBALT
_BRAND_MUTED = MUTED
_BRAND_FONT = FONT_STACK


def _branded_shell(*, academy_name: str, inner_html: str, footer_note: str | None = None) -> str:
    """The academy-branded shell shared by every transactional email.

    ``footer_note`` is for reminders only ("if you've already paid, please
    disregard"); a welcome or a fresh invoice must not carry it.
    """
    note_html = (
        f'<p style="font-size:12px;color:{MUTED};margin:20px 0 0;">{html.escape(footer_note)}</p>'
        if footer_note
        else ""
    )
    return shell(
        brand=EmailBrand(academy_name=academy_name), inner_html=inner_html, footer_html=note_html
    )


def _branded_button(*, label: str, url: str) -> str:
    return button(label, url)


class LoginInviteEmailAdapter:
    """Bridges identity's `InviteEmailPort` to communications' `EmailSendPort`.

    Composition may import both contexts; the identity context itself must
    not import communications, so this adapter lives here rather than in
    `send_login_invite.py`.
    """

    def __init__(self, *, sender: EmailSendPort) -> None:
        self._sender = sender

    async def send_invite_email(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        subject: str,
        body: str,
    ) -> InviteEmailOutcome:
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=user_id,
                email=email,
                display_name=display_name,
            ),
            subject=subject,
            body=body,
        )
        return InviteEmailOutcome(ok=outcome.ok, failed_reason=outcome.failed_reason)


class UndeliverableInviteEmailAdapter:
    """Stands in for `LoginInviteEmailAdapter` when the composed port cannot send.

    ``_build_email_sender`` falls back to ``StubEmailSendPort`` whenever
    ``email_delivery_enabled``/``resend_api_key``/``env`` do not all line up —
    and the stub reports ``ok=True``. For the digests that is correct: local and
    CI runs must not mail anyone. For a *user-visible, user-triggered* message it
    is a lie with consequences: a mistyped ``RESEND_API_KEY`` in prod would show
    every registering parent "Verification email sent", send nothing, log
    nothing, and strand them at a login they can never verify.

    So in an environment that is supposed to deliver real mail, a stub port is
    swapped for this adapter, which logs at ERROR and reports failure. The
    parent gets an honest "could not send, try again" and the misconfiguration
    shows up in the logs on the first attempt instead of in a support ticket
    weeks later.
    """

    def __init__(self, *, reason: str) -> None:
        self._reason = reason

    async def send_invite_email(
        self,
        *,
        user_id: str,
        email: str,
        display_name: str,
        subject: str,
        body: str,
    ) -> InviteEmailOutcome:
        log.error(
            "email delivery is not configured (%s); refusing to report a "
            "successful send of %r to user %s",
            self._reason,
            subject,
            user_id,
        )
        return InviteEmailOutcome(ok=False, failed_reason=self._reason)


def build_user_facing_invite_sender(
    *, sender: EmailSendPort, env: str, real_email_envs: frozenset[str]
) -> LoginInviteEmailAdapter | UndeliverableInviteEmailAdapter:
    """Wrap `sender` for a message a *user* is waiting on.

    Outside a real-email environment the stub's silent success is the desired
    behaviour and is preserved. Inside one, a stub means the deployment is
    misconfigured — see `UndeliverableInviteEmailAdapter`.
    """
    from backend.v2.composition.digests import unwrap_send_port

    if env.lower() in real_email_envs and isinstance(unwrap_send_port(sender), StubEmailSendPort):
        return UndeliverableInviteEmailAdapter(
            reason="email delivery is not configured for this environment"
        )
    return LoginInviteEmailAdapter(sender=sender)


class LastCharge(BaseModel):
    """The most recent successful charge on the same enrollment (issue #659).

    The incident copy the owner asked for is "Your last charge was $70.00 for
    August 2026 tuition on September 3": back-to-back months only explain
    themselves if the *previous* month is named next to the upcoming one.
    Resolved by ``composition.invoice_naming`` and capped at 45 days there, so
    the sentence is always about a charge the parent still remembers.
    """

    model_config = {"frozen": True}

    amount_cents: int
    currency: str
    period: str
    charged_on: date


class InvoiceNaming(BaseModel):
    """What a parent needs to recognise a charge (issue #659).

    Resolved per invoice by the composition root (see
    ``composition.invoice_naming``) and handed to the adapter, which owns only
    the copy. Every field is optional: an unresolvable student or class costs
    the email its detail, never its delivery.
    """

    model_config = {"frozen": True}

    student_name: str | None = None
    session_label: str | None = None
    #: The human ``ACADEMYCODE-YYYY-MM-NNNN`` number. The raw ``invoice_id`` is
    #: deliberately NOT a fallback — a parent must never see the internal slug.
    invoice_number: str | None = None
    #: The previous successful charge on this enrollment, when one landed in
    #: the last 45 days. ``None`` means "say nothing" — never "no charge".
    last_charge: LastCharge | None = None


class InvoiceEmailAdapter:
    def __init__(
        self,
        *,
        memberships: MongoMembershipRepository,
        users: MongoUserRepository,
        academies: MongoAcademyRepository,
        sender: EmailSendPort,
        naming: Callable[[str], Awaitable[InvoiceNaming | None]] | None = None,
    ) -> None:
        self._memberships = memberships
        self._users = users
        self._academies = academies
        self._sender = sender
        # Issue #659: resolves student / class / invoice number for one
        # invoice id. Unwired (or failing) degrades to month-only copy.
        self._naming = naming

    async def _naming_for(self, invoice_id: str) -> InvoiceNaming:
        if self._naming is None:
            return InvoiceNaming()
        try:
            return await self._naming(invoice_id) or InvoiceNaming()
        except Exception:
            log.warning(
                "invoice_email_naming_unresolved",
                extra={"invoice_id": invoice_id},
                exc_info=True,
            )
            return InvoiceNaming()

    @staticmethod
    def _tuition_for(period: str, naming: InvoiceNaming) -> str:
        """Plain-text subject lead: ``"September 2026 tuition for Arjun"``."""
        lead = f"{format_tuition_month(period)} tuition"
        if naming.student_name:
            lead = f"{lead} for {naming.student_name}"
        return lead

    @staticmethod
    def _tuition_html(period: str, naming: InvoiceNaming) -> str:
        """Escaped body lead naming the month, the student and the class."""
        parts = [f"<strong>{html.escape(format_tuition_month(period))} tuition</strong>"]
        if naming.student_name:
            parts.append(f"for <strong>{html.escape(naming.student_name)}</strong>")
        if naming.session_label:
            parts.append(f"({html.escape(naming.session_label)})")
        return " ".join(parts)

    @staticmethod
    def _last_charge_html(naming: InvoiceNaming) -> str:
        """ "Your last charge was $70.00 for August 2026 tuition on September 3."

        Omitted entirely when there is no recent charge: an empty sentence is
        better than one that implies the family has never paid.
        """
        charge = naming.last_charge
        if charge is None:
            return ""
        amount = format_money(charge.amount_cents, charge.currency)
        line = (
            f"{amount} for {format_tuition_month(charge.period)} tuition "
            f"on {format_charge_date(charge.charged_on)}"
        )
        return f"<p>Your last charge was <strong>{html.escape(line)}</strong>.</p>"

    @staticmethod
    def _invoice_number_html(naming: InvoiceNaming) -> str:
        if not naming.invoice_number:
            return ""
        return (
            f"<p style='color: {_BRAND_MUTED};'>Invoice "
            f"<strong>{html.escape(naming.invoice_number)}</strong></p>"
        )

    async def send_invoice_email(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        total_cents: int,
        balance_due_cents: int,
        currency: str,
        checkout_url: str | None,
    ) -> str | None:
        academy_id = current_academy_id()
        membership = await self._memberships.get_membership(academy_id, parent_id)
        if membership is None or not membership.is_active() or "parent" not in membership.roles:
            raise ValueError("invoice parent has no active membership in request academy")

        user = await self._users.get_by_id(parent_id)
        email = str(user.email if user else "").strip()
        if not email:
            raise ValueError("invoice parent email not found")

        display_name = str(user.display_name if user else "")
        academy_name = await self._academies.get_academy_name(academy_id) or "Your academy"
        naming = await self._naming_for(invoice_id)
        amount = format_money(balance_due_cents, currency)
        total = format_money(total_cents, currency)
        month = format_tuition_month(period)
        safe_amount = html.escape(amount)
        safe_total = html.escape(total)
        pay_line = (
            _branded_button(label="Pay invoice", url=checkout_url)
            if checkout_url
            else f"<p style='color: {_BRAND_MUTED};'>Please contact the academy to arrange payment.</p>"
        )
        subject = self._tuition_for(period, naming)
        if naming.session_label:
            subject = f"{subject} — {naming.session_label}"
        inner = (
            f"<h2 style='color: {_BRAND_HEADING}; font-size: 20px; margin: 0 0 12px;'>"
            f"{html.escape(month)} tuition</h2>"
            f"<p>{self._tuition_html(period, naming)} is ready.</p>"
            f"<p>Balance due: <strong>{safe_amount}</strong> "
            f"(invoice total {safe_total}).</p>"
            f"{pay_line}"
            f"{self._invoice_number_html(naming)}"
        )
        body = _branded_shell(academy_name=academy_name, inner_html=inner)
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_id,
                email=email,
                display_name=display_name or None,
            ),
            subject=subject,
            body=body,
        )
        if not outcome.ok:
            raise ValueError(outcome.failed_reason or "invoice email delivery failed")
        return outcome.provider_message_id

    async def send_dunning_notice(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        balance_due_cents: int,
        currency: str,
        attempt_no: int,
        terminal: bool,
    ) -> None:
        academy_id = current_academy_id()
        membership = await self._memberships.get_membership(academy_id, parent_id)
        if membership is None or not membership.is_active() or "parent" not in membership.roles:
            raise ValueError("dunning parent has no active membership in request academy")

        user = await self._users.get_by_id(parent_id)
        email = str(user.email if user else "").strip()
        if not email:
            raise ValueError("dunning parent email not found")

        academy_name = await self._academies.get_academy_name(academy_id) or "Your academy"
        naming = await self._naming_for(invoice_id)
        amount = format_money(balance_due_cents, currency)
        safe_amount = html.escape(amount)
        tuition = self._tuition_for(period, naming)
        tuition_html = self._tuition_html(period, naming)
        number_html = self._invoice_number_html(naming)
        if terminal:
            subject = f"Autopay disabled — {tuition}"
            inner = (
                f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>Autopay disabled</h2>"
                f"<p>We could not collect {tuition_html} after {attempt_no} attempts.</p>"
                f"<p>Balance due: <strong>{safe_amount}</strong>. "
                "Autopay has been disabled for this enrollment until payment details are updated.</p>"
                f"{number_html}"
            )
        else:
            subject = f"Autopay attempt {attempt_no} failed — {tuition}"
            inner = (
                f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>Autopay attempt failed</h2>"
                f"<p>We could not collect {tuition_html}.</p>"
                f"<p>Balance due: <strong>{safe_amount}</strong>. "
                "We will retry automatically on the published retry schedule.</p>"
                f"{number_html}"
            )
        body = _branded_shell(academy_name=academy_name, inner_html=inner)
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_id,
                email=email,
                display_name=str(user.display_name if user else "") or None,
            ),
            subject=subject,
            body=body,
        )
        if not outcome.ok:
            raise ValueError(outcome.failed_reason or "dunning email delivery failed")

    async def _parent_recipient(self, parent_id: str, *, what: str) -> ResolvedRecipient:
        academy_id = current_academy_id()
        membership = await self._memberships.get_membership(academy_id, parent_id)
        if membership is None or not membership.is_active() or "parent" not in membership.roles:
            raise ValueError(f"{what} parent has no active membership in request academy")
        user = await self._users.get_by_id(parent_id)
        email = str(user.email if user else "").strip()
        if not email:
            raise ValueError(f"{what} parent email not found")
        return ResolvedRecipient(
            user_id=parent_id,
            email=email,
            display_name=str(user.display_name if user else "") or None,
        )

    async def send_autopay_notice(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        amount_cents: int,
        currency: str,
        charge_on: date,
        portal_url: str | None,
    ) -> str | None:
        """Pre-charge notice for autopay parents (issue #651): what, when, how
        to pay early or update the card. Sent once per generated invoice."""
        recipient = await self._parent_recipient(parent_id, what="autopay notice")
        academy_name = await self._academies.get_academy_name(current_academy_id()) or (
            "Your academy"
        )
        naming = await self._naming_for(invoice_id)
        amount = format_money(amount_cents, currency)
        safe_amount = html.escape(amount)
        safe_date = html.escape(charge_on.strftime("%B %d, %Y"))
        action = (
            _branded_button(label="View or pay now", url=portal_url)
            if portal_url
            else (
                f"<p style='color: {_BRAND_MUTED};'>Contact the academy to pay early "
                "or update your card.</p>"
            )
        )
        inner = (
            f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
            f"Upcoming autopay charge</h2>"
            f"<p>{self._tuition_html(period, naming)} is "
            f"<strong>{safe_amount}</strong>.</p>"
            f"<p>Your saved card will be charged on <strong>{safe_date}</strong>. "
            "Nothing to do if that works for you. Pay early or update your card "
            "before then if not.</p>"
            f"{self._last_charge_html(naming)}"
            f"{action}"
            f"{self._invoice_number_html(naming)}"
        )
        outcome = await self._sender.send(
            recipient=recipient,
            subject=(
                f"{self._tuition_for(period, naming)}: {amount} will be charged on "
                f"{charge_on.strftime('%b')} {charge_on.day}"
            ),
            body=_branded_shell(academy_name=academy_name, inner_html=inner),
        )
        if not outcome.ok:
            raise ValueError(outcome.failed_reason or "autopay notice delivery failed")
        return outcome.provider_message_id

    async def send_autopay_receipt(
        self,
        *,
        parent_id: str,
        invoice_id: str,
        period: str,
        amount_cents: int,
        currency: str,
    ) -> None:
        """Receipt after a successful autopay charge (issue #651)."""
        recipient = await self._parent_recipient(parent_id, what="autopay receipt")
        academy_name = await self._academies.get_academy_name(current_academy_id()) or (
            "Your academy"
        )
        naming = await self._naming_for(invoice_id)
        amount = format_money(amount_cents, currency)
        inner = (
            f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>"
            f"Payment received</h2>"
            f"<p>We charged <strong>{html.escape(amount)}</strong> to your saved card for "
            f"{self._tuition_html(period, naming)}.</p>"
            f"<p style='color: {_BRAND_MUTED};'>Thank you. No action is needed.</p>"
            f"{self._last_charge_html(naming)}"
            f"{self._invoice_number_html(naming)}"
        )
        outcome = await self._sender.send(
            recipient=recipient,
            subject=f"Receipt: {amount} paid — {self._tuition_for(period, naming)}",
            body=_branded_shell(academy_name=academy_name, inner_html=inner),
        )
        if not outcome.ok:
            raise ValueError(outcome.failed_reason or "autopay receipt delivery failed")


class DuesReminderEmailAdapter:
    """Bridges the admin dues-followup action to communications' `EmailSendPort`."""

    def __init__(self, *, academies: MongoAcademyRepository, sender: EmailSendPort) -> None:
        self._academies = academies
        self._sender = sender

    async def send_reminder(
        self,
        *,
        parent_id: str,
        email: str,
        display_name: str | None,
        total_due_cents: int,
        pending_count: int,
        currency: str,
        pay_url: str | None,
    ) -> bool:
        academy_name = (
            await self._academies.get_academy_name(current_academy_id()) or "Your academy"
        )
        safe_name = html.escape(display_name or "there")
        amount = format_money(total_due_cents, currency)
        safe_amount = html.escape(amount)
        invoice_word = "invoice" if pending_count == 1 else "invoices"
        pay_line = (
            _branded_button(label="Pay now", url=pay_url)
            if pay_url
            else f"<p style='color: {_BRAND_MUTED};'>Please log in to the parent portal to pay.</p>"
        )
        inner = (
            f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>Payment reminder</h2>"
            f"<p>Hi {safe_name},</p>"
            f"<p>You have {pending_count} open {invoice_word} totaling "
            f"<strong>{safe_amount}</strong>.</p>"
            f"{pay_line}"
        )
        body = _branded_shell(
            academy_name=academy_name,
            inner_html=inner,
            footer_note="If you've already taken care of this, please disregard this message.",
        )
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_id,
                email=email,
                display_name=display_name or None,
            ),
            subject="Payment reminder: outstanding balance",
            body=body,
        )
        return outcome.ok


class AddCardReminderEmailAdapter:
    """Bridges billing's local ``InviteEmailPort`` to communications'
    ``EmailSendPort`` — mirrors ``LoginInviteEmailAdapter``; billing must not
    import communications directly."""

    def __init__(self, *, sender: EmailSendPort) -> None:
        self._sender = sender

    async def send_invite_email(
        self, *, user_id: str, email: str, display_name: str, subject: str, body: str
    ) -> AddCardReminderEmailOutcome:
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(user_id=user_id, email=email, display_name=display_name),
            subject=subject,
            body=body,
        )
        return AddCardReminderEmailOutcome(ok=outcome.ok, failed_reason=outcome.failed_reason)
