"""Wave 2 ownership tests — a parent can only read/patch their own
onboarding application. Closes the security gap surfaced by review
comment on PR #18."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
    APPLICATION_TTL_DAYS,
    GetApplicationStatus,
    PatchApplication,
    PatchApplicationCommand,
    TransitionApplication,
)
from backend.v2.contexts.onboarding.domain.errors import (
    ApplicationNotEditable,
    ApplicationNotFound,
)
from backend.v2.contexts.onboarding.domain.models import Application, ChildProfile


class FakeAppRepo:
    def __init__(self, app: Application | None) -> None:
        self._app = app

    async def save(self, app):
        self._app = app

    async def get(self, application_id):
        return self._app if self._app and self._app.application_id == application_id else None

    async def latest_for_parent(self, _):
        return self._app

    async def get_by_payment_id(self, _):
        return self._app


class FakeWaiverRepo:
    async def get_active(self):
        return None


class ExistingStudentRegistrations:
    async def find_registration_student(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> str | None:
        return "existing-student"

    async def has_ambiguous_registration_match(
        self,
        *,
        parent_id: str,
        full_name: str,
        date_of_birth: str | None,
    ) -> bool:
        return False

    async def has_active_enrollment(
        self,
        student_id: str,
        *,
        exclude_enrollment_id: str | None = None,
    ) -> bool:
        return student_id == "existing-student"


class ConfigurableStudentRegistrations:
    def __init__(
        self,
        *,
        student_id: str | None = None,
        active: bool = False,
        ambiguous: bool = False,
    ) -> None:
        self.student_id = student_id
        self.active = active
        self.ambiguous = ambiguous

    async def find_registration_student(self, **kwargs) -> str | None:
        return self.student_id

    async def has_ambiguous_registration_match(self, **kwargs) -> bool:
        return self.ambiguous

    async def has_active_enrollment(
        self, student_id: str, *, exclude_enrollment_id: str | None = None
    ) -> bool:
        return self.active and student_id == self.student_id


def _app(parent_user_id: str = "alice") -> Application:
    now = datetime.now(UTC)
    return Application(
        application_id="app-1",
        academy_id="acad",
        parent_user_id=parent_user_id,
        parent_email=f"{parent_user_id}@example.com",
        status="DRAFT",
        expires_at=now + timedelta(days=APPLICATION_TTL_DAYS),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_patch_application_rejects_other_parent() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = PatchApplication(apps=repo, waivers=FakeWaiverRepo())
    with pytest.raises(ApplicationNotFound):
        await uc.execute(
            PatchApplicationCommand(
                application_id="app-1",
                caller_user_id="bob",  # different parent
            )
        )


@pytest.mark.asyncio
async def test_patch_application_allows_owner() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = PatchApplication(apps=repo, waivers=FakeWaiverRepo())
    result = await uc.execute(
        PatchApplicationCommand(
            application_id="app-1",
            caller_user_id="alice",
            parent_profile={"first_name": "Alice"},
        )
    )
    assert result.parent_profile.first_name == "Alice"


@pytest.mark.asyncio
async def test_patch_application_rejects_an_already_enrolled_child() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = PatchApplication(apps=repo, waivers=FakeWaiverRepo())
    uc._student_registrations = ExistingStudentRegistrations()  # type: ignore[attr-defined]

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await uc.execute(
            PatchApplicationCommand(
                application_id="app-1",
                caller_user_id="alice",
                child_profile={
                    "first_name": "Sam",
                    "last_name": "Student",
                    "date_of_birth": "2015-05-10",
                    "skill_level": "beginner",
                },
            )
        )

    assert repo._app is not None
    assert repo._app.child_profile.first_name == ""


@pytest.mark.asyncio
async def test_patch_child_profile_clears_stale_student_binding_when_identity_changes() -> None:
    repo = FakeAppRepo(_app().model_copy(update={"student_id": "old-student"}))
    registrations = ConfigurableStudentRegistrations(student_id=None)
    uc = PatchApplication(
        apps=repo,
        waivers=FakeWaiverRepo(),
        student_registrations=registrations,
    )

    result = await uc.execute(
        PatchApplicationCommand(
            application_id="app-1",
            caller_user_id="alice",
            child_profile={
                "first_name": "Different",
                "last_name": "Child",
                "date_of_birth": "2017-01-02",
                "skill_level": "beginner",
            },
        )
    )

    assert result.student_id is None


@pytest.mark.asyncio
async def test_patch_rejects_ambiguous_legacy_child_match() -> None:
    repo = FakeAppRepo(_app())
    uc = PatchApplication(
        apps=repo,
        waivers=FakeWaiverRepo(),
        student_registrations=ConfigurableStudentRegistrations(ambiguous=True),
    )

    with pytest.raises(ApplicationNotEditable, match="more than one possible child"):
        await uc.execute(
            PatchApplicationCommand(
                application_id="app-1",
                caller_user_id="alice",
                child_profile={
                    "first_name": "Sam",
                    "last_name": "Student",
                    "date_of_birth": "",
                    "skill_level": "beginner",
                },
            )
        )


@pytest.mark.asyncio
async def test_checkout_transition_rechecks_active_enrollment() -> None:
    app = _app().model_copy(
        update={
            "student_id": "existing-student",
            "child_profile": ChildProfile(
                first_name="Sam",
                last_name="Student",
                date_of_birth="2015-05-10",
                skill_level="beginner",
            ),
        }
    )
    repo = FakeAppRepo(app)
    uc = TransitionApplication(
        apps=repo,
        student_registrations=ConfigurableStudentRegistrations(
            student_id="existing-student", active=True
        ),
    )

    with pytest.raises(ApplicationNotEditable, match="already enrolled"):
        await uc.execute("app-1", "CHECKOUT_PENDING")

    assert repo._app is not None
    assert repo._app.status == "DRAFT"


@pytest.mark.asyncio
async def test_get_status_with_caller_rejects_other_parent() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = GetApplicationStatus(apps=repo)
    with pytest.raises(ApplicationNotFound):
        await uc.execute("app-1", caller_user_id="bob")


@pytest.mark.asyncio
async def test_get_status_with_caller_allows_owner() -> None:
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = GetApplicationStatus(apps=repo)
    result = await uc.execute("app-1", caller_user_id="alice")
    assert result.application_id == "app-1"


@pytest.mark.asyncio
async def test_get_status_without_caller_skips_check() -> None:
    """Webhook handlers and admin paths call without caller_user_id."""
    repo = FakeAppRepo(_app(parent_user_id="alice"))
    uc = GetApplicationStatus(apps=repo)
    result = await uc.execute("app-1")
    assert result.application_id == "app-1"


@pytest.mark.asyncio
async def test_start_application_prefills_parent_profile_from_prior_application() -> None:
    """A returning parent adding a second child must not retype their own
    details: the new draft carries parent_profile from the last application."""
    from backend.v2.contexts.onboarding.application.use_cases.manage_application import (
        StartApplication,
        StartApplicationCommand,
    )
    from backend.v2.contexts.onboarding.domain.models import ParentProfile

    prior = _app(parent_user_id="alice").model_copy(
        update={
            "status": "COMPLETED",
            "parent_profile": ParentProfile(first_name="Alice", last_name="Ng", phone="5551234"),
        }
    )
    repo = FakeAppRepo(prior)
    uc = StartApplication(apps=repo, academy_id=lambda: "acad")

    fresh = await uc.execute(
        StartApplicationCommand(parent_user_id="alice", parent_email="alice@example.com")
    )

    assert fresh.application_id != prior.application_id
    assert fresh.status == "DRAFT"
    assert fresh.parent_profile.first_name == "Alice"
    assert fresh.parent_profile.last_name == "Ng"
    assert fresh.parent_profile.phone == "5551234"
    # Child details must start blank for the new application.
    assert fresh.child_profile.first_name == ""
