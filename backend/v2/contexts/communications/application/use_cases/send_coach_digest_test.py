"""SendCoachDigestTest use case.

An admin-triggered *test* send of the coach teaching-plan digest. It reuses the
same renderer and ``PlanProvider`` as the daily digest, but differs in two ways:

* It BYPASSES the per-academy ``coach_digest_enabled`` flag — a test send works
  even when the daily digest is turned off.
* It does NOT consume the daily idempotency claim. The send is recorded with a
  ``kind="test"`` marker via ``record_test_send`` so the unique
  ``(academy_id, coach_id, digest_date)`` index for the real daily send is never
  blocked, and an admin can re-test as many times as they like.

The target is one user: a named coach, or the admin themselves ("self"). The
recipient is resolved through the shared ``AudienceResolver`` (an explicit
single-id selection), so the same tenant scoping and Resend/Stub gating apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from backend.v2.contexts.communications.application.digest_renderer import render_coach_digest
from backend.v2.contexts.communications.application.ports import (
    AudienceResolver,
    DigestSendRepository,
    EmailSendPort,
    ResolvedRecipient,
)
from backend.v2.contexts.communications.application.use_cases.send_coach_daily_digest import (
    PlanProvider,
    plan_is_empty,
)
from backend.v2.contexts.communications.domain.models import SelectedRecipientsAudience


class _Clock(Protocol):
    def __call__(self) -> datetime: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SendCoachDigestTestCommand:
    academy_id: str
    target_user_id: str
    on_date: date


@dataclass(frozen=True, slots=True)
class SendCoachDigestTestResult:
    status: str  # "sent" | "skipped_empty" | "failed"
    coach_id: str
    email: str | None
    detail: str | None = None


class CoachDigestTargetNotFound(Exception):
    """The requested coach/self could not be resolved in this academy."""


@dataclass
class SendCoachDigestTest:
    digests: DigestSendRepository
    resolver: AudienceResolver
    sender: EmailSendPort
    plan_provider: PlanProvider
    now: _Clock = field(default=_utcnow)

    async def execute(self, command: SendCoachDigestTestCommand) -> SendCoachDigestTestResult:
        recipients = await self.resolver.resolve_selected_audience(
            SelectedRecipientsAudience(user_ids=(command.target_user_id,))
        )
        recipient = next(
            (r for r in recipients if r.user_id == command.target_user_id),
            recipients[0] if recipients else None,
        )
        if recipient is None:
            raise CoachDigestTargetNotFound(command.target_user_id)

        digest_date = command.on_date.isoformat()
        send = await self.digests.record_test_send(
            command.academy_id, recipient.user_id, digest_date
        )

        try:
            plan: Any | None = await self.plan_provider.execute(recipient.user_id, command.on_date)
        except Exception as exc:  # plan generation must never crash the test send
            await self.digests.mark_failed(send.digest_id, f"plan generation failed: {exc}")
            return SendCoachDigestTestResult(
                status="failed", coach_id=recipient.user_id, email=recipient.email, detail=str(exc)
            )

        if plan_is_empty(plan):
            await self.digests.mark_skipped_empty(send.digest_id)
            return SendCoachDigestTestResult(
                status="skipped_empty",
                coach_id=recipient.user_id,
                email=recipient.email,
                detail="No sessions to teach for this date.",
            )

        if not recipient.email:
            await self.digests.mark_failed(send.digest_id, "no email address")
            return SendCoachDigestTestResult(
                status="failed",
                coach_id=recipient.user_id,
                email=None,
                detail="Recipient has no email address.",
            )

        subject, body = render_coach_digest(plan)
        outcome = await self.sender.send(
            recipient=ResolvedRecipient(
                user_id=recipient.user_id,
                email=recipient.email,
                display_name=recipient.display_name,
            ),
            subject=subject,
            body=body,
        )
        if outcome.ok:
            await self.digests.mark_sent(send.digest_id, outcome.provider_message_id)
            return SendCoachDigestTestResult(
                status="sent", coach_id=recipient.user_id, email=recipient.email
            )
        await self.digests.mark_failed(send.digest_id, outcome.failed_reason or "unknown")
        return SendCoachDigestTestResult(
            status="failed",
            coach_id=recipient.user_id,
            email=recipient.email,
            detail=outcome.failed_reason or "unknown",
        )
