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
