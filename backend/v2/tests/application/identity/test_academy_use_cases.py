from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.get_academy_fees_use_case import (
    GetAcademyFeesUseCase,
)
from backend.v2.contexts.identity.application.get_academy_notifications_use_case import (
    GetAcademyNotificationsUseCase,
)
from backend.v2.contexts.identity.application.get_academy_use_case import (
    GetAcademyUseCase,
)
from backend.v2.contexts.identity.application.update_academy_fees_use_case import (
    UpdateAcademyFeesUseCase,
)
from backend.v2.contexts.identity.application.update_academy_notifications_use_case import (
    UpdateAcademyNotificationsUseCase,
)
from backend.v2.contexts.identity.application.update_academy_use_case import (
    UpdateAcademyUseCase,
)


@pytest.mark.asyncio
async def test_get_academy_returns_view_when_found():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "display_name": "Court 7",
        "timezone": "America/New_York",
    }
    use_case = GetAcademyUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1")
    assert output.academy_id == "acad-1"
    assert output.display_name == "Court 7"
    assert output.timezone == "America/New_York"
    assert output.contact_email is None

@pytest.mark.asyncio
async def test_get_academy_upserts_with_defaults_when_missing():
    repo = AsyncMock()
    repo.find_by_id.return_value = None
    repo.upsert_defaults.return_value = {
        "_id": "default-academy",
        "display_name": "default-academy",
        "timezone": "UTC",
    }
    use_case = GetAcademyUseCase(academy_repo=repo)
    output = await use_case.execute("default-academy")
    assert output.academy_id == "default-academy"
    assert output.display_name == "default-academy"
    assert output.timezone == "UTC"
    assert output.contact_email is None
    repo.upsert_defaults.assert_awaited_once_with("default-academy")

@pytest.mark.asyncio
async def test_update_academy_partial_set():
    repo = AsyncMock()
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "display_name": "Court 7",
        "timezone": "America/New_York",
        "contact_email": "ops@court7.example",
    }
    use_case = UpdateAcademyUseCase(academy_repo=repo)
    output = await use_case.execute(
        "acad-1", {"contact_email": "ops@court7.example"}
    )
    assert output.contact_email == "ops@court7.example"
    repo.update_by_id.assert_awaited_once_with(
        "acad-1", {"contact_email": "ops@court7.example"},
    )

@pytest.mark.asyncio
async def test_update_academy_raises_when_missing():
    repo = AsyncMock()
    repo.update_by_id.return_value = None
    use_case = UpdateAcademyUseCase(academy_repo=repo)
    with pytest.raises(LookupError):
        await use_case.execute("missing", {"display_name": "X"})

# --- Fees ---

@pytest.mark.asyncio
async def test_get_academy_fees():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "default_monthly_cents": 10000,
        "late_fee_cents": 1500,
        "grace_days": 3,
    }
    use_case = GetAcademyFeesUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1")
    assert output.default_monthly_cents == 10000
    assert output.late_fee_cents == 1500
    assert output.grace_days == 3

@pytest.mark.asyncio
async def test_update_academy_fees():
    repo = AsyncMock()
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "default_monthly_cents": 10000,
        "late_fee_cents": 2000,
        "grace_days": 3,
    }
    use_case = UpdateAcademyFeesUseCase(academy_repo=repo)
    output = await use_case.execute(
        "acad-1", {"late_fee_cents": 2000}
    )
    assert output.late_fee_cents == 2000
    repo.update_by_id.assert_awaited_once_with("acad-1", {"fees.late_fee_cents": 2000})

# --- Notifications ---

@pytest.mark.asyncio
async def test_get_academy_notifications():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "dues_reminders": True,
        "attendance_alerts": False,
        "daily_digest_to_admin": True,
    }
    use_case = GetAcademyNotificationsUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1")
    assert output.dues_reminders is True
    assert output.attendance_alerts is False
    assert output.daily_digest_to_admin is True

@pytest.mark.asyncio
async def test_update_academy_notifications():
    repo = AsyncMock()
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "dues_reminders": True,
        "attendance_alerts": True,
        "daily_digest_to_admin": True,
    }
    use_case = UpdateAcademyNotificationsUseCase(academy_repo=repo)
    output = await use_case.execute(
        "acad-1", {"attendance_alerts": True}
    )
    assert output.attendance_alerts is True
    repo.update_by_id.assert_awaited_once_with("acad-1", {"notifications.attendance_alerts": True})
