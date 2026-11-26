"""Use cases for the parent onboarding stepper.

- StartApplication — returns an existing DRAFT, RESUMES an abandoned checkout,
  or creates a new application.
- PatchApplication — merges parent/child profile, waiver acceptance, selected session.
- GetApplicationStatus — polling endpoint for the checkout-return page.
- ListParentRegistrations — the family's unfinished and not-yet-confirmed
  registrations (S02), so a child never vanishes between wizard and roster.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.application.ports import (
    ApplicationRepository,
    RegistrationSubmittedNotifier,
    WaiverRepository,
)
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationForPaymentNotFound,
    ApplicationNotEditable,
    ApplicationNotFound,
    NoActiveWaiver,
    WaiverDateOfBirthMissing,
    WaiverSignatureIncomplete,
)
from backend.v2.contexts.onboarding.domain.models import (
    ESIGN_CONSENT_TEXT,
    Application,
    ChildProfile,
    ParentProfile,
    Waiver,
    WaiverAcceptance,
    clean_signer_name,
)
from backend.v2.contexts.onboarding.domain.waiver_sections import (
    SigningPath,
    has_age_paths,
    missing_initials,
    parse_sections,
    signing_path_for,
)
from backend.v2.shared.ids import new_ulid
from backend.v2.shared.time.mongo import ensure_utc

_EDITABLE = {"DRAFT"}
APPLICATION_TTL_DAYS = 7
# The status a resumed checkout returns to. Kept as a name (rather than a bare
# "DRAFT" literal at each site) because the legality of the move lives in
# _TRANSITIONS, not in the resume code — see StartApplication._resume.
_RESUME_TO = "DRAFT"


logger = logging.getLogger(__name__)

#: S02: the plain state a family sees for each application that is not yet an
#: enrolled child. "finish" goes back into the wizard; nothing new is stored.
REGISTRATION_STATES: dict[str, str] = {
    "DRAFT": "finish",
    "CHECKOUT_PENDING": "finish",
    "CHECKOUT_EXPIRED": "finish",
    "PENDING_APPROVAL": "waiting",
    "APPROVING": "waiting",
    "WAITLISTING": "waitlisted",
    "WAITLISTED": "waitlisted",
    "DECLINING": "declined",
    "DECLINED": "declined",
}
#: An application here already asks the academy for a seat: a second one for
#: the same child and class is a duplicate (S02).
_SUBMITTED = ["CHECKOUT_PENDING", "PENDING_APPROVAL", "APPROVING", "WAITLISTING", "WAITLISTED"]
DECLINED_VISIBLE_FOR = timedelta(days=30)
#: A checkout this fresh may already be paid while Stripe's webhook is in
#: flight, so the family is not invited to pay it again.
CHECKOUT_IN_FLIGHT_FOR = timedelta(minutes=15)
#: Payment statuses that mean money for a CHECKOUT_PENDING application arrived.
_PAID = {"succeeded", "partially_paid"}


def _child_key(app: Application) -> str:
    child = app.child_profile
    return " ".join(f"{child.first_name} {child.last_name}".lower().split())


def same_child(a: Application, b: Application) -> bool:
    """The student record when both carry one, otherwise the normalised name.

    Twins have different first names, so they never match each other.
    """
    if a.student_id and b.student_id:
        return a.student_id == b.student_id
    key = _child_key(a)
    return bool(key) and key == _child_key(b)


async def _open_duplicate(
    apps: ApplicationRepository, app: Application, now: datetime
) -> Application | None:
    """S02: another open registration for the same child and class, if any.

    A second class for the same child, or a twin in the same class, is a
    different child-and-class pair and is not a duplicate.
    """
    if not app.selected_session_id:
        return None
    for other in await apps.list_open_for_parent(app.parent_user_id, _SUBMITTED):
        if (
            other.application_id != app.application_id
            and other.selected_session_id == app.selected_session_id
            and same_child(other, app)
            # An unpaid checkout whose expiry webhook never came must not block forever.
            and not other.is_expired(now)
        ):
            return other
    return None


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
    #: S02: "Finish registration" on a card that is not the latest application.
    application_id: str | None = None


class StartApplication:
    def __init__(
        self,
        *,
        apps: ApplicationRepository,
        academy_id: Callable[[], str],
        clock=lambda: datetime.now(UTC),
        checkout_retirement: SupersededCheckoutRetirement | None = None,
        account_profile: Callable[[str], Awaitable[ParentProfile | None]] | None = None,
    ) -> None:
        self._apps = apps
        self._academy_id = academy_id
        self._now = clock
        self._checkout_retirement = checkout_retirement
        # S21 persona follow-up: the account's own name and phone, so a parent
        # with no earlier application does not retype them on the parent step.
        self._account_profile = account_profile

    async def execute(self, cmd: StartApplicationCommand) -> Application:
        requested = await self._requested(cmd)
        existing = requested or await self._apps.latest_for_parent(cmd.parent_user_id)
        if existing is not None and existing.is_expired(self._now()):
            # The TTL passed with nobody finishing the wizard or Stripe.
            # Retire it (issue #537) rather than handing it back below, or a
            # parent who abandoned a draft weeks ago keeps editing/paying
            # against a quote and a seat hold that should already be gone.
            await self._apps.save(
                existing.model_copy(update={"status": "ABANDONED", "updated_at": self._now()})
            )
            existing = None
        refused: Application | None = None
        if existing and existing.status in _EDITABLE:
            if (
                requested is not None
                or await _open_duplicate(self._apps, existing, self._now()) is None
            ):
                return existing
            # S02 persona follow-up: checkout already refused this draft as a
            # duplicate of an open registration, so "Add a child" handing it back
            # is a dead end. Retire it; the family's details carry over below.
            await self._apps.save(
                existing.model_copy(update={"status": "ABANDONED", "updated_at": self._now()})
            )
            refused, existing = existing, None
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
        previous = existing or requested or refused
        if previous is not None:
            # Returning parent adding another child: carry their own details
            # over from the previous application so they never retype them.
            # The child profile intentionally starts blank.
            app = app.model_copy(update={"parent_profile": previous.parent_profile})
        app = await self._fill_from_account(app)
        if requested is not None and existing is not None:
            # Re-read after a missed resume: paid in another tab means no copy.
            requested = existing if existing.application_id == requested.application_id else None
        if requested is not None and REGISTRATION_STATES.get(requested.status) == "finish":
            # An expired checkout the family asked to finish: start again with
            # the same child and class, never the old payment or waiver.
            app = app.model_copy(
                update={
                    "child_profile": requested.child_profile,
                    "student_id": requested.student_id,
                    "selected_session_id": requested.selected_session_id,
                }
            )
        await self._apps.save(app)
        return app

    async def _fill_from_account(self, app: Application) -> Application:
        """Blank parent name and phone come from the account; typed values win."""
        profile = app.parent_profile
        fields = ("first_name", "last_name", "phone")
        if self._account_profile is None or all(getattr(profile, f).strip() for f in fields):
            return app
        account = await self._account_profile(app.parent_user_id)
        if account is None:
            return app
        blanks = {
            f: getattr(account, f).strip()
            for f in fields
            if not getattr(profile, f).strip() and getattr(account, f).strip()
        }
        if not blanks:
            return app
        return app.model_copy(update={"parent_profile": profile.model_copy(update=blanks)})

    async def _requested(self, cmd: StartApplicationCommand) -> Application | None:
        if not cmd.application_id:
            return None
        app = await self._apps.get(cmd.application_id)
        # Someone else's id is ignored, never an error a parent could probe with.
        return app if app is not None and app.parent_user_id == cmd.parent_user_id else None

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
    # Required with ``accept_waiver``: the typed full name and consent box.
    signer_name: str | None = None
    consent: bool = False
    ip_address: str | None = None
    user_agent: str | None = None
    # waiver id -> {section key: initials} for sections marked [initials].
    initials: dict[str, dict[str, str]] | None = None
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
        if app.status not in _EDITABLE or app.is_expired(self._now()):
            raise ApplicationNotEditable(
                "application is not in an editable state",
                status=app.status,
            )

        waiver_acceptance = app.waiver_acceptance
        additional_acceptances = app.additional_waiver_acceptances
        session_id = cmd.selected_session_id or app.selected_session_id
        if cmd.accept_waiver:
            signer_name = clean_signer_name(cmd.signer_name)
            if signer_name is None or not cmd.consent:
                raise WaiverSignatureIncomplete(
                    "Type your full name and tick the consent box to sign.",
                    missing_name=signer_name is None,
                    missing_consent=not cmd.consent,
                )
            # Everything this class's family signs: the all-families waivers
            # plus the ones assigned to the class's program. First = primary.
            required = await self._waivers.list_required(session_id)
            if not required:
                raise NoActiveWaiver("no active waiver to accept")
            accepted_at = self._now()
            birth_date = str(
                (cmd.child_profile or {}).get("date_of_birth") or app.child_profile.date_of_birth
            )
            paths = _registration_paths(required, birth_date, accepted_at)
            given = cmd.initials or {}
            unmet = {
                waiver.waiver_id: keys
                for waiver in required
                if (
                    keys := missing_initials(
                        parse_sections(waiver.text),
                        paths[waiver.waiver_id],
                        given.get(waiver.waiver_id, {}),
                    )
                )
            }
            if unmet:
                raise WaiverSignatureIncomplete(
                    "Initial every section marked for initials to sign.", missing_initials=unmet
                )
            accepted = [
                WaiverAcceptance(
                    waiver_version=waiver.version,
                    content_hash=waiver.content_hash,
                    accepted_at=accepted_at,
                    waiver_template_id=waiver.waiver_id,
                    lineage_key=waiver.lineage_key,
                    signer_name=signer_name,
                    consent_text=ESIGN_CONSENT_TEXT,
                    ip_address=cmd.ip_address,
                    user_agent=cmd.user_agent,
                    initials={
                        key: value.strip().upper()
                        for key, value in given.get(waiver.waiver_id, {}).items()
                        if value.strip()
                    },
                    signing_path=paths[waiver.waiver_id],
                )
                for waiver in required
            ]
            waiver_acceptance = accepted[0]
            additional_acceptances = accepted[1:]
        elif (
            cmd.selected_session_id
            and cmd.selected_session_id != app.selected_session_id
            and app.waiver_acceptance is not None
        ):
            # A different class can add a required waiver: a parent who signed
            # the first set is asked again only for what is now missing, by
            # clearing the acceptance so the waiver step shows the new set.
            # Same set (one waiver for everyone) leaves the acceptance alone.
            required = await self._waivers.list_required(cmd.selected_session_id)
            accepted_lineages = {
                item.lineage_key or "legacy" for item in app.all_waiver_acceptances
            }
            if any(waiver.lineage_key not in accepted_lineages for waiver in required):
                waiver_acceptance = None
                additional_acceptances = []

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
                "additional_waiver_acceptances": additional_acceptances,
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


class ListParentRegistrations:
    """S02: the family's applications that are not finished or not confirmed.

    One row per child and class. A submitted (or approved) application wins
    over any unfinished attempt for the same pair, whatever their order; among
    equals the newest wins. Unfinished rows past the 7-day TTL are dropped so
    old abandoned wizards never resurface. Applications with no child named
    yet are wizard scratch, not a child.
    """

    def __init__(
        self,
        apps: ApplicationRepository,
        clock=lambda: datetime.now(UTC),
        payment_status: Callable[[str], Awaitable[str | None]] | None = None,
    ) -> None:
        self._apps = apps
        self._now = clock
        self._payment_status = payment_status

    async def execute(self, parent_user_id: str) -> list[tuple[Application, str]]:
        now = self._now()
        fetched = await self._apps.list_open_for_parent(
            parent_user_id, [*REGISTRATION_STATES, "APPROVED"]
        )
        rows: list[tuple[Application, str]] = []
        # Stable sort: submitted rows claim their child-and-class pair first.
        for app in sorted(fetched, key=lambda a: REGISTRATION_STATES.get(a.status) == "finish"):
            state = "done" if app.status == "APPROVED" else REGISTRATION_STATES.get(app.status)
            if state is None or app.parent_user_id != parent_user_id:
                continue
            if not app.child_profile.first_name.strip():
                continue
            if state == "finish" and (
                app.is_expired(now)
                or ensure_utc(app.updated_at) < now - timedelta(days=APPLICATION_TTL_DAYS)
            ):
                continue
            if state == "declined" and (
                ensure_utc(app.decided_at or app.updated_at) < now - DECLINED_VISIBLE_FOR
            ):
                continue
            if app.status == "CHECKOUT_PENDING" and await self._checkout_in_flight(app, now):
                state = "paying"
            if any(
                seen.selected_session_id == app.selected_session_id and same_child(seen, app)
                for seen, _ in rows
            ):
                continue
            rows.append((app, state))
        rows.sort(key=lambda r: r[0].created_at, reverse=True)
        return [(a, state) for a, state in rows if state != "done"]

    async def _checkout_in_flight(self, app: Application, now: datetime) -> bool:
        """Paid, or so fresh the payment webhook may still be on its way."""
        if ensure_utc(app.updated_at) > now - CHECKOUT_IN_FLIGHT_FOR:
            return True
        if self._payment_status is None or not app.payment_id:
            return False
        return await self._payment_status(app.payment_id) in _PAID


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
        submitted_notifier: RegistrationSubmittedNotifier | None = None,
    ) -> None:
        self._apps = apps
        self._student_registrations = student_registrations
        self._now = clock
        self._checkout_retirement = checkout_retirement
        self._submitted_notifier = submitted_notifier

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
            await self._assert_no_open_duplicate(app)
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
        if to == "PENDING_APPROVAL":
            await self._alert_staff(updated)
        return updated

    async def _alert_staff(self, app: Application) -> None:
        """Issue #776: a new application landing in the review queue is news.

        After the save, and never able to undo it: the money has usually
        already moved by this point, so a mail outage must not be what leaves a
        paid registration outside ``PENDING_APPROVAL``.
        """
        if self._submitted_notifier is None:
            return
        child = app.child_profile
        student_name = f"{child.first_name} {child.last_name}".strip() or "New student"
        parent = app.parent_profile
        parent_name = f"{parent.first_name} {parent.last_name}".strip() or None
        try:
            await self._submitted_notifier.registration_submitted(
                application_id=app.application_id,
                student_name=student_name,
                parent_name=parent_name,
                session_id=app.selected_session_id,
            )
        except Exception:
            logger.exception(
                "registration_staff_alert_failed",
                extra={"application_id": app.application_id},
            )

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

    async def _assert_no_open_duplicate(self, app: Application) -> None:
        """S02: one open registration per child and class.

        A second class for the same child, or a twin in the same class, is a
        different child-and-class pair and goes through.
        """
        other = await _open_duplicate(self._apps, app, self._now())
        if other is None:
            return
        name = app.child_profile.first_name.strip() or "This child"
        if other.status == "CHECKOUT_PENDING":
            raise ApplicationNotEditable(
                f"{name} has an unfinished registration for this class. "
                "Use Finish registration on your Home page."
            )
        raise ApplicationNotEditable(
            f"{name} is already registered for this class. "
            "You can see it on your Home page; we will email you when the academy confirms."
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


def _registration_paths(
    required: list[Waiver], date_of_birth: str, day: datetime
) -> dict[str, SigningPath | None]:
    """The adult/minor path per waiver for the child being registered.

    Only waivers with age-specific sections need one; a missing date of birth
    on those refuses the signature.
    """
    paths: dict[str, SigningPath | None] = {}
    for waiver in required:
        if not has_age_paths(parse_sections(waiver.text)):
            paths[waiver.waiver_id] = None
            continue
        # shortcut: UTC date, see parent_student_waivers._path_for.
        path = signing_path_for(date_of_birth, day.date())
        if path is None:
            raise WaiverDateOfBirthMissing(
                "Add the child's date of birth to sign this waiver.", students=["child"]
            )
        paths[waiver.waiver_id] = path
    return paths
