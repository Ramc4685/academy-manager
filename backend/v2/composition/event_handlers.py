"""Cross-context event handlers.

Lives in the composition root because handlers may need to call use cases
from multiple contexts. Registers `@handler` for every cross-context event
in Waves 2+.

Wave 2 wires:
- `Billing.PaymentSucceeded` → Enrollment.ConfirmEnrollment (+ Onboarding transition to PENDING_APPROVAL)
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
from backend.v2.contexts.billing.domain.events import (
    CheckoutExpired,
    PaymentSucceeded,
)
from backend.v2.contexts.enrollment.application.use_cases.confirm_enrollment import (
    ConfirmEnrollment,
    ConfirmEnrollmentCommand,
)
from backend.v2.contexts.enrollment.application.use_cases.promote_from_waitlist import (
    PromoteFromWaitlist,
)
from backend.v2.contexts.enrollment.domain.events import (
    CapacityExceeded as CapacityExceededEvent,
    EnrollmentCancelled,
)
from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    TransitionApplication,
)
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


def _require_deps() -> HandlerDeps:
    if _deps is None:
        raise RuntimeError("event handlers not installed — composition root did not call install_handlers()")
    return _deps


@handler(event=PaymentSucceeded, schema_version=1)
async def on_payment_succeeded(event: PaymentSucceeded) -> None:
    deps = _require_deps()
    payload = event.payload
    # Pull child profile from the Onboarding application via payment metadata
    # in a real wire-up. Wave 2's parent BFF route writes the application_id
    # into a Stripe metadata field; the webhook handler propagates it on the
    # Payment aggregate. For now we pass empty student names — admin completes
    # the profile, mirroring the legacy "PENDING_APPROVAL" stage.
    with tenant_scope(event.academy_id):
        if payload.session_id is None:
            log.info("PaymentSucceeded without session_id; subscription path TBD")
            return
        try:
            await deps.confirm_enrollment.execute(
                ConfirmEnrollmentCommand(
                    payment_id=payload.payment_id,
                    parent_id=payload.parent_id,
                    session_id=payload.session_id,
                    student_first_name="",
                    student_last_name="",
                )
            )
            await deps.transition_application.execute_for_payment(
                payment_id=payload.payment_id, to="PENDING_APPROVAL"
            )
        except Exception:
            # CapacityExceededEvent was already appended by ConfirmEnrollment;
            # auto-refund handler reacts.
            log.exception("ConfirmEnrollment failed for payment %s", payload.payment_id)
            raise


@handler(event=CheckoutExpired, schema_version=1)
async def on_checkout_expired(event: CheckoutExpired) -> None:
    deps = _require_deps()
    with tenant_scope(event.academy_id):
        await deps.transition_application.execute_for_payment(
            payment_id=event.payload.payment_id, to="CHECKOUT_EXPIRED"
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
        await deps.transition_application.execute_for_payment(
            payment_id=payload.payment_id, to="CAPACITY_FAILED_REFUNDING"
        )
        try:
            await deps.issue_refund.execute(
                IssueRefundCommand(
                    payment_id=payload.payment_id,
                    amount_cents=None,
                    reason="capacity_failed",
                )
            )
            await deps.transition_application.execute_for_payment(
                payment_id=payload.payment_id, to="REFUNDED"
            )
        except Exception:
            log.exception("Auto-refund failed for payment %s", payload.payment_id)
            await deps.transition_application.execute_for_payment(
                payment_id=payload.payment_id, to="CAPACITY_FAILED_REFUND_FAILED"
            )


@handler(event=EnrollmentCancelled, schema_version=1)
async def on_enrollment_cancelled(event: EnrollmentCancelled) -> None:
    deps = _require_deps()
    with tenant_scope(event.academy_id):
        await deps.promote_from_waitlist.execute(event.payload.session_id)
