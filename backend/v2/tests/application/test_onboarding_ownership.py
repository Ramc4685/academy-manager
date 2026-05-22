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
)
from backend.v2.contexts.onboarding.domain.errors import ApplicationNotFound
from backend.v2.contexts.onboarding.domain.models import Application


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
