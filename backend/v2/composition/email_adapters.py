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

from backend.v2.contexts.billing.application.ports import (
    InviteEmailOutcome as AddCardReminderEmailOutcome,
)
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


class InvoiceEmailAdapter:
    def __init__(
        self,
        *,
        memberships: MongoMembershipRepository,
        users: MongoUserRepository,
        academies: MongoAcademyRepository,
        sender: EmailSendPort,
    ) -> None:
        self._memberships = memberships
        self._users = users
        self._academies = academies
        self._sender = sender

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
        amount = format_money(balance_due_cents, currency)
        total = format_money(total_cents, currency)
        safe_invoice = html.escape(invoice_id)
        safe_period = html.escape(period)
        safe_amount = html.escape(amount)
        safe_total = html.escape(total)
        pay_line = (
            _branded_button(label="Pay invoice", url=checkout_url)
            if checkout_url
            else f"<p style='color: {_BRAND_MUTED};'>Please contact the academy to arrange payment.</p>"
        )
        inner = (
            f"<h2 style='color: {_BRAND_HEADING}; font-size: 20px; margin: 0 0 12px;'>"
            f"Your {safe_period} invoice</h2>"
            f"<p>Invoice <strong>{safe_invoice}</strong> is ready.</p>"
            f"<p>Balance due: <strong>{safe_amount}</strong> "
            f"(invoice total {safe_total}).</p>"
            f"{pay_line}"
        )
        body = _branded_shell(academy_name=academy_name, inner_html=inner)
        outcome = await self._sender.send(
            recipient=ResolvedRecipient(
                user_id=parent_id,
                email=email,
                display_name=display_name or None,
            ),
            subject=f"Invoice {invoice_id} for {period}",
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
        amount = format_money(balance_due_cents, currency)
        safe_invoice = html.escape(invoice_id)
        safe_period = html.escape(period)
        safe_amount = html.escape(amount)
        if terminal:
            subject = f"Autopay disabled for invoice {invoice_id}"
            inner = (
                f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>Autopay disabled</h2>"
                f"<p>We could not collect invoice <strong>{safe_invoice}</strong> "
                f"for {safe_period} after {attempt_no} attempts.</p>"
                f"<p>Balance due: <strong>{safe_amount}</strong>. "
                "Autopay has been disabled for this enrollment until payment details are updated.</p>"
            )
        else:
            subject = f"Autopay attempt {attempt_no} failed for invoice {invoice_id}"
            inner = (
                f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>Autopay attempt failed</h2>"
                f"<p>We could not collect invoice <strong>{safe_invoice}</strong> "
                f"for {safe_period}.</p>"
                f"<p>Balance due: <strong>{safe_amount}</strong>. "
                "We will retry automatically on the published retry schedule.</p>"
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
