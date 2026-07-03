from unittest.mock import AsyncMock

import pytest
from backend.v2.contexts.identity.application.change_user_role_use_case import (
    ChangeUserRole,
    ChangeUserRoleCommand,
)
from backend.v2.contexts.identity.application.get_academy_gateway_use_case import (
    GetAcademyGatewayUseCase,
)
from backend.v2.contexts.identity.application.use_cases.admin_directory import (
    AdminUserSummary,
)
from backend.v2.contexts.identity.domain.errors import UserNotFound


@pytest.mark.asyncio
async def test_gateway_masks_stripe_account_and_defaults_manual_methods():
    repo = AsyncMock()
    repo.find_by_id.return_value = {"stripe_account_id": "acct_1234567890"}

    output = await GetAcademyGatewayUseCase(repo).execute("acad")

    assert output.stripe_connected is True
    assert output.stripe_account_id_masked == "acct...7890"
    assert output.manual_methods == ["cash", "check"]


@pytest.mark.asyncio
async def test_gateway_prefers_connected_account_reader_when_ready():
    repo = AsyncMock()
    repo.find_by_id.return_value = {"stripe_account_id": None}
    reader = AsyncMock()
    reader.get_status_for_academy.return_value = (True, "acct_9876543210")

    output = await GetAcademyGatewayUseCase(repo, connected_accounts=reader).execute("acad")

    reader.get_status_for_academy.assert_awaited_once_with("acad")
    assert output.stripe_connected is True
    assert output.stripe_account_id_masked == "acct...3210"


@pytest.mark.asyncio
async def test_gateway_connected_account_reader_overrides_stale_legacy_field():
    # A legacy `academy.stripe_account_id` from the old OAuth flow must not
    # report "connected" once the new Connect-account reader is wired — that
    # field is no longer read by any billing/charging code path.
    repo = AsyncMock()
    repo.find_by_id.return_value = {"stripe_account_id": "acct_1234567890"}
    reader = AsyncMock()
    reader.get_status_for_academy.return_value = (False, None)

    output = await GetAcademyGatewayUseCase(repo, connected_accounts=reader).execute("acad")

    assert output.stripe_connected is False
    assert output.stripe_account_id_masked is None


@pytest.mark.asyncio
async def test_change_user_role_requires_same_academy_match():
    repo = AsyncMock()
    repo.change_role.return_value = AdminUserSummary(
        user_id="user-1",
        email="user@example.com",
        display_name="User One",
        role="coach",
        status="active",
    )

    output = await ChangeUserRole(repo).execute(
        "user-1",
        ChangeUserRoleCommand(
            role="coach",
            actor_id="admin-1",
            reason="Coach onboarding",
        ),
        academy_id="acad",
    )

    assert output.role == "coach"
    repo.change_role.assert_awaited_once_with(
        "user-1",
        "coach",
        academy_id="acad",
        actor_id="admin-1",
        reason="Coach onboarding",
    )


@pytest.mark.asyncio
async def test_change_user_role_raises_when_target_not_in_academy():
    repo = AsyncMock()
    repo.change_role.return_value = None

    with pytest.raises(UserNotFound):
        await ChangeUserRole(repo).execute(
            "user-1",
            ChangeUserRoleCommand(
                role="coach",
                actor_id="admin-1",
                reason="Coach onboarding",
            ),
            academy_id="other-acad",
        )
