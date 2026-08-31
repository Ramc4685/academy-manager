"""Cross-context event handlers.

Lives in the composition root because handlers may need to call use cases
from multiple contexts. Registers `@handler` for every cross-context event
in Waves 2+.

Wave 2 wires:
- `Billing.PaymentSucceeded` → Onboarding transition to PENDING_APPROVAL
- `Enrollment.CapacityExceeded` → Billing.IssueRefund (auto-refund)
- `Billing.CheckoutExpired` → Onboarding transition to CHECKOUT_EXPIRED
- `Enrollment.EnrollmentCancelled` → Enrollment.PromoteFromWaitlist
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.v2.contexts.billing.application.use_cases.issue_refund import (
    IssueRefund,
    IssueRefundCommand,
)
from backend.v2.contexts.billing.application.use_cases.process_dunning_retries import (
    DunningNotificationPort,
)
from backend.v2.contexts.billing.domain.events import (
    CheckoutExpired,
    DunningNoticeRequested,
    PaymentSucceeded,
)
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import (
    CapacityExceeded as CapacityExceededEvent,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentCancelled,
)
from backend.v2.contexts.identity.application.use_cases.register_public_parent import (
    WelcomeEmailRequested,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    TransitionApplication,
)
from backend.v2.contexts.onboarding.domain.errors import ApplicationForPaymentNotFound
from backend.v2.contexts.student_progress.domain.events import StudentPlacedInLevel
from backend.v2.shared.events import handler
from backend.v2.shared.tenancy.context import tenant_scope

log = logging.getLogger(__name__)


@dataclass
class HandlerDeps:
    confirm_enrollment: ConfirmEnrollment
    promote_from_waitlist: PromoteFromWaitlist
    issue_refund: IssueRefund
    transition_application: TransitionApplication


# Module-level holder so the `@handler` registrations have a reference to
# the wired-in deps at runtime. The composition root populates this in
# `main.py` startup.
_deps: HandlerDeps | None = None


def install_handlers(deps: HandlerDeps) -> None:
    """Called once by the composition root."""
    global _deps
    _deps = deps


# The dunning notice adapter is installed separately from `HandlerDeps`
# (issue #435): it is built by `compose_admin`, which owns the billing e-mail
# wiring, while `install_handlers` is called by `compose_parent`. Keeping it in
# its own holder avoids making one composition root reach into the other's
# dependencies just to satisfy a single handler.
_dunning_notifier: DunningNotificationPort | None = None


def install_dunning_notifier(notifier: DunningNotificationPort | None) -> None:
    """Called once by the admin composition root. ``None`` when e-mail delivery
    is not configured — the dunning worker then never enqueues a notice, so the
    handler is unreachable rather than permanently failing."""
    global _dunning_notifier
    _dunning_notifier = notifier


def _require_deps() -> HandlerDeps:
    if _deps is None:
        raise RuntimeError(
            "event handlers not installed — composition root did not call install_handlers()"
        )
    return _deps


@handler(event=StudentPlacedInLevel, schema_version=1)
async def on_student_placed_in_level(_event: StudentPlacedInLevel) -> None:
    # Placement audit is written synchronously by the admin route; this handler
    # keeps the domain event registered until a cross-context subscriber exists.
    return None


@handler(event=PaymentSucceeded, schema_version=1)
async def on_payment_succeeded(event: PaymentSucceeded) -> None:
    deps = _require_deps()
    payload = event.payload
    with tenant_scope(event.academy_id):
        if payload.session_id is None:
            log.info("PaymentSucceeded without session_id; subscription path TBD")
            return
        try:
            await deps.transition_application.execute_for_payment(
                payment_id=payload.payment_id, to="PENDING_APPROVAL"
            )
        except ApplicationForPaymentNotFound:
            # Most PaymentSucceeded events are not registrations at all —
            # invoices, subscription renewals and admin-recorded payments all
            # land here with no onboarding application, and that is fine.
            # What is NOT fine is the case this used to be indistinguishable
            # from: a registration checkout that was paid while its application
            # pointed somewhere else. `execute_for_payment` now matches
            # superseded payment ids too, so a miss here should be the benign
            # kind — but it is money that moved, so it is recorded at WARNING
            # under a stable marker a reconciliation query can select on,
            # rather than swallowed by a `None` nobody looked at (#549).
            log.warning(
                "onboarding_application_unresolved_for_payment",
                extra={
                    "marker": "onboarding_application_unresolved_for_payment",
                    "payment_id": payload.payment_id,
                    "parent_id": payload.parent_id,
                    "session_id": payload.session_id,
                    "amount_cents": payload.amount_cents,
                    "to_status": "PENDING_APPROVAL",
                },
            )


@handler(event=CheckoutExpired, schema_version=1)
async def on_checkout_expired(event: CheckoutExpired) -> None:
    deps = _require_deps()
    with tenant_scope(event.academy_id):
        try:
            await deps.transition_application.execute_for_payment(
                payment_id=event.payload.payment_id, to="CHECKOUT_EXPIRED"
            )
        except ApplicationForPaymentNotFound:
            # No money moved, so this one is genuinely uninteresting: every
            # non-registration checkout that times out arrives here.
            log.info(
                "checkout expired for payment %s with no onboarding application",
                event.payload.payment_id,
            )


@handler(event=CapacityExceededEvent, schema_version=1)
async def on_capacity_exceeded(event: CapacityExceededEvent) -> None:
    deps = _require_deps()
    payload = event.payload
    if payload.payment_id is None:
        return
    with tenant_scope(event.academy_id):
        # Move onboarding state to CAPACITY_FAILED_REFUNDING first so an
        # admin sees the intermediate state if anything blows up.
        try:
            await deps.transition_application.execute_for_payment(
                payment_id=payload.payment_id, to="CAPACITY_FAILED_REFUNDING"
            )
        except ApplicationForPaymentNotFound:
            # The refund below still has to run — it is a real charge — but an
            # over-capacity registration whose application cannot be found is a
            # genuine anomaly, not routine traffic like the succeeded path.
            log.error(
                "onboarding_application_unresolved_for_payment",
                extra={
                    "marker": "onboarding_application_unresolved_for_payment",
                    "payment_id": payload.payment_id,
                    "to_status": "CAPACITY_FAILED_REFUNDING",
                },
            )
        try:
            await deps.issue_refund.execute(
                IssueRefundCommand(
                    payment_id=payload.payment_id,
                    amount_cents=None,
                    reason="capacity_failed",
                )
            )
            try:
                await deps.transition_application.execute_for_payment(
                    payment_id=payload.payment_id, to="REFUNDED"
                )
            except ApplicationForPaymentNotFound:
                # Already reported above; the refund itself succeeded, and
                # falling into the refund-failed branch would misreport that.
                pass
        except Exception:
            log.exception("Auto-refund failed for payment %s", payload.payment_id)
            try:
                await deps.transition_application.execute_for_payment(
                    payment_id=payload.payment_id, to="CAPACITY_FAILED_REFUND_FAILED"
                )
            except ApplicationForPaymentNotFound:
                pass


@handler(event=EnrollmentCancelled, schema_version=1)
async def on_enrollment_cancelled(event: EnrollmentCancelled) -> None:
    deps = _require_deps()
    with tenant_scope(event.academy_id):
        await deps.promote_from_waitlist.execute(event.payload.session_id)


@handler(event=WelcomeEmailRequested, schema_version=1)
async def on_welcome_email_requested(event: WelcomeEmailRequested) -> None:
    log.info(
        "welcome_email_requested",
        extra={
            "user_id": event.payload.user_id,
            "academy_id": event.academy_id,
        },
    )


# The decorator is typed against the DomainEvent base while every handler here
# narrows to its own event — same as the handlers above, which predate the
# mypy baseline. Ignored locally rather than widening the baseline.
@handler(event=DunningNoticeRequested, schema_version=1)  # type: ignore[arg-type]
async def on_dunning_notice_requested(event: DunningNoticeRequested) -> None:
    """Deliver the "autopay attempt failed" notice (issue #435).

    This handler deliberately lets failures propagate: raising is what hands the
    notice to the dispatcher's retry ladder, and eventually to the dead-letter
    collection the ops digest reports. Swallowing the error here would restore
    exactly the bug this event was introduced to fix — a parent never told that
    their payment failed.
    """
    if _dunning_notifier is None:
        raise RuntimeError(
            "dunning notifier not installed — composition root did not call "
            "install_dunning_notifier()"
        )
    payload = event.payload
    with tenant_scope(event.academy_id):
        await _dunning_notifier.send_dunning_notice(
            parent_id=payload.parent_id,
            invoice_id=payload.invoice_id,
            period=payload.period,
            balance_due_cents=payload.balance_due_cents,
            currency=payload.currency,
            attempt_no=payload.attempt_no,
            terminal=payload.terminal,
        )
