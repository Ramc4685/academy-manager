from datetime import UTC, datetime
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
    output = await use_case.execute("acad-1", {"contact_email": "ops@court7.example"})
    assert output.contact_email == "ops@court7.example"
    repo.update_by_id.assert_awaited_once_with(
        "acad-1",
        {"contact_email": "ops@court7.example"},
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
        "fees": {"late_fee_cents": 1500, "grace_days": 3},
    }
    use_case = GetAcademyFeesUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1")
    assert output.late_fee_cents == 1500
    assert output.grace_days == 3


@pytest.mark.asyncio
async def test_update_academy_fees():
    repo = AsyncMock()
    repo.find_by_id.return_value = {"_id": "acad-1", "fees": {"late_fee_cents": 1500}}
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "fees": {"late_fee_cents": 2000, "grace_days": 3},
    }
    use_case = UpdateAcademyFeesUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1", {"late_fee_cents": 2000})
    assert output.late_fee_cents == 2000
    # Already on: raising the amount must not move the start date.
    repo.update_by_id.assert_awaited_once_with("acad-1", {"fees.late_fee_cents": 2000})


# --- Notifications ---


@pytest.mark.asyncio
async def test_get_academy_notifications():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "daily_digest_to_admin": True,
    }
    use_case = GetAcademyNotificationsUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1")
    assert output.daily_digest_to_admin is True


@pytest.mark.asyncio
async def test_get_academy_notifications_uses_digest_env_fallback_when_override_unset():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "notifications": {
            "daily_digest_to_admin": False,
        },
    }
    use_case = GetAcademyNotificationsUseCase(
        academy_repo=repo,
        default_coach_digest_enabled=True,
        default_coach_digest_hour=18,
    )

    output = await use_case.execute("acad-1")

    assert output.coach_digest_enabled is True
    assert output.coach_digest_hour == 18


@pytest.mark.asyncio
async def test_get_academy_notifications_uses_parent_digest_env_fallback_when_override_unset():
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "notifications": {
            "daily_digest_to_admin": False,
        },
    }
    use_case = GetAcademyNotificationsUseCase(
        academy_repo=repo,
        default_parent_digest_enabled=True,
        default_parent_digest_hour=7,
    )

    output = await use_case.execute("acad-1")

    assert output.parent_digest_enabled is True
    assert output.parent_digest_hour == 7


@pytest.mark.asyncio
async def test_update_academy_notifications_persists_parent_digest_fields():
    repo = AsyncMock()
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "notifications": {
            "parent_digest_enabled": True,
            "parent_digest_hour": 8,
        },
    }
    use_case = UpdateAcademyNotificationsUseCase(academy_repo=repo)
    output = await use_case.execute(
        "acad-1", {"parent_digest_enabled": True, "parent_digest_hour": 8}
    )
    assert output.parent_digest_enabled is True
    assert output.parent_digest_hour == 8
    repo.update_by_id.assert_awaited_once_with(
        "acad-1",
        {
            "notifications.parent_digest_enabled": True,
            "notifications.parent_digest_hour": 8,
        },
    )


@pytest.mark.asyncio
async def test_update_academy_notifications_rejects_bad_parent_digest_hour():
    repo = AsyncMock()
    use_case = UpdateAcademyNotificationsUseCase(academy_repo=repo)
    with pytest.raises(ValueError):
        await use_case.execute("acad-1", {"parent_digest_hour": 24})
    repo.update_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_academy_notifications():
    repo = AsyncMock()
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "daily_digest_to_admin": True,
    }
    use_case = UpdateAcademyNotificationsUseCase(academy_repo=repo)
    output = await use_case.execute("acad-1", {"daily_digest_to_admin": True})
    assert output.daily_digest_to_admin is True
    repo.update_by_id.assert_awaited_once_with(
        "acad-1", {"notifications.daily_digest_to_admin": True}
    )


@pytest.mark.asyncio
async def test_a_zero_late_fee_reads_back_as_zero_not_none() -> None:
    """`or` collapsed a stored 0 to the legacy alias and then to None.

    The Billing rules panel showed the field blank right after saving 0, so the
    owner retyped it and every save wrote another audit entry claiming
    `null -> 0` for a change that had already landed.
    """
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "fees": {"late_fee_cents": 0, "grace_days": 0},
    }

    result = await GetAcademyFeesUseCase(academy_repo=repo).execute("acad-1")

    assert result.late_fee_cents == 0
    assert result.grace_days == 0


@pytest.mark.asyncio
async def test_a_late_cancellation_amount_is_never_read_as_the_late_fee() -> None:
    """Money audit X8 (2026-09-25).

    ``late_cancellation_fee_cents`` is the fee for cancelling a class with
    short notice. The hourly late-fee pass read it as the late-*payment* fee
    whenever ``late_fee_cents`` was absent, and charged it on every overdue
    invoice.
    """
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "fees": {"late_cancellation_fee_cents": 750},
    }

    result = await GetAcademyFeesUseCase(academy_repo=repo).execute("acad-1")

    assert result.late_fee_cents is None


@pytest.mark.asyncio
async def test_fees_are_read_only_from_the_fees_subdocument() -> None:
    """An academy doc with no ``fees`` was read flat, so any top-level
    ``late_fee_cents``/``late_cancellation_fee_cents`` became a charge."""
    repo = AsyncMock()
    repo.find_by_id.return_value = {
        "_id": "acad-1",
        "late_fee_cents": 1500,
        "late_cancellation_fee_cents": 750,
        "grace_days": 3,
    }

    result = await GetAcademyFeesUseCase(academy_repo=repo).execute("acad-1")

    assert result.late_fee_cents is None
    assert result.grace_days is None


@pytest.mark.parametrize("stored", [None, 0])
@pytest.mark.asyncio
async def test_turning_the_late_fee_on_stamps_when_it_took_effect(stored: int | None) -> None:
    """The late-fee pass only charges invoices that become late after this."""
    now = datetime(2026, 9, 25, 15, 0, tzinfo=UTC)
    repo = AsyncMock()
    repo.find_by_id.return_value = {"_id": "acad-1", "fees": {"late_fee_cents": stored}}
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "fees": {"late_fee_cents": 500, "late_fee_effective_from": now},
    }

    output = await UpdateAcademyFeesUseCase(academy_repo=repo, clock=lambda: now).execute(
        "acad-1", {"late_fee_cents": 500}
    )

    repo.update_by_id.assert_awaited_once_with(
        "acad-1", {"fees.late_fee_cents": 500, "fees.late_fee_effective_from": now}
    )
    assert output.late_fee_effective_from == now


@pytest.mark.asyncio
async def test_update_response_does_not_echo_the_late_cancellation_alias() -> None:
    repo = AsyncMock()
    repo.find_by_id.return_value = {"_id": "acad-1", "fees": {"late_fee_cents": 500}}
    repo.update_by_id.return_value = {
        "_id": "acad-1",
        "fees": {"late_fee_cents": 0, "late_cancellation_fee_cents": 750, "grace_days": 2},
    }

    output = await UpdateAcademyFeesUseCase(academy_repo=repo).execute(
        "acad-1", {"late_fee_cents": 0}
    )

    assert output.late_fee_cents == 0
