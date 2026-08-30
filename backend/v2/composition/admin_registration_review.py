"""Admin registration review and approval workflow."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, Field

from backend.v2.contexts.enrollment.application.ports import (
    EnrollmentEventRepository,
    EnrollmentWriter,
    SessionWriter,
    StudentWriter,
    WaitlistRepository,
)
from backend.v2.contexts.enrollment.domain.events import (
    EnrollmentLifecycleEvent,
    EnrollmentLifecycleEventType,
)
from backend.v2.contexts.enrollment.domain.models import Enrollment, Session, Student
from backend.v2.contexts.enrollment.domain.models_extra import WaitlistEntry
from backend.v2.contexts.onboarding.application.ports import ApplicationRepository
from backend.v2.contexts.onboarding.application.use_cases.admin_waiver_templates import (
    AdminWaiverTemplateRecord,
)
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationNotEditable,
    ApplicationNotFound,
    IncompleteApplication,
    WaiverNotAccepted,
)
from backend.v2.contexts.onboarding.domain.models import Application, WaiverSignature
from backend.v2.shared.ids import new_ulid, stable_ulid
from backend.v2.shared.tenancy import current_academy_id

logger = logging.getLogger(__name__)
REVIEW_CLAIM_TTL = timedelta(minutes=15)


class RegistrationWaiverTemplateQuery(Protocol):
    async def get_registration_template(self) -> AdminWaiverTemplateRecord | None: ...


class RegistrationWaiverSignatureWriter(Protocol):
    async def save_signature(self, signature: WaiverSignature) -> None: ...


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

    async def claim_registration(
        self,
        student_id: str,
        application_id: str,
        *,
        claim_token: str,
        claimed_at: datetime,
        stale_before: datetime,
    ) -> bool: ...

    async def release_registration(
        self, student_id: str, application_id: str, *, claim_token: str
    ) -> None: ...


class TrialConversionLinker(Protocol):
    """Port for the enrollment context's ``LinkTrialConversion`` use case
    (R3, Task 7). Declared here (rather than imported directly) so this
    composition module documents the cross-context dependency as a narrow
    port instead of depending on the concrete use case class — even though
    ``backend/v2/composition/`` already imports both the enrollment and
    onboarding contexts directly and is exempt from the no-cross-context-
    imports rule (that rule only scans ``backend/v2/contexts/**``)."""

    async def execute(self, *, parent_user_id: str, application_id: str) -> None: ...


class PaidPeriodResolver(Protocol):
    """Port for resolving which billing period a registration checkout
    payment already covered (#506).

    The first-month proration paid at registration checkout is persisted
    with ``enrollment_id=None`` (the enrollment does not exist yet), so
    neither of the monthly generator's dedupe layers can see it. At
    approval time — the first moment the enrollment exists — this port
    resolves the paid period label (e.g. ``"2026-08"``) from the payment's
    consumed calculation snapshot so it can be stamped as a skip period,
    exactly like the zero-quote path stamps ``zero_quote_period``.

    Returns ``None`` when the payment cannot be tied to a successfully
    paid first-month proration period.
    """

    async def paid_period_for_payment(self, payment_id: str) -> str | None: ...


class AdminRegistrationRow(BaseModel):
    model_config = {"frozen": True}

    application_id: str
    status: str
    parent_email: str
    parent_name: str | None = None
    student_name: str | None = None
    selected_session_id: str | None = None
    waiver_required: bool = False
    waiver_satisfied: bool = False
    updated_at: datetime


class AdminRegistrationDetail(AdminRegistrationRow):
    parent_user_id: str
    child_first_name: str = ""
    child_last_name: str = ""
    child_skill_level: str = ""
    payment_id: str | None = None
    student_id: str | None = None
    enrollment_id: str | None = None
    waitlist_id: str | None = None
    session_title: str | None = None
    session_capacity: int | None = None
    waiver_template_id: str | None = None
    waiver_title: str | None = None
    waiver_version: str | None = None


class ApproveRegistrationCommand(BaseModel):
    model_config = {"frozen": True}

    application_id: str
    actor_id: str
    session_id: str | None = None
    waiver_override_reason: str | None = None
    effective_at: datetime | None = None


class WaitlistRegistrationCommand(BaseModel):
    model_config = {"frozen": True}

    application_id: str
    actor_id: str
    session_id: str | None = None
    reason: str | None = None


class RejectRegistrationCommand(BaseModel):
    model_config = {"frozen": True}

    application_id: str
    actor_id: str
    reason: str = Field(min_length=1)


class AdminRegistrationReview:
    def __init__(
        self,
        *,
        apps: ApplicationRepository,
        sessions: SessionWriter,
        students: StudentWriter,
        enrollments: EnrollmentWriter,
        waitlist: WaitlistRepository,
        academy_id: str | None,
        waiver_templates: RegistrationWaiverTemplateQuery | None = None,
        waiver_signatures: RegistrationWaiverSignatureWriter | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        trial_conversion: TrialConversionLinker | None = None,
        student_registrations: StudentRegistrationQuery | None = None,
        paid_period_resolver: PaidPeriodResolver | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._apps = apps
        self._sessions = sessions
        self._students = students
        self._enrollments = enrollments
        self._waitlist = waitlist
        self._academy_id = academy_id
        self._waiver_templates = waiver_templates
        self._waiver_signatures = waiver_signatures
        self._enrollment_events = enrollment_events
        self._trial_conversion = trial_conversion
        self._student_registrations = student_registrations
        self._paid_period_resolver = paid_period_resolver
        self._now = clock

    async def list_pending(self) -> list[AdminRegistrationRow]:
        apps = await self._apps.list_by_status(
            ["PENDING_APPROVAL", "APPROVING", "WAITLISTING", "DECLINING"]
        )
        rows: list[AdminRegistrationRow] = []
        for app in apps:
            if app.status != "PENDING_APPROVAL" and not self._review_claim_is_stale(app):
                continue
            try:
                existing_student_id = await self._active_existing_student_id(app)
            except ApplicationNotEditable:
                # Keep ambiguous legacy identities visible to academy staff
                # without guessing which child record should be changed.
                rows.append((await self._row(app)).model_copy(update={"status": "MANUAL_REVIEW"}))
                continue
            if existing_student_id is None:
                rows.append(await self._row(app))
        return rows

    async def detail(self, application_id: str) -> AdminRegistrationDetail:
        app = await self._get(application_id)
        return await self._detail(app)

    async def approve(self, command: ApproveRegistrationCommand) -> AdminRegistrationDetail:
        app = await self._get(command.application_id)
        if app.status == "APPROVED" and app.enrollment_id:
            return await self._detail(app)
        self._assert_reviewable(app, "APPROVING")
        session_id = command.session_id or app.selected_session_id
        if not session_id:
            raise IncompleteApplication("Registration approval requires a session target")
        if command.session_id and command.session_id != app.selected_session_id:
            raise ApplicationNotEditable(
                "Registration session changed; update the parent application before approval"
            )
        await self._assert_waiver_ready(app, command.waiver_override_reason)

        now = self._now()
        app = await self._claim_review(app, "APPROVING", now)
        student_id: str | None = None
        try:
            student_id = await self._available_student_id(
                app,
                session_id=session_id,
                allow_current_enrollment=True,
            )
            session = await self._sessions.get(session_id)
            if session is None:
                raise IncompleteApplication("Selected session is not available")

            full_name = self._student_name(app)
            await self._students.upsert(
                Student(
                    student_id=student_id,
                    academy_id=self._request_academy_id(),
                    parent_id=app.parent_user_id,
                    full_name=full_name,
                    date_of_birth=app.child_profile.date_of_birth or None,
                    emergency_contact_name=app.child_profile.emergency_contact_name or None,
                    emergency_contact_phone=app.child_profile.emergency_contact_phone or None,
                    medical_notes=app.child_profile.medical_notes or None,
                )
            )
            await self._claim_student_registration(student_id, app)
            await self._renew_review_claim(app)
            expected_enrollment_id = app.enrollment_id or self._registration_enrollment_id(
                app.application_id, student_id, session_id
            )
            await self._assert_no_other_active_enrollment(student_id, expected_enrollment_id)
            existing = await self._enrollments.find_for_session_student(session_id, student_id)
            if existing is not None and (
                existing.enrollment_id != expected_enrollment_id
                or existing.registration_application_id != app.application_id
            ):
                raise ApplicationNotEditable(
                    "This child is already enrolled. Manage their existing classes instead."
                )
            if existing is None:
                reserved = await self._sessions.try_reserve_seat(session_id)
                if not reserved:
                    raise ApplicationNotEditable("Selected session is full; waitlist instead")
            enrollment = Enrollment(
                enrollment_id=expected_enrollment_id,
                academy_id=self._request_academy_id(),
                session_id=session_id,
                student_id=student_id,
                status="active",
                enrolled_at=app.created_at,
                created_at=now,
                registration_application_id=app.application_id,
                registration_student_lock=student_id,
            )
            if existing is None:
                try:
                    created = await self._enrollments.create_if_absent(enrollment)
                except Exception:
                    await self._sessions.release_seat(session_id)
                    raise
                if not created:
                    await self._sessions.release_seat(session_id)
                    existing = await self._enrollments.get(expected_enrollment_id)
                    if (
                        existing is None
                        or existing.registration_application_id != app.application_id
                    ):
                        raise ApplicationNotEditable(
                            "Registration approval conflicted; refresh and try again"
                        )
                    enrollment = existing
            else:
                enrollment = existing
            if enrollment.enrolled_at is None:
                await self._enrollments.set_enrolled_at_if_missing(
                    enrollment.enrollment_id, app.created_at
                )
                enrollment = enrollment.model_copy(update={"enrolled_at": app.created_at})
            if app.zero_quote_period:
                await self._enrollments.add_skip_period(
                    enrollment.enrollment_id, app.zero_quote_period
                )
            # #506: the first-month proration paid at checkout is stored with
            # enrollment_id=None, so the monthly generator's dedupe layers
            # (existing-payment check and CONSUMED-snapshot check) cannot see
            # it and an intra-month generation run would invoice the same
            # period again. Stamp the paid period as a skip period the moment
            # the enrollment exists, mirroring the zero-quote path above.
            # Deliberately NOT wrapped in try/except: failing open here would
            # silently reintroduce the double charge, and approval is safely
            # retryable after a transient failure.
            if app.payment_id and self._paid_period_resolver is not None:
                paid_period = await self._paid_period_resolver.paid_period_for_payment(
                    app.payment_id
                )
                if paid_period:
                    await self._enrollments.add_skip_period(enrollment.enrollment_id, paid_period)
            effective_at = command.effective_at or now
            await self._record_event(
                event_id=stable_ulid("registration-approved-event", app.application_id),
                event_type="created",
                actor_id=command.actor_id,
                enrollment_id=enrollment.enrollment_id,
                session_id=session_id,
                student_id=student_id,
                reason=command.waiver_override_reason or "registration_approved",
                effective_at=effective_at,
            )
            await self._record_registration_waiver_signature(app, student_id)
            await self._release_student_registration(student_id, app)
            decided = app.model_copy(
                update={
                    "status": "APPROVED",
                    "selected_session_id": session_id,
                    "student_id": student_id,
                    "enrollment_id": enrollment.enrollment_id,
                    "decision_reason": command.waiver_override_reason,
                    "decided_by": command.actor_id,
                    "decided_at": now,
                    "review_claimed_at": None,
                    "updated_at": now,
                }
            )
            await self._complete_review(decided, app)
            try:
                await self._link_trial_conversion(decided)
            except Exception:
                logger.exception(
                    "Registration %s was approved, but trial conversion linking failed",
                    decided.application_id,
                )
            return await self._detail(decided)
        except Exception:
            if student_id is not None:
                await self._release_student_registration(student_id, app)
            await self._apps.release_review(
                app.application_id,
                "APPROVING",
                claim_token=self._claim_token(app),
                updated_at=self._now(),
            )
            raise

    async def waitlist(self, command: WaitlistRegistrationCommand) -> AdminRegistrationDetail:
        app = await self._get(command.application_id)
        if app.status == "WAITLISTED" and app.waitlist_id:
            return await self._detail(app)
        self._assert_reviewable(app, "WAITLISTING")
        session_id = command.session_id or app.selected_session_id
        if not session_id:
            raise IncompleteApplication("Waitlisting requires a session target")
        session = await self._sessions.get(session_id)
        if session is None:
            raise IncompleteApplication("Selected session is not available")

        now = self._now()
        app = await self._claim_review(app, "WAITLISTING", now)
        student_id: str | None = None
        try:
            student_id = await self._available_student_id(app)
            await self._students.upsert(
                Student(
                    student_id=student_id,
                    academy_id=self._request_academy_id(),
                    parent_id=app.parent_user_id,
                    full_name=self._student_name(app),
                    date_of_birth=app.child_profile.date_of_birth or None,
                    emergency_contact_name=app.child_profile.emergency_contact_name or None,
                    emergency_contact_phone=app.child_profile.emergency_contact_phone or None,
                    medical_notes=app.child_profile.medical_notes or None,
                )
            )
            await self._claim_student_registration(student_id, app)
            await self._renew_review_claim(app)
            existing = await self._waitlist.find_waiting_for_session_student(session_id, student_id)
            if existing is None:
                entry = WaitlistEntry(
                    waitlist_id=str(new_ulid()),
                    academy_id=self._request_academy_id(),
                    session_id=session_id,
                    student_id=student_id,
                    parent_id=app.parent_user_id,
                    joined_at=now,
                    status="waiting",
                )
                await self._waitlist.add(entry)
                waitlist_id = entry.waitlist_id
            else:
                waitlist_id = existing.waitlist_id
            await self._record_event(
                event_id=stable_ulid("registration-waitlisted-event", app.application_id),
                event_type="waitlisted",
                actor_id=command.actor_id,
                waitlist_id=waitlist_id,
                session_id=session_id,
                student_id=student_id,
                reason=command.reason or "registration_waitlisted",
                effective_at=now,
            )
            await self._record_registration_waiver_signature(app, student_id)
            await self._release_student_registration(student_id, app)
            decided = app.model_copy(
                update={
                    "status": "WAITLISTED",
                    "selected_session_id": session_id,
                    "student_id": student_id,
                    "waitlist_id": waitlist_id,
                    "decision_reason": command.reason,
                    "decided_by": command.actor_id,
                    "decided_at": now,
                    "review_claimed_at": None,
                    "updated_at": now,
                }
            )
            await self._complete_review(decided, app)
            return await self._detail(decided)
        except Exception:
            if student_id is not None:
                await self._release_student_registration(student_id, app)
            await self._apps.release_review(
                app.application_id,
                "WAITLISTING",
                claim_token=self._claim_token(app),
                updated_at=self._now(),
            )
            raise

    async def reject(self, command: RejectRegistrationCommand) -> AdminRegistrationDetail:
        app = await self._get(command.application_id)
        if app.status == "DECLINED":
            return await self._detail(app)
        self._assert_reviewable(app, "DECLINING")
        now = self._now()
        app = await self._claim_review(app, "DECLINING", now)
        await self._renew_review_claim(app)
        decided = app.model_copy(
            update={
                "status": "DECLINED",
                "decision_reason": command.reason,
                "decided_by": command.actor_id,
                "decided_at": now,
                "review_claimed_at": None,
                "updated_at": now,
            }
        )
        try:
            await self._complete_review(decided, app)
        except Exception:
            await self._apps.release_review(
                app.application_id,
                "DECLINING",
                claim_token=self._claim_token(app),
                updated_at=self._now(),
            )
            raise
        return await self._detail(decided)

    async def _get(self, application_id: str) -> Application:
        app = await self._apps.get(application_id)
        if app is None:
            raise ApplicationNotFound("registration application not found")
        return app

    async def _link_trial_conversion(self, app: Application) -> None:
        """R3 conversion tracking hook: after a successful registration
        approval, tell the enrollment context so it can link the newest
        convertible trial request (if any) for this parent to this
        application. No-op if no ``trial_conversion`` port was wired
        (e.g. in tests that don't care about R3), matching
        ``LinkTrialConversion``'s own silent-no-op-on-no-match design."""
        if self._trial_conversion is None:
            return
        await self._trial_conversion.execute(
            parent_user_id=app.parent_user_id,
            application_id=app.application_id,
        )

    def _assert_reviewable(self, app: Application, processing_status: str) -> None:
        if app.status == "PENDING_APPROVAL":
            return
        if app.status == processing_status and self._review_claim_is_stale(app):
            return
        if app.status != "PENDING_APPROVAL":
            raise ApplicationNotEditable("registration is not pending admin approval")

    async def _registration_template(self) -> AdminWaiverTemplateRecord | None:
        if self._waiver_templates is None:
            return None
        return await self._waiver_templates.get_registration_template()

    async def _assert_waiver_ready(
        self, app: Application, waiver_override_reason: str | None
    ) -> None:
        template = await self._registration_template()
        if template is None:
            return
        if app.waiver_acceptance is not None:
            return
        if waiver_override_reason and waiver_override_reason.strip():
            return
        raise WaiverNotAccepted("Required registration waiver is not signed")

    async def _record_registration_waiver_signature(
        self, app: Application, student_id: str
    ) -> None:
        if self._waiver_signatures is None or app.waiver_acceptance is None:
            return
        acceptance = app.waiver_acceptance
        if not acceptance.waiver_template_id:
            return
        signer_name = self._parent_name(app) or str(app.parent_email)
        await self._waiver_signatures.save_signature(
            WaiverSignature(
                waiver_signature_id=(
                    "ws_registration_"
                    f"{app.application_id}_{student_id}_{acceptance.waiver_template_id}"
                ),
                academy_id=self._request_academy_id(),
                waiver_template_id=acceptance.waiver_template_id,
                student_id=student_id,
                parent_user_id=app.parent_user_id,
                signed_at=acceptance.accepted_at,
                signer_name=signer_name,
                signer_email=app.parent_email,
                content_hash=acceptance.content_hash,
            )
        )

    async def _row(self, app: Application) -> AdminRegistrationRow:
        template = await self._registration_template()
        return AdminRegistrationRow(
            application_id=app.application_id,
            status=app.status,
            parent_email=str(app.parent_email),
            parent_name=self._parent_name(app) or None,
            student_name=self._student_name(app) or None,
            selected_session_id=app.selected_session_id,
            waiver_required=template is not None,
            waiver_satisfied=template is None or app.waiver_acceptance is not None,
            updated_at=app.updated_at,
        )

    async def _detail(self, app: Application) -> AdminRegistrationDetail:
        display_app = app
        if app.status == "PENDING_APPROVAL" and self._student_registrations is not None:
            try:
                await self._registration_student_id(app)
            except ApplicationNotEditable:
                display_app = app.model_copy(update={"status": "MANUAL_REVIEW"})
        row = await self._row(display_app)
        template = await self._registration_template()
        session: Session | None = None
        if app.selected_session_id:
            session = await self._sessions.get(app.selected_session_id)
        return AdminRegistrationDetail(
            **row.model_dump(),
            parent_user_id=app.parent_user_id,
            child_first_name=app.child_profile.first_name,
            child_last_name=app.child_profile.last_name,
            child_skill_level=app.child_profile.skill_level,
            payment_id=app.payment_id,
            student_id=app.student_id,
            enrollment_id=app.enrollment_id,
            waitlist_id=app.waitlist_id,
            session_title=session.title if session else None,
            session_capacity=session.capacity if session else None,
            waiver_template_id=template.waiver_template_id if template else None,
            waiver_title=template.title if template else None,
            waiver_version=template.version if template else None,
        )

    @staticmethod
    def _parent_name(app: Application) -> str:
        return f"{app.parent_profile.first_name} {app.parent_profile.last_name}".strip()

    @staticmethod
    def _student_name(app: Application) -> str:
        return f"{app.child_profile.first_name} {app.child_profile.last_name}".strip()

    def _request_academy_id(self) -> str:
        if self._academy_id is not None:
            return self._academy_id
        return current_academy_id()

    async def _registration_student_id(self, app: Application) -> str | None:
        if self._student_registrations is None:
            return app.student_id
        if await self._student_registrations.has_ambiguous_registration_match(
            parent_id=app.parent_user_id,
            full_name=self._student_name(app),
            date_of_birth=app.child_profile.date_of_birth or None,
        ):
            raise ApplicationNotEditable(
                "We found more than one possible child record. Contact the academy to continue."
            )
        resolved = await self._student_registrations.find_registration_student(
            parent_id=app.parent_user_id,
            full_name=self._student_name(app),
            date_of_birth=app.child_profile.date_of_birth or None,
        )
        if resolved is not None:
            return resolved
        # Only retain a non-matching stored binding for replay recovery after
        # this application already owns an enrollment artifact.
        return app.student_id if app.enrollment_id else None

    async def _active_existing_student_id(self, app: Application) -> str | None:
        student_id = await self._registration_student_id(app)
        if student_id is None or self._student_registrations is None:
            return None
        expected_enrollment_id = app.enrollment_id or (
            self._registration_enrollment_id(
                app.application_id, student_id, app.selected_session_id
            )
            if app.selected_session_id
            else None
        )
        if await self._student_registrations.has_active_enrollment(
            student_id,
            exclude_enrollment_id=expected_enrollment_id,
        ):
            return student_id
        return None

    async def _available_student_id(
        self,
        app: Application,
        *,
        session_id: str | None = None,
        allow_current_enrollment: bool = False,
    ) -> str:
        existing_student_id = await self._registration_student_id(app)
        if (
            existing_student_id is not None
            and self._student_registrations is not None
            and await self._student_registrations.has_active_enrollment(
                existing_student_id,
                exclude_enrollment_id=(
                    app.enrollment_id
                    or self._registration_enrollment_id(
                        app.application_id, existing_student_id, session_id
                    )
                    if allow_current_enrollment and session_id
                    else None
                ),
            )
        ):
            raise ApplicationNotEditable(
                "This child is already enrolled. Manage their existing classes instead."
            )
        return (
            existing_student_id
            or (app.student_id if self._student_registrations is None else None)
            or stable_ulid(
                "registration-student",
                self._request_academy_id(),
                app.parent_user_id,
                " ".join(self._student_name(app).casefold().split()),
                app.child_profile.date_of_birth,
            )
        )

    @staticmethod
    def _registration_enrollment_id(application_id: str, student_id: str, session_id: str) -> str:
        return stable_ulid("registration-enrollment", application_id, student_id, session_id)

    async def _claim_review(
        self,
        app: Application,
        processing_status: str,
        now: datetime,
    ) -> Application:
        claimed = await self._apps.claim_for_review(
            app.application_id,
            processing_status,
            claim_token=str(new_ulid()),
            updated_at=now,
            stale_before=now - REVIEW_CLAIM_TTL,
        )
        if claimed is not None:
            return claimed
        raise ApplicationNotEditable(
            "Registration is already being reviewed; refresh and try again"
        )

    async def _claim_student_registration(self, student_id: str, app: Application) -> None:
        if self._student_registrations is None:
            return
        now = self._now()
        if not await self._student_registrations.claim_registration(
            student_id,
            app.application_id,
            claim_token=self._claim_token(app),
            claimed_at=now,
            stale_before=now - REVIEW_CLAIM_TTL,
        ):
            raise ApplicationNotEditable(
                "Another registration for this child is already being reviewed"
            )

    async def _release_student_registration(self, student_id: str, app: Application) -> None:
        if self._student_registrations is not None:
            await self._student_registrations.release_registration(
                student_id,
                app.application_id,
                claim_token=self._claim_token(app),
            )

    async def _assert_no_other_active_enrollment(
        self, student_id: str, expected_enrollment_id: str
    ) -> None:
        if self._student_registrations is None:
            return
        if await self._student_registrations.has_active_enrollment(
            student_id, exclude_enrollment_id=expected_enrollment_id
        ):
            raise ApplicationNotEditable(
                "This child is already enrolled. Manage their existing classes instead."
            )

    async def _renew_review_claim(self, app: Application) -> None:
        if not await self._apps.renew_review_claim(
            app.application_id,
            self._claim_token(app),
            claimed_at=self._now(),
        ):
            raise ApplicationNotEditable(
                "Registration review ownership changed; refresh and try again"
            )

    async def _complete_review(self, decided: Application, claimed: Application) -> None:
        if not await self._apps.complete_review(decided, claim_token=self._claim_token(claimed)):
            raise ApplicationNotEditable(
                "Registration review ownership changed; refresh and try again"
            )

    @staticmethod
    def _claim_token(app: Application) -> str:
        if not app.review_claim_token:
            raise ApplicationNotEditable("Registration review claim is missing")
        return app.review_claim_token

    def _review_claim_is_stale(self, app: Application) -> bool:
        if app.review_claimed_at is None:
            return True
        claimed_at = app.review_claimed_at
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=UTC)
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return claimed_at <= (now - REVIEW_CLAIM_TTL)

    async def _record_event(
        self,
        *,
        event_id: str | None = None,
        event_type: EnrollmentLifecycleEventType,
        actor_id: str,
        session_id: str,
        student_id: str,
        reason: str,
        effective_at: datetime,
        enrollment_id: str | None = None,
        waitlist_id: str | None = None,
    ) -> None:
        if self._enrollment_events is None:
            return
        await self._enrollment_events.record(
            EnrollmentLifecycleEvent(
                event_id=event_id or str(new_ulid()),
                academy_id=self._request_academy_id(),
                event_type=event_type,
                enrollment_id=enrollment_id,
                waitlist_id=waitlist_id,
                session_id=session_id,
                student_id=student_id,
                actor_id=actor_id,
                reason=reason,
                effective_at=effective_at,
                occurred_at=self._now(),
            )
        )
