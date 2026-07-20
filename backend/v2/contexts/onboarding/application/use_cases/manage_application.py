"""Use cases for the parent onboarding stepper.

- StartApplication — idempotently returns an existing DRAFT or creates one.
- PatchApplication — merges parent/child profile, waiver acceptance, selected session.
- GetApplicationStatus — polling endpoint for the checkout-return page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from backend.v2.contexts.onboarding.application.ports import (
    ApplicationRepository,
    WaiverRepository,
)
from backend.v2.contexts.onboarding.domain.errors import (
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


class StartApplicationCommand(BaseModel):
    model_config = {"frozen": True}
    parent_user_id: str
    parent_email: str


class StartApplication:
    def __init__(
        self,
        *,
        apps: ApplicationRepository,
        academy_id: str,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._apps = apps
        self._academy_id = academy_id
        self._now = clock

    async def execute(self, cmd: StartApplicationCommand) -> Application:
        existing = await self._apps.latest_for_parent(cmd.parent_user_id)
        if existing and existing.status in _EDITABLE:
            return existing
        now = self._now()
        app = Application(
            application_id=str(new_ulid()),
            academy_id=self._academy_id,
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
    "DRAFT": {"CHECKOUT_PENDING", "ABANDONED"},
    "CHECKOUT_PENDING": {
        "CHECKOUT_EXPIRED",
        "PENDING_APPROVAL",
        "CAPACITY_FAILED_REFUNDING",
    },
    "CAPACITY_FAILED_REFUNDING": {"REFUNDED", "CAPACITY_FAILED_REFUND_FAILED"},
}


class TransitionApplication:
    """Internal helper used by Billing event handlers + admin paths.

    Enforces the legal-transition table. Idempotent: re-applying the same
    target returns the existing app unchanged.
    """

    def __init__(
        self,
        apps: ApplicationRepository,
        student_registrations: StudentRegistrationQuery | None = None,
        clock=lambda: datetime.now(UTC),
    ) -> None:
        self._apps = apps
        self._student_registrations = student_registrations
        self._now = clock

    async def execute_for_payment(
        self,
        payment_id: str,
        to: str,
    ) -> Application | None:
        """Locate the application by payment_id and transition it.

        Used by Billing event handlers in composition/event_handlers.py.
        No-ops (returns None) if no application is associated with the
        payment (e.g., admin-issued payment without onboarding context).
        """
        app = await self._apps.get_by_payment_id(payment_id)
        if app is None:
            return None
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
            return app
        legal = _TRANSITIONS.get(app.status, set())
        if to not in legal:
            raise ApplicationNotEditable(
                "illegal application transition",
                from_status=app.status,
                to_status=to,
            )
        if to == "CHECKOUT_PENDING":
            await self._assert_child_not_enrolled(app)
        updates: dict[str, object] = {"status": to, "updated_at": self._now()}
        if stripe_checkout_session_id is not None:
            updates["stripe_checkout_session_id"] = stripe_checkout_session_id
        if payment_id is not None:
            updates["payment_id"] = payment_id
        updated = app.model_copy(update=updates)
        await self._apps.save(updated)
        return updated

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
