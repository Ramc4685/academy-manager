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

from backend.v2.contexts.billing.application.ports import (
    InviteEmailOutcome as AddCardReminderEmailOutcome,
)
from backend.v2.contexts.communications.application.ports import (
    EmailSendPort,
    ResolvedRecipient,
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
from backend.v2.shared.tenancy import current_academy_id

_BRAND_HEADING = "#0a0f1c"
_BRAND_ACCENT = "#2545d3"
_BRAND_MUTED = "#64748b"
_BRAND_FONT = "-apple-system, 'Segoe UI', sans-serif"


def _branded_shell(*, academy_name: str, inner_html: str) -> str:
    """Wraps a message body in the academy-branded header/footer shared by
    every billing email. Uses the same color and font conventions as
    ``send_login_invite._invite_body`` so all outbound mail reads as one
    product."""
    safe_academy_name = html.escape(academy_name)
    return f"""
<div style="font-family: {_BRAND_FONT}; max-width: 520px; margin: 0 auto;">
  <div style="padding-bottom: 14px; margin-bottom: 20px; border-bottom: 2px solid {_BRAND_ACCENT};">
    <span style="font-size: 16px; font-weight: 700; color: {_BRAND_HEADING};">{safe_academy_name}</span>
  </div>
  {inner_html}
  <p style="color: {_BRAND_MUTED}; font-size: 12px; margin-top: 32px; border-top: 1px solid #e2e8f0; padding-top: 16px;">
    Sent by {safe_academy_name}. If you've already taken care of this, please disregard this message.
  </p>
</div>
"""


def _branded_button(*, label: str, url: str) -> str:
    safe_url = html.escape(url, quote=True)
    safe_label = html.escape(label)
    return (
        f'<p style="margin: 24px 0;"><a href="{safe_url}" '
        f'style="background: {_BRAND_ACCENT}; color: #ffffff; padding: 12px 20px; '
        f'border-radius: 8px; text-decoration: none; font-weight: 600; display: inline-block;">'
        f"{safe_label}</a></p>"
    )


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
        amount = f"{currency.upper()} {balance_due_cents / 100:.2f}"
        total = f"{currency.upper()} {total_cents / 100:.2f}"
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
            f"<h2 style='color: {_BRAND_HEADING}; font-size: 18px; margin: 0 0 12px;'>Invoice ready</h2>"
            f"<p>Your invoice <strong>{safe_invoice}</strong> for {safe_period} is ready.</p>"
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
        amount = f"{currency.upper()} {balance_due_cents / 100:.2f}"
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
        amount = f"{currency.upper()} {total_due_cents / 100:.2f}"
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
        body = _branded_shell(academy_name=academy_name, inner_html=inner)
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
