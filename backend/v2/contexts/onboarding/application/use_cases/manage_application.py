"""Use cases for the parent onboarding stepper.

- StartApplication — returns an existing DRAFT, RESUMES an abandoned checkout,
  or creates a new application.
- PatchApplication — merges parent/child profile, waiver acceptance, selected session.
- GetApplicationStatus — polling endpoint for the checkout-return page.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.application.ports import (
    ApplicationRepository,
    WaiverRepository,
)
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationForPaymentNotFound,
    ApplicationNotEditable,
    ApplicationNotFound,
    NoActiveWaiver,
)
from backend.v2.contexts.onboarding.domain.models import (
    Application,
    ChildProfile,
    ParentProfile,
    WaiverAcceptance,
)
from backend.v2.shared.ids import new_ulid

_EDITABLE = {"DRAFT"}
APPLICATION_TTL_DAYS = 7
# The status a resumed checkout returns to. Kept as a name (rather than a bare
# "DRAFT" literal at each site) because the legality of the move lives in
# _TRANSITIONS, not in the resume code — see StartApplication._resume.
_RESUME_TO = "DRAFT"


class SupersededCheckoutRetirement(Protocol):
    """Cross-context port (Billing): kill a checkout attempt this application
    no longer owns.

    Expiring the Stripe Checkout Session and parking its pending Payment are
    Billing concerns, so Onboarding only states the need; composition wires
    the adapter. The implementation must be forgiving — Stripe errors when a
    session is already complete or expired, and that is precisely the race
    (parent paid on the old tab) where the surrounding state must still stand.
    """

    async def retire_checkout_attempt(
        self, *, checkout_session_id: str | None, payment_id: str | None
    ) -> None: ...


class StartApplicationCommand(BaseModel):
    model_config = {"frozen": True}
    parent_user_id: str
    parent_email: str


class StartApplication:
    def __init__(
        self,
        *,
        apps: ApplicationRepository,
        academy_id: Callable[[], str],
        clock=lambda: datetime.now(UTC),
        checkout_retirement: SupersededCheckoutRetirement | None = None,
    ) -> None:
        self._apps = apps
        self._academy_id = academy_id
        self._now = clock
        self._checkout_retirement = checkout_retirement

    async def execute(self, cmd: StartApplicationCommand) -> Application:
        existing = await self._apps.latest_for_parent(cmd.parent_user_id)
        if existing and existing.status in _EDITABLE:
            return existing
        if existing is not None and _RESUME_TO in _TRANSITIONS.get(existing.status, set()):
            # The parent hit Cancel on Stripe and landed back on the wizard,
            # which calls this on mount. Minting a SECOND application here
            # (the old behaviour) leaves the first one holding a still-payable
            # Checkout Session: one enrollment, two ways to be charged.
            resumed = await self._resume(existing)
            if resumed is not None:
                return resumed
            # The compare-and-set missed, so the application moved under us —
            # almost always because the parent paid in the other tab and the
            # webhook won. NEVER resurrect that; re-read and fall through to a
            # brand new application.
            existing = await self._apps.get(existing.application_id) or existing
            if existing.status in _EDITABLE:
                return existing
        now = self._now()
        app = Application(
            application_id=str(new_ulid()),
            # Request-time tenant via the injected provider — never a boot value.
            academy_id=self._academy_id(),
            parent_user_id=cmd.parent_user_id,
            parent_email=cmd.parent_email,
            status="DRAFT",
            expires_at=now + timedelta(days=APPLICATION_TTL_DAYS),
            created_at=now,
            updated_at=now,
        )
        if existing is not None:
            # Returning parent adding another child: carry their own details
            # over from the previous application so they never retype them.
            # The child profile intentionally starts blank.
            app = app.model_copy(update={"parent_profile": existing.parent_profile})
        await self._apps.save(app)
        return app

    async def _resume(self, app: Application) -> Application | None:
        """Hand an abandoned checkout attempt back to the wizard.

        PatchApplication only accepts DRAFT, so resuming has to move the
        application back there — an authorised product change, declared in
        _TRANSITIONS rather than smuggled past the state machine.

        The write is a compare-and-set on the status we read. Returns None if
        the application already moved on (paid in another tab), in which case
        the caller must not resurrect it.
        """
        resumed = await self._apps.reopen_for_edit(
            app.application_id,
            expected_status=app.status,
            updated_at=self._now(),
        )
        if resumed is None:
            return None
        if self._checkout_retirement is not None:
            # The superseded Stripe session stays payable until we expire it.
            # payment_id is deliberately LEFT on the application: if that
            # payment succeeded in the last instants before we won the CAS,
            # `get_by_payment_id` is the only handle the webhook has back to
            # this application (DRAFT -> PENDING_APPROVAL covers that case).
            await self._checkout_retirement.retire_checkout_attempt(
                checkout_session_id=app.stripe_checkout_session_id,
                payment_id=app.payment_id,
            )
        return resumed


class PatchApplicationCommand(BaseModel):
    model_config = {"frozen": True}
    application_id: str
    # The route layer must pass the caller's user_id — the use case rejects
    # the request if the application belongs to a different parent. This is
    # the security-matrix "own resource" enforcement for the parent persona.
    caller_user_id: str
    # Raw dicts at the application boundary so the interface layer doesn't
    # have to import from domain (ADR-0005 rule 4). Domain types are
    # constructed inside the use case.
    parent_profile: dict[str, object] | None = None
    child_profile: dict[str, object] | None = None
    selected_session_id: str | None = None
    accept_waiver: bool = False


class StudentRegistrationQuery(Protocol):
    async def find_registration_student(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> str | None: ...

    async def has_ambiguous_registration_match(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> bool: ...

    async def has_active_enrollment(
        self,
        student_id: str,
        *,
        exclude_enrollment_id: str | None = None,
    ) -> bool: ...


class PatchApplication:
    def __init__(
        self,
        *,
        apps: ApplicationRepository,
        waivers: WaiverRepository,
        student_registrations: StudentRegistrationQuery | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._apps = apps
        self._waivers = waivers
        self._student_registrations = student_registrations
        self._now = clock

    async def execute(self, cmd: PatchApplicationCommand) -> Application:
        app = await self._apps.get(cmd.application_id)
        if app is None or app.parent_user_id != cmd.caller_user_id:
            # 404 (not 403) so a parent can't probe other parents'
            # application ids. Per docs/security-matrix.md.
            raise ApplicationNotFound("application missing", application_id=cmd.application_id)
        if app.status not in _EDITABLE:
            raise ApplicationNotEditable(
                "application is not in an editable state",
                status=app.status,
            )

        waiver_acceptance = app.waiver_acceptance
        if cmd.accept_waiver:
            waiver = await self._waivers.get_active()
            if waiver is None:
                raise NoActiveWaiver("no active waiver to accept")
            waiver_acceptance = WaiverAcceptance(
                waiver_version=waiver.version,
                content_hash=waiver.content_hash,
                accepted_at=self._now(),
                waiver_template_id=waiver.waiver_id,
            )

        child_profile = (
            ChildProfile.model_validate(cmd.child_profile)
            if cmd.child_profile
            else app.child_profile
        )
        # A child-profile edit invalidates the old binding. Keeping it when
        # the edited identity no longer matches could update the wrong child.
        student_id = None if cmd.child_profile else app.student_id
        if cmd.child_profile and self._student_registrations is not None:
            full_name = f"{child_profile.first_name} {child_profile.last_name}".strip()
            await self._assert_unambiguous_child(
                app.parent_user_id,
                full_name,
                child_profile.date_of_birth or None,
            )
            existing_student_id = await self._student_registrations.find_registration_student(
                parent_id=app.parent_user_id,
                full_name=full_name,
                date_of_birth=child_profile.date_of_birth or None,
            )
            if existing_student_id is not None:
                if await self._student_registrations.has_active_enrollment(existing_student_id):
                    raise ApplicationNotEditable(
                        "This child is already enrolled. Manage their existing classes instead."
                    )
                student_id = existing_student_id

        updated = app.model_copy(
            update={
                "parent_profile": (
                    ParentProfile.model_validate(cmd.parent_profile)
                    if cmd.parent_profile
                    else app.parent_profile
                ),
                "child_profile": child_profile,
                "student_id": student_id,
                "selected_session_id": cmd.selected_session_id or app.selected_session_id,
                "waiver_acceptance": waiver_acceptance,
                "updated_at": self._now(),
            }
        )
        await self._apps.save(updated)
        return updated

    async def _assert_unambiguous_child(
        self, parent_id: str, full_name: str, date_of_birth: str | None
    ) -> None:
        assert self._student_registrations is not None
        if await self._student_registrations.has_ambiguous_registration_match(
            parent_id=parent_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
        ):
            raise ApplicationNotEditable(
                "We found more than one possible child record. Contact the academy to continue."
            )


class GetApplicationStatus:
    def __init__(self, apps: ApplicationRepository) -> None:
        self._apps = apps

    async def execute(
        self, application_id: str, *, caller_user_id: str | None = None
    ) -> Application:
        """Returns the application status. When `caller_user_id` is
        supplied (the parent BFF passes it from auth claims), the use
        case 404s on mismatch — preventing parent A from reading parent
        B's onboarding status. Webhook handlers and admin callers pass
        None to skip the check."""
        app = await self._apps.get(application_id)
        if app is None or (caller_user_id is not None and app.parent_user_id != caller_user_id):
            raise ApplicationNotFound("application missing", application_id=application_id)
        return app


_TRANSITIONS: dict[str, set[str]] = {
    # DRAFT -> PENDING_APPROVAL only ever fires for a RESUMED application whose
    # superseded Stripe session was paid anyway. TransitionApplication reaches
    # it exclusively through execute_for_payment, which resolves the
    # application by a payment_id the application still carries — a draft that
    # never checked out has no payment_id and can never be found that way. Without
    # this edge the webhook for that race would raise forever and the parent
    # would be charged with no registration.
    "DRAFT": {"CHECKOUT_PENDING", "ABANDONED", "PENDING_APPROVAL"},
    # CHECKOUT_PENDING -> DRAFT is the resume transition: returning from
    # Stripe's cancel URL re-opens THIS application for editing instead of
    # minting a second one that could be paid separately (product decision).
    "CHECKOUT_PENDING": {
        "CHECKOUT_EXPIRED",
        "PENDING_APPROVAL",
        "CAPACITY_FAILED_REFUNDING",
        "DRAFT",
    },
    "CAPACITY_FAILED_REFUNDING": {"REFUNDED", "CAPACITY_FAILED_REFUND_FAILED"},
}


# The ONLY transition a payment id the application has already superseded may
# drive. Advancing a paid registration is safe and is the point of the archive
# (#549); every other target is destructive, and a stale event for a replaced
# attempt must never reach the live one.
_SUPERSEDED_RESOLVABLE_TARGETS = frozenset({"PENDING_APPROVAL"})


class TransitionApplication:
    """Internal helper used by Billing event handlers + admin paths.

    Enforces the legal-transition table. Re-applying the same target is
    idempotent when there is nothing new to stamp; when a newer checkout id /
    payment id IS supplied it re-points the application at that attempt under
    a compare-and-set and retires the one it replaced.
    """

    def __init__(
        self,
        apps: ApplicationRepository,
        student_registrations: StudentRegistrationQuery | None = None,
        clock=lambda: datetime.now(UTC),
        checkout_retirement: SupersededCheckoutRetirement | None = None,
    ) -> None:
        self._apps = apps
        self._student_registrations = student_registrations
        self._now = clock
        self._checkout_retirement = checkout_retirement

    async def execute_for_payment(
        self,
        payment_id: str,
        to: str,
    ) -> Application:
        """Locate the application by payment_id and transition it.

        Used by Billing event handlers in composition/event_handlers.py.

        Raises ``ApplicationForPaymentNotFound`` when nothing claims the
        payment. This USED to return ``None``, which made the two cases
        indistinguishable at the call site and turned the dangerous one into a
        shrug: a registration checkout that was paid but whose application no
        longer pointed at the payment silently went nowhere — money taken,
        application stuck, no alert (#549). Payments that never had an
        onboarding context (invoices, subscriptions, admin-recorded payments)
        still reach here, and the handler names that case explicitly instead of
        letting the return value stand in for it.

        A payment id the application has SUPERSEDED resolves only for
        ``PENDING_APPROVAL``. That asymmetry is the whole safety property, so
        it lives here rather than in the adapter: the archive exists to let a
        late `checkout.session.completed` for an attempt the parent actually
        paid still advance the registration. Letting the same archive answer a
        destructive target would be strictly worse than the orphan it repairs —
        a stale `checkout.session.expired` for the replaced attempt would park
        the application in ``CHECKOUT_EXPIRED``, which has no outgoing
        transition and is not a status checkout can be restarted from, while
        the live attempt is being paid. The guard cannot be delegated to the
        webhook's own `payment.status == "pending"` check either: the write
        that arms it is neither atomic with the CAS nor exception-guarded.
        """
        app = await self._apps.get_by_payment_id(payment_id)
        if app is None and to in _SUPERSEDED_RESOLVABLE_TARGETS:
            app = await self._apps.get_by_superseded_payment_id(payment_id)
        if app is None:
            raise ApplicationForPaymentNotFound(
                "no onboarding application claims this payment",
                payment_id=payment_id,
                to_status=to,
            )
        return await self.execute(app.application_id, to)  # type: ignore[arg-type]

    async def execute(
        self,
        application_id: str,
        to: Literal[
            "CHECKOUT_PENDING",
            "CHECKOUT_EXPIRED",
            "PENDING_APPROVAL",
            "CAPACITY_FAILED_REFUNDING",
            "REFUNDED",
            "CAPACITY_FAILED_REFUND_FAILED",
            "ABANDONED",
        ],
        *,
        stripe_checkout_session_id: str | None = None,
        payment_id: str | None = None,
    ) -> Application:
        app = await self._apps.get(application_id)
        if app is None:
            raise ApplicationNotFound("application missing", application_id=application_id)
        if app.status == to:
            if stripe_checkout_session_id is None and payment_id is None:
                # Plain idempotent re-apply with nothing to stamp — the $0
                # checkout path calls CHECKOUT_PENDING with no ids at all.
                return app
            return await self._restamp_checkout(
                app,
                stripe_checkout_session_id=stripe_checkout_session_id,
                payment_id=payment_id,
            )
        legal = _TRANSITIONS.get(app.status, set())
        if to not in legal:
            raise ApplicationNotEditable(
                "illegal application transition",
                from_status=app.status,
                to_status=to,
            )
        if to == "CHECKOUT_PENDING":
            await self._assert_child_not_enrolled(app)
            # The ENTRY transition needs the same CAS as the re-stamp below.
            # This used to be a blind save, so two concurrent starts from one
            # DRAFT application both wrote — leaving two live payable Stripe
            # sessions and only the last-written payment_id, which is the sole
            # handle `PaymentSucceeded` has. The re-stamp CAS never covered
            # this because it only fires once the application is ALREADY
            # CHECKOUT_PENDING; the first race happens on the way in.
            claimed = await self._apps.restamp_checkout(
                app.application_id,
                expected_status=app.status,
                expected_payment_id=app.payment_id,
                stripe_checkout_session_id=stripe_checkout_session_id,
                payment_id=payment_id,
                updated_at=self._now(),
                new_status=to,
            )
            if claimed is None:
                # Lost the entry race. Ours is the losing attempt: retire the
                # session we just minted rather than leave it payable, and
                # never write over the winner's ids.
                await self._retire_checkout_attempt(
                    checkout_session_id=stripe_checkout_session_id,
                    payment_id=payment_id,
                )
                raise ApplicationNotEditable(
                    "checkout was superseded by a concurrent start",
                    from_status=app.status,
                    to_status=to,
                )
            return claimed
        updates: dict[str, object] = {"status": to, "updated_at": self._now()}
        if stripe_checkout_session_id is not None:
            updates["stripe_checkout_session_id"] = stripe_checkout_session_id
        if payment_id is not None:
            updates["payment_id"] = payment_id
        updated = app.model_copy(update=updates)
        await self._apps.save(updated)
        return updated

    async def _restamp_checkout(
        self,
        app: Application,
        *,
        stripe_checkout_session_id: str | None,
        payment_id: str | None,
    ) -> Application:
        """Re-point an already-CHECKOUT_PENDING application at a newer checkout.

        Reachable when the same application starts checkout twice — two tabs,
        or a retried POST. The status does not move, but the ids MUST:
        `checkout.session.completed` resolves back to the application through
        `get_by_payment_id` alone, so keeping the superseded payment_id orphans
        the one the parent actually paid.
        """
        # The real ->CHECKOUT_PENDING transition runs this guard, and this
        # branch writes just as that one does. Skipping it here would let a
        # second start re-point an application at a live payment for a child
        # who is already enrolled.
        await self._assert_child_not_enrolled(app)
        updated = await self._apps.restamp_checkout(
            app.application_id,
            expected_status=app.status,
            expected_payment_id=app.payment_id,
            stripe_checkout_session_id=stripe_checkout_session_id,
            payment_id=payment_id,
            updated_at=self._now(),
        )
        if updated is None:
            # A concurrent start already took ownership. OURS is the losing
            # attempt: retire the session we just minted rather than leave a
            # second payable session behind, and never overwrite the winner's
            # ids — that would point the application at a payment nobody is
            # going to complete.
            await self._retire_checkout_attempt(
                checkout_session_id=stripe_checkout_session_id,
                payment_id=payment_id,
            )
            raise ApplicationNotEditable(
                "checkout was superseded by a concurrent start",
                from_status=app.status,
                to_status="CHECKOUT_PENDING",
            )
        await self._retire_checkout_attempt(
            checkout_session_id=app.stripe_checkout_session_id,
            payment_id=app.payment_id,
        )
        return updated

    async def _retire_checkout_attempt(
        self, *, checkout_session_id: str | None, payment_id: str | None
    ) -> None:
        if self._checkout_retirement is None:
            return
        if checkout_session_id is None and payment_id is None:
            return
        await self._checkout_retirement.retire_checkout_attempt(
            checkout_session_id=checkout_session_id,
            payment_id=payment_id,
        )

    async def _assert_child_not_enrolled(self, app: Application) -> None:
        if self._student_registrations is None:
            return
        full_name = f"{app.child_profile.first_name} {app.child_profile.last_name}".strip()
        date_of_birth = app.child_profile.date_of_birth or None
        if await self._student_registrations.has_ambiguous_registration_match(
            parent_id=app.parent_user_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
        ):
            raise ApplicationNotEditable(
                "We found more than one possible child record. Contact the academy to continue."
            )
        student_id = app.student_id or await self._student_registrations.find_registration_student(
            parent_id=app.parent_user_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
        )
        if student_id and await self._student_registrations.has_active_enrollment(student_id):
            raise ApplicationNotEditable(
                "This child is already enrolled. Manage their existing classes instead."
            )
