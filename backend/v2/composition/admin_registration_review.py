"""Admin registration review and approval workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
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
from backend.v2.contexts.onboarding.domain.models import Application
from backend.v2.shared.ids import new_ulid


class RegistrationWaiverTemplateQuery(Protocol):
    async def get_registration_template(self) -> AdminWaiverTemplateRecord | None: ...


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
        academy_id: str,
        waiver_templates: RegistrationWaiverTemplateQuery | None = None,
        enrollment_events: EnrollmentEventRepository | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._apps = apps
        self._sessions = sessions
        self._students = students
        self._enrollments = enrollments
        self._waitlist = waitlist
        self._academy_id = academy_id
        self._waiver_templates = waiver_templates
        self._enrollment_events = enrollment_events
        self._now = clock

    async def list_pending(self) -> list[AdminRegistrationRow]:
        apps = await self._apps.list_by_status(["PENDING_APPROVAL"])
        return [await self._row(app) for app in apps]

    async def detail(self, application_id: str) -> AdminRegistrationDetail:
        app = await self._get(application_id)
        return await self._detail(app)

    async def approve(self, command: ApproveRegistrationCommand) -> AdminRegistrationDetail:
        app = await self._get(command.application_id)
        if app.status == "APPROVED" and app.enrollment_id:
            return await self._detail(app)
        self._assert_reviewable(app)
        session_id = command.session_id or app.selected_session_id
        if not session_id:
            raise IncompleteApplication("Registration approval requires a session target")
        await self._assert_waiver_ready(app, command.waiver_override_reason)

        now = self._now()
        student_id = app.student_id or str(new_ulid())
        existing = await self._enrollments.find_for_session_student(session_id, student_id)
        session = await self._sessions.get(session_id)
        if session is None:
            raise IncompleteApplication("Selected session is not available")
        if existing is None:
            reserved = await self._sessions.try_reserve_seat(session_id)
            if not reserved:
                raise ApplicationNotEditable("Selected session is full; waitlist instead")

        full_name = self._student_name(app)
        await self._students.upsert(
            Student(
                student_id=student_id,
                academy_id=self._academy_id,
                parent_id=app.parent_user_id,
                full_name=full_name,
            )
        )
        enrollment = Enrollment(
            enrollment_id=app.enrollment_id or str(new_ulid()),
            academy_id=self._academy_id,
            session_id=session_id,
            student_id=student_id,
            status="active",
        )
        if existing is None:
            await self._enrollments.create(enrollment)
        else:
            enrollment = existing
        effective_at = command.effective_at or now
        await self._record_event(
            event_type="created",
            actor_id=command.actor_id,
            enrollment_id=enrollment.enrollment_id,
            session_id=session_id,
            student_id=student_id,
            reason=command.waiver_override_reason or "registration_approved",
            effective_at=effective_at,
        )
        decided = app.model_copy(
            update={
                "status": "APPROVED",
                "selected_session_id": session_id,
                "student_id": student_id,
                "enrollment_id": enrollment.enrollment_id,
                "decision_reason": command.waiver_override_reason,
                "decided_by": command.actor_id,
                "decided_at": now,
                "updated_at": now,
            }
        )
        await self._apps.save(decided)
        return await self._detail(decided)

    async def waitlist(self, command: WaitlistRegistrationCommand) -> AdminRegistrationDetail:
        app = await self._get(command.application_id)
        if app.status == "WAITLISTED" and app.waitlist_id:
            return await self._detail(app)
        self._assert_reviewable(app)
        session_id = command.session_id or app.selected_session_id
        if not session_id:
            raise IncompleteApplication("Waitlisting requires a session target")
        session = await self._sessions.get(session_id)
        if session is None:
            raise IncompleteApplication("Selected session is not available")

        now = self._now()
        student_id = app.student_id or str(new_ulid())
        await self._students.upsert(
            Student(
                student_id=student_id,
                academy_id=self._academy_id,
                parent_id=app.parent_user_id,
                full_name=self._student_name(app),
            )
        )
        existing = await self._waitlist.find_waiting_for_session_student(session_id, student_id)
        if existing is None:
            entry = WaitlistEntry(
                waitlist_id=str(new_ulid()),
                academy_id=self._academy_id,
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
            event_type="waitlisted",
            actor_id=command.actor_id,
            waitlist_id=waitlist_id,
            session_id=session_id,
            student_id=student_id,
            reason=command.reason or "registration_waitlisted",
            effective_at=now,
        )
        decided = app.model_copy(
            update={
                "status": "WAITLISTED",
                "selected_session_id": session_id,
                "student_id": student_id,
                "waitlist_id": waitlist_id,
                "decision_reason": command.reason,
                "decided_by": command.actor_id,
                "decided_at": now,
                "updated_at": now,
            }
        )
        await self._apps.save(decided)
        return await self._detail(decided)

    async def reject(self, command: RejectRegistrationCommand) -> AdminRegistrationDetail:
        app = await self._get(command.application_id)
        if app.status == "DECLINED":
            return await self._detail(app)
        self._assert_reviewable(app)
        now = self._now()
        decided = app.model_copy(
            update={
                "status": "DECLINED",
                "decision_reason": command.reason,
                "decided_by": command.actor_id,
                "decided_at": now,
                "updated_at": now,
            }
        )
        await self._apps.save(decided)
        return await self._detail(decided)

    async def _get(self, application_id: str) -> Application:
        app = await self._apps.get(application_id)
        if app is None:
            raise ApplicationNotFound("registration application not found")
        return app

    @staticmethod
    def _assert_reviewable(app: Application) -> None:
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
        row = await self._row(app)
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

    async def _record_event(
        self,
        *,
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
                event_id=str(new_ulid()),
                academy_id=self._academy_id,
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
